"""
compliance_agent.py — ARIA AI Compliance & Safety Layer v1.

Legal and ethical compliance agent that:
1. Reviews proposed actions before executing them
2. Maintains a list of absolutely prohibited patterns
3. Implements the system's "emergency brake"
4. Auto-approves low-risk categories based on history
5. Learns new regulations and updates internal policies

Principle: ARIA ALWAYS operates within legal and ethical limits.
When in doubt, consult the human supervisor via Telegram.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.compliance_agent")

# Absolutely prohibited patterns — NEVER approved under any circumstances
HARD_PROHIBITIONS: list[str] = [
    "spam",
    "phishing",
    "malware",
    "ddos",
    "ransomware",
    "hack",
    "unauthorized_access",
    "brute_force",
    "fake_reviews",
    "astroturfing",
    "deceptive_advertising",
    "copyright_infringement",
    "plagiarism",
    "data_theft",
    "illegal_content",
    "pyramid_scheme",
    "ponzi_scheme",
    "money_laundering",
    "tax_evasion",
    "insider_trading",
    "identity_theft",
    "social_engineering_attack",
    "scrape_without_permission",
    "gdpr_violation",
]

# Low-risk categories — auto-approved with no additional review
AUTO_APPROVE_CATEGORIES: list[str] = [
    "content_creation",
    "seo_optimization",
    "blog_post",
    "email_newsletter",
    "social_media_post",
    "tweet",
    "market_research",
    "trend_analysis",
    "competitor_analysis",
    "product_listing",
    "affiliate_link",
    "product_description",
    "api_integration",
    "code_improvement",
    "bug_fix",
    "data_analysis",
    "performance_optimization",
    "digital_product",
    "ebook",
    "template",
    "course_outline",
    "keyword_research",
    "backlink_outreach",
]


class ComplianceAgent(BaseAgent):
    """
    ARIA AI's legal, ethical, and operational compliance agent.
    Acts as a safety layer before high-impact actions.
    """

    def __init__(self) -> None:
        super().__init__(
            name="compliance",
            description="Legal/ethical review — emergency brake — low-risk auto-approval",
            capabilities=[
                "legal_review",
                "ethics_check",
                "risk_assessment",
                "policy_enforcement",
                "emergency_brake",
                "auto_approval",
                "normative_learning",
            ],
        )
        self._emergency_brake_active: bool = False
        self._violation_count: int = 0
        self._approved_count: int = 0
        self._rejected_count: int = 0

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mode = context.get("mode", "review")
        if mode == "review":
            return await self._review_action(context)
        if mode == "emergency_brake":
            return await self._activate_emergency_brake(context.get("reason", "Manual activation"))
        if mode == "reset":
            return self._deactivate_emergency_brake()
        if mode == "status":
            return self._get_status()
        if mode == "learn_normative":
            return await self._learn_normative(context.get("source", ""))
        return await self._review_action(context)

    # ══════════════════════════════════════════════════════════════
    # ACTION REVIEW
    # ══════════════════════════════════════════════════════════════

    async def _review_action(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Reviews whether a proposed action is legal, ethical, and safe.
        Returns: {approved, risk_level, reason, needs_human_review}
        """
        if self._emergency_brake_active:
            return {
                "success": True,
                "approved": False,
                "risk_level": "EMERGENCY",
                "reason": "System in emergency brake mode — all actions blocked.",
                "needs_human_review": True,
            }

        action_type = context.get("action_type", "unknown").lower()
        description = context.get("description", "").lower()
        amount_usd = float(context.get("amount_usd", 0))
        full_text = f"{action_type} {description}"

        # 1. Check absolute prohibitions
        for prohibition in HARD_PROHIBITIONS:
            if prohibition.replace("_", " ") in full_text or prohibition in full_text:
                self._violation_count += 1
                self._rejected_count += 1
                logger.warning("[Compliance] REJECTED — prohibited pattern: '%s'", prohibition)
                if self._violation_count >= 5:
                    await self._activate_emergency_brake(
                        f"Multiple violations detected ({self._violation_count})"
                    )
                return {
                    "success": True,
                    "approved": False,
                    "risk_level": "HIGH",
                    "reason": f"Action rejected — prohibited pattern: '{prohibition}'",
                    "violation_count": self._violation_count,
                    "needs_human_review": True,
                }

        # 2. Auto-approve low-risk categories
        for category in AUTO_APPROVE_CATEGORIES:
            if category.replace("_", " ") in full_text or category in action_type:
                self._approved_count += 1
                return {
                    "success": True,
                    "approved": True,
                    "risk_level": "LOW",
                    "reason": f"Auto-approved — low-risk category: {category}",
                    "auto_approved": True,
                    "needs_human_review": False,
                }

        # 3. Actions with cost or high impact — AI review
        if amount_usd > 0 or any(
            kw in full_text for kw in ["delete", "deploy", "publish", "send_bulk", "purchase"]
        ):
            return await self._ai_review(action_type, description, amount_usd)

        # 4. Default: approve with medium risk
        self._approved_count += 1
        return {
            "success": True,
            "approved": True,
            "risk_level": "MEDIUM",
            "reason": "Approved — no prohibited pattern detected",
            "needs_human_review": False,
        }

    async def _ai_review(
        self,
        action_type: str,
        description: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """Detailed AI review for higher-impact actions."""
        try:
            from apps.core.tools.ai_client import get_ai_client

            ai = get_ai_client()
            if not ai:
                # A compliance gate for costed/high-impact actions (delete,
                # deploy, publish, send_bulk, purchase) must fail CLOSED when
                # it can't actually review — auto-approving "provisionally"
                # defeats the entire point of gating these actions.
                self._rejected_count += 1
                return {
                    "success": True,
                    "approved": False,
                    "risk_level": "HIGH",
                    "reason": "AI not available for review — action blocked, requires human approval",
                    "needs_human_review": True,
                }

            cost_str = f"${amount_usd:.2f} USD"
            resp = await ai.complete(
                system=(
                    "You are ARIA AI's legal and ethical compliance agent. "
                    "Evaluate whether the action is legal, ethical, and safe. "
                    "Respond ONLY with valid JSON: "
                    '{"approved": true, "risk_level": "LOW", "reason": "str", "concerns": []}'
                ),
                user=(
                    f"Action: {action_type}\n"
                    f"Description: {description}\n"
                    f"Cost: {cost_str}\n\n"
                    "Evaluate: GDPR, copyright, spam, platform ToS, fraud, "
                    "deceptive advertising, privacy."
                ),
                model=AIModel.FAST,
                json_mode=True,
            )

            if resp and resp.success:
                data = resp.content
                if isinstance(data, str):
                    match = re.search(r"\{.*\}", data, re.DOTALL)
                    data = json.loads(match.group()) if match else {}
                approved = data.get("approved", True)
                if approved:
                    self._approved_count += 1
                else:
                    self._rejected_count += 1
                return {
                    "success": True,
                    "approved": approved,
                    "risk_level": data.get("risk_level", "MEDIUM"),
                    "reason": data.get("reason", ""),
                    "concerns": data.get("concerns", []),
                    "ai_reviewed": True,
                    "needs_human_review": data.get("risk_level") == "HIGH",
                }
        except Exception as exc:
            logger.error("[Compliance] ai_review error: %s", exc)

        # Same fail-closed rule as the "AI not available" branch above: a
        # broken review must block the action, not wave it through.
        self._rejected_count += 1
        return {
            "success": True,
            "approved": False,
            "risk_level": "HIGH",
            "reason": "Error in AI review — action blocked, requires human approval",
            "needs_human_review": True,
        }

    # ══════════════════════════════════════════════════════════════
    # EMERGENCY BRAKE
    # ══════════════════════════════════════════════════════════════

    async def _activate_emergency_brake(self, reason: str) -> dict[str, Any]:
        """
        Activates the emergency brake.
        Stops all autonomous operations and notifies the supervisor.
        To deactivate: send /compliance_reset to the Telegram bot.
        """
        self._emergency_brake_active = True
        logger.critical("[Compliance] EMERGENCY BRAKE ACTIVATED: %s", reason)

        violations_count = self._violation_count
        await self._send_telegram(
            f"EMERGENCY BRAKE ACTIVATED\n\n"
            f"Reason: {reason}\n\n"
            f"ARIA has paused all autonomous operations.\n"
            f"Accumulated violations: {violations_count}\n\n"
            f"To reactivate the system, send:\n"
            f"/compliance_reset"
        )

        return {
            "success": True,
            "emergency_brake": True,
            "active": True,
            "reason": reason,
            "message": "System paused — human intervention required.",
        }

    def _deactivate_emergency_brake(self) -> dict[str, Any]:
        """Deactivates the emergency brake (only via human intervention)."""
        self._emergency_brake_active = False
        self._violation_count = 0
        logger.info("[Compliance] Emergency brake deactivated by operator")
        return {
            "success": True,
            "emergency_brake": False,
            "message": "System reactivated by operator",
        }

    # ══════════════════════════════════════════════════════════════
    # REGULATORY LEARNING
    # ══════════════════════════════════════════════════════════════

    async def _learn_normative(self, source: str) -> dict[str, Any]:
        """
        ARIA learns from new legal/ethical regulations.
        Extracts rules from the source and updates internal policies.
        """
        if not source:
            return {"success": False, "error": "A source is required (URL or regulatory text)"}

        try:
            from apps.core.tools.ai_client import get_ai_client

            ai = get_ai_client()
            if not ai:
                return {"success": False, "error": "AI not available"}

            resp = await ai.complete(
                system=(
                    "Expert in digital regulation, privacy, and AI ethics. "
                    "Extract rules applicable to an autonomous AI monetization system. "
                    "Respond ONLY with JSON: "
                    '{"rules": ["rule"], "prohibitions": ["pattern"], "recommendations": ["rec"]}'
                ),
                user=f"Regulatory source:\n{source[:3000]}\n\nExtract rules for ARIA AI.",
                model=AIModel.STRATEGY,
                json_mode=True,
            )

            if resp and resp.success:
                data = resp.content
                if isinstance(data, str):
                    match = re.search(r"\{.*\}", data, re.DOTALL)
                    data = json.loads(match.group()) if match else {}

                new_prohibitions = data.get("prohibitions", [])
                added = []
                for p in new_prohibitions:
                    p_lower = p.lower().replace(" ", "_")
                    if p_lower not in HARD_PROHIBITIONS:
                        HARD_PROHIBITIONS.append(p_lower)
                        added.append(p_lower)

                return {
                    "success": True,
                    "rules_learned": len(data.get("rules", [])),
                    "prohibitions_added": added,
                    "total_prohibitions": len(HARD_PROHIBITIONS),
                    "recommendations": data.get("recommendations", []),
                }
        except Exception as exc:
            logger.error("[Compliance] learn_normative error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # STATUS
    # ══════════════════════════════════════════════════════════════

    def _get_status(self) -> dict[str, Any]:
        return {
            "success": True,
            "emergency_brake_active": self._emergency_brake_active,
            "violation_count": self._violation_count,
            "total_approved": self._approved_count,
            "total_rejected": self._rejected_count,
            "hard_prohibitions_count": len(HARD_PROHIBITIONS),
            "auto_approve_categories_count": len(AUTO_APPROVE_CATEGORIES),
            "prohibitions_sample": HARD_PROHIBITIONS[:5],
        }


# ── SINGLETON ─────────────────────────────────────────────
# A fresh instance per call would silently reset _violation_count each time,
# defeating the 5-strikes emergency-brake escalation in _review_action() —
# callers (base_agent.py's execute_with_approval) must share one instance.
_compliance_agent: ComplianceAgent | None = None


def get_compliance_agent() -> ComplianceAgent:
    global _compliance_agent
    if _compliance_agent is None:
        _compliance_agent = ComplianceAgent()
    return _compliance_agent
