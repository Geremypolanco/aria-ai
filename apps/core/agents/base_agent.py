"""
BaseAgent — Base class for all Aria AI agents.

Fundamental principle: ARIA never simulates. If it cannot perform an action
because it lacks an API key or a service, it states so explicitly.
"""

from __future__ import annotations

import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from apps.core.config import settings
from apps.core.tools.ai_client import AIModel, get_ai_client

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

logger = logging.getLogger("aria.base_agent")
TELEGRAM_API = "https://api.telegram.org/bot"


@dataclass
class AgentMetrics:
    tasks_attempted: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0
    total_latency_ms: int = 0
    revenue_generated: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.tasks_attempted == 0:
            return 100.0
        return round(self.tasks_succeeded / self.tasks_attempted * 100, 1)

    @property
    def avg_latency_ms(self) -> int:
        if self.tasks_succeeded == 0:
            return 0
        return self.total_latency_ms // self.tasks_succeeded


class BaseAgent(ABC):
    """
    Base class for all Aria AI agents.
    Policy: no method returns fake or simulated data.
    If an API key or service is missing, an explicit error is returned.
    """

    APPROVAL_THRESHOLD_USD: float = float(getattr(settings, "MAX_SPEND_WITHOUT_APPROVAL_USD", 0.0))
    REQUIRE_APPROVAL_FOR_PAYMENTS: bool = bool(getattr(settings, "REQUIRE_APPROVAL_FOR_PAYMENTS", True))

    # Global map: capability_name -> required env_var
    CAPABILITY_ENV_MAP: dict[str, str] = {
        "gumroad": "GUMROAD_TOKEN",
        "stripe": "STRIPE_SECRET_KEY",
        "paypal": "PAYPAL_CLIENT_ID",
        "shopify": "SHOPIFY_URL",
        "mailchimp": "MAILCHIMP_API_KEY",
        "buffer": "BUFFER_TOKEN",
        "google": "GOOGLE_API_KEY",
        "youtube": "GOOGLE_API_KEY",
        "elevenlabs": "ELEVENLABS_API_KEY",
        "pexels": "PEXELS_API_KEY",
        "cloudinary": "CLOUDINARY_CLOUD_NAME",
        "canva": "CANVA_CLIENT_ID",
        "airtable": "AIRTABLE_TOKEN",
        "news": "NEWS_API_KEY",
        "serp": "SERP_API_KEY",
        "telegram": "TELEGRAM_TOKEN",
        "github": "GITHUB_TOKEN",
        "huggingface": "HF_TOKEN",
        "groq": "GROQ_API_KEY",
        "openai": "OPENAI_API_KEY",
        "supabase": "SUPABASE_URL",
        "redis": "UPSTASH_REDIS_REST_URL",
        "medium": "MEDIUM_TOKEN",
        "devto": "DEVTO_API_KEY",
        "hashnode": "HASHNODE_TOKEN",
        "amazon": "AMAZON_ASSOCIATE_TAG",
        "affiliate": "AMAZON_ASSOCIATE_TAG",
        "notion": "NOTION_TOKEN",
        "vercel": "VERCEL_TOKEN",
        "meta_ads": "FACEBOOK_MARKETING_TOKEN",
        "gmail": "GOOGLE_API_KEY",
        "calendar": "GOOGLE_API_KEY",
        "drive": "GOOGLE_API_KEY",
        "screenshot": "SCREENSHOT_API_KEY",
    }

    def __init__(self, name: str, description: str, capabilities: list[str]) -> None:
        self.name = name
        self.description = description
        self.capabilities = capabilities
        self.agent_id = str(uuid.uuid4())
        self.metrics = AgentMetrics()
        self._http = httpx.AsyncClient(timeout=15.0)
        self._consecutive_failures = 0
        self._circuit_open = False
        self._circuit_open_until: float = 0.0
        logger.info("[%s] Agent initialized", self.name)

    # ── LIFECYCLE ──────────────────────────────────────────

    async def start(self) -> None:
        await self._register_in_supabase()
        logger.info("[%s] Agent ready", self.name)

    async def stop(self) -> None:
        await self._http.aclose()
        logger.info("[%s] Agent stopped", self.name)

    # ── MAIN EXECUTION ─────────────────────────────────────

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        """Main entry point with circuit breaker."""
        if not self._is_circuit_available():
            wait_secs = int(self._circuit_open_until - time.monotonic())
            return {
                "success": False,
                "error": (
                    f"{self.name}: circuit breaker open — too many consecutive failures. "
                    f"Try again in ~{wait_secs}s."
                ),
                "circuit_open": True,
            }

        self.metrics.tasks_attempted += 1
        start_ts = time.monotonic()
        try:
            result = await self._execute(context)
            elapsed_ms = int((time.monotonic() - start_ts) * 1000)
            if result.get("success", False):
                self.metrics.tasks_succeeded += 1
                self.metrics.total_latency_ms += elapsed_ms
                self._consecutive_failures = 0
                if rev := result.get("revenue_generated"):
                    self.metrics.revenue_generated += rev
            else:
                self.metrics.tasks_failed += 1
                self._consecutive_failures += 1
                self._check_circuit_breaker()
                logger.warning(
                    "[%s] Task failed: %s", self.name, result.get("error", "no detail")
                )
            result["agent_metrics"] = {
                "tasks_attempted": self.metrics.tasks_attempted,
                "success_rate": self.metrics.success_rate,
                "avg_latency_ms": self.metrics.avg_latency_ms,
            }
            return result
        except Exception as exc:
            self.metrics.tasks_failed += 1
            self._consecutive_failures += 1
            self._check_circuit_breaker()
            logger.error("[%s] Exception in _execute: %s", self.name, exc, exc_info=True)
            return {"success": False, "error": str(exc), "agent": self.name}

    @abstractmethod
    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Implement in each concrete agent."""

    # ── CAPABILITY CHECK ──────────────────────────────────

    def check_capabilities(self) -> dict[str, Any]:
        """
        Checks in real time what this agent can and CANNOT do.
        Never simulates — reports the real status of each API dependency.
        Call from Telegram with /agents to see full status.
        """
        available: list[str] = []
        unavailable: list[str] = []

        for cap in self.capabilities:
            cap_lower = cap.lower()
            required_env: str | None = None
            for keyword, env_var in self.CAPABILITY_ENV_MAP.items():
                if keyword in cap_lower:
                    required_env = env_var
                    break

            if required_env:
                val = getattr(settings, required_env, None)
                if val:
                    available.append(cap)
                else:
                    unavailable.append(f"{cap} [requires {required_env}]")
            else:
                # Capability with no external dependency (e.g. planning, base AI)
                available.append(cap)

        return {
            "agent": self.name,
            "description": self.description,
            "available": available,
            "unavailable": unavailable,
            "fully_operational": len(unavailable) == 0,
            "operational_pct": round(len(available) / max(len(self.capabilities), 1) * 100),
        }

    # ── AI-POWERED THINKING ────────────────────────────────

    async def think(
        self,
        system: str,
        user: str,
        model: AIModel = AIModel.FAST,
        json_mode: bool = False,
        max_tokens: int = 2000,
        inject_business_intelligence: bool = True,
    ) -> str | None:
        """
        Calls the AI and returns text.
        Enforces a relaxed, direct, no-nonsense personality.
        """
        # Personality and reasoning style
        relaxed_persona = (
            "\n\n[PERSONALITY & REASONING]: You are ARIA. Speak directly, intelligently, and without unnecessary formality. "
            "Think step by step before responding. Be thorough: if the user asks for analysis, give a complete analysis; "
            "if they ask for strategy, give a detailed strategy with actionable steps. "
            "Never give vague or incomplete answers. If you need data, look it up; if you can't look it up, say so. "
            "Use markdown (lists, bold, sections) when it improves clarity. "
            "If something is impossible, say so clearly with real alternatives. If you're going to monetize, do it with confidence and detail."
        )
        system += relaxed_persona

        if inject_business_intelligence:
            try:
                from apps.core.intelligence.sales_knowledge import (
                    SALES_TECHNIQUES,
                    VOCABULARY_EXPANSION,
                )

                intelligence_context = (
                    f"\n\n[BUSINESS INTELLIGENCE]:\n"
                    f'Techniques: {SALES_TECHNIQUES["copywriting"]}\n'
                    f'Persuasive Vocabulary: {VOCABULARY_EXPANSION["persuasive_verbs"]}\n'
                )
                system += intelligence_context
            except ImportError:
                pass
        try:
            ai = get_ai_client()
            response = await ai.complete(
                system=system,
                user=user,
                model=model,
                json_mode=json_mode,
                max_tokens=max_tokens,
            )
            if response and response.success:
                return (
                    response.content if isinstance(response.content, str) else str(response.content)
                )
            logger.warning("[%s] think() got no AI response — provider unavailable", self.name)
            return None
        except Exception as exc:
            logger.error("[%s] think() error: %s", self.name, exc)
            return None

    # ── HUMAN APPROVAL ─────────────────────────────────────

    async def request_human_approval(
        self,
        action: str,
        details: str,
        amount_usd: float = 0.0,
    ) -> dict[str, Any]:
        """
        Requests supervisor approval via Telegram.
        EXPLICIT ERROR if Telegram is not configured — never auto-approves.
        """
        if not settings.TELEGRAM_TOKEN or not settings.TELEGRAM_CHAT_ID:
            return {
                "success": False,
                "error": (
                    "Human approval required but TELEGRAM_TOKEN or TELEGRAM_CHAT_ID "
                    "is not configured. Action blocked for safety."
                ),
                "action_blocked": True,
            }
        try:
            db = _get_db()
            approval_id = str(uuid.uuid4())[:8]
            db.table("approvals").insert(
                {
                    "id": approval_id,
                    "agent": self.name,
                    "action": action,
                    "details": details,
                    "amount_usd": amount_usd,
                    "status": "pending",
                }
            ).execute()

            msg = (
                f"⚠️ <b>Approval required</b>\n\n"
                f"<b>Agent:</b> {self.name}\n"
                f"<b>Action:</b> {action}\n"
                f"<b>Details:</b> {details}\n"
                + (f"<b>Amount:</b> ${amount_usd:.2f}\n" if amount_usd > 0 else "")
                + f"\n<b>ID:</b> <code>{approval_id}</code>\n\n"
                f"/approve {approval_id}  |  /reject {approval_id}"
            )
            await self._send_telegram(msg)
            return {
                "success": True,
                "approval_id": approval_id,
                "status": "pending",
                "message": f"Approval requested from supervisor (ID: {approval_id})",
            }
        except Exception as exc:
            logger.error("[%s] request_approval error: %s", self.name, exc)
            return {"success": False, "error": str(exc)}

    async def execute_with_approval(
        self,
        action: str,
        details: str,
        fn: Callable[[], Coroutine],
        amount_usd: float = 0.0,
    ) -> dict[str, Any]:
        """Runs the action through ComplianceAgent first, then executes fn()
        directly or requests human approval depending on the outcome and amount.

        ComplianceAgent used to be unreachable from any live code path — every
        caller (just cfo_agent.py today) went straight from "how much does
        this cost" to fn()/request_human_approval, with no legal/ethical/policy
        screen at all. That gap was concrete: cfo_agent.py calls this with
        amount_usd=0.0 for "Publish ebook to Gumroad" (the ebook's own price is
        passed separately, in `details`, not as amount_usd) — a $0 amount never
        clears APPROVAL_THRESHOLD_USD, so a paid product's publish action
        would run unreviewed. ComplianceAgent's own category check catches
        "publish" regardless of amount_usd and routes it through review.
        """
        from apps.core.agents.compliance_agent import get_compliance_agent

        review = await get_compliance_agent().run(
            {
                "mode": "review",
                "action_type": action,
                "description": details,
                "amount_usd": amount_usd,
            }
        )
        if review.get("success") and not review.get("approved", True):
            return {
                "success": False,
                "error": review.get("reason", "Blocked by compliance review."),
                "compliance_blocked": True,
                "risk_level": review.get("risk_level"),
            }
        if review.get("success") and review.get("needs_human_review"):
            return await self.request_human_approval(action, details, amount_usd)
        if amount_usd <= self.APPROVAL_THRESHOLD_USD and not self.REQUIRE_APPROVAL_FOR_PAYMENTS:
            return await fn()
        return await self.request_human_approval(action, details, amount_usd)

    # ── SUPABASE / LOGGING ────────────────────────────────

    async def _register_in_supabase(self) -> None:
        try:
            db = _get_db()
            db.table("agents").upsert(
                {
                    "name": self.name,
                    "description": self.description,
                    "capabilities": self.capabilities,
                    "status": "active",
                    "agent_id": self.agent_id,
                }
            ).execute()
        except Exception as exc:
            logger.warning("[%s] Could not register in Supabase: %s", self.name, exc)

    async def _log(self, event: str, message: str, metadata: dict | None = None) -> None:
        try:
            db = _get_db()
            db.table("system_logs").insert(
                {
                    "agent": self.name,
                    "event": event,
                    "message": message,
                    "metadata": metadata or {},
                }
            ).execute()
        except Exception as exc:
            logger.debug("[%s] _log error (non-critical): %s", self.name, exc)

    # ── TELEGRAM ──────────────────────────────────────────

    async def _send_telegram(self, message: str) -> bool:
        """Sends a Telegram message. Returns False (no exception) if not configured."""
        if not settings.TELEGRAM_TOKEN or not settings.TELEGRAM_CHAT_ID:
            logger.warning("[%s] Telegram not configured — message not sent", self.name)
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"{TELEGRAM_API}{settings.TELEGRAM_TOKEN}/sendMessage",
                    json={
                        "chat_id": settings.TELEGRAM_CHAT_ID,
                        "text": message,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                return res.status_code == 200
        except Exception as exc:
            logger.error("[%s] Telegram error: %s", self.name, exc)
            return False

    # ── CIRCUIT BREAKER ───────────────────────────────────

    def _is_circuit_available(self) -> bool:
        if not self._circuit_open:
            return True
        if time.monotonic() > self._circuit_open_until:
            self._circuit_open = False
            self._consecutive_failures = 0
            logger.info("[%s] Circuit breaker closed — resetting", self.name)
            return True
        return False

    def _check_circuit_breaker(self) -> None:
        if self._consecutive_failures >= 5:
            cooldown = min(300, 60 * self._consecutive_failures)
            self._circuit_open = True
            self._circuit_open_until = time.monotonic() + cooldown
            logger.error(
                "[%s] Circuit breaker OPEN for %ds (%d consecutive failures)",
                self.name,
                cooldown,
                self._consecutive_failures,
            )


def _get_db():
    """Helper to get the Supabase client."""
    from apps.core.memory.supabase_client import get_db

    return get_db()._client
