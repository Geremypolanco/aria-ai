"""
guardrails.py — Aria's 4-layer safety/alignment pipeline.

Aria is an autonomous agent with real capabilities that carry real risk:
it can write and run code (execute_code), drive a browser (computer_use),
post to the owner's live social accounts (post_to_social), and spend real
AI budget against a tracked ledger (cost_ledger). This module exists to
make sure none of that can be turned toward fraud, illegal activity, or
abuse — categorically, not just "the model usually refuses."

Four independent layers, each able to block on its own (defense in depth —
a bypass or bug in one layer doesn't remove the others):

  1. Input moderation      — moderate_input(): two-pass (fast keyword/regex
     screen, then an LLM classifier) check on the raw user message, before
     it ever reaches AriaMind's planner.
  2. Constitutional review — evaluate_plan(): a second LLM call judges the
     *specific tool + arguments* the planner chose against a legality/ethics
     rubric, returning {"safe": bool, "risk_score": 0-1, "reason": str}.
     Fails CLOSED — if the evaluator can't be reached or returns garbage,
     the plan is treated as unsafe rather than silently allowed through.
  3. Deterministic firewall — check_code_safety() / check_content_safety():
     regex + (when available) `bandit` static analysis on code the agent is
     about to run, and phishing/credential-harvesting pattern checks on
     content it's about to publish. Layers 1-2 are probabilistic (an LLM
     judging an LLM); this layer is regex/AST-deterministic on purpose, so
     it can't be talked out of blocking a known-bad pattern.
  4. Kill switch + anomaly watch — KillSwitch: a Redis-persisted emergency
     freeze (global or per-user), reusing the same storage pattern as
     CostLedger's frozen-user flag, plus record_and_check_anomaly() which
     watches for burst patterns (repeated Layer 2 rejections, blocked-code
     attempts) and can trip the switch on its own. main.py's existing
     Global Panic button and this kill switch both gate the same request
     paths — either one freezes execution.

GUARDRAILS_ENABLED (apps.core.config.settings) defaults to True. It exists
so the owner can disable the pipeline for local debugging without deleting
code — it is NOT a way to bypass ethics/legality review in production, and
nothing in this module reads it as such.
"""

from __future__ import annotations

import json
import logging
import re
import time
from contextlib import suppress
from dataclasses import dataclass, field

logger = logging.getLogger("aria.safety.guardrails")

# ── Layer 1: prohibited-category taxonomy ───────────────────────────────
# Deliberately broad keyword/phrase triggers for a fast, cheap first pass.
# False positives here are fine (they just fall through to the LLM
# classifier for a real judgment); false negatives are what the LLM pass
# exists to catch.
PROHIBITED_CATEGORIES: dict[str, list[str]] = {
    "malware": [
        "ransomware",
        "keylogger",
        "write a virus",
        "ddos script",
        "botnet",
        "reverse shell",
        "exploit kit",
        "bypass antivirus",
    ],
    "fraud": [
        "fake invoice",
        "credit card generator",
        "carding",
        "chargeback fraud",
        "ponzi scheme",
        "pump and dump",
        "wire fraud",
        "romance scam",
    ],
    "tax_evasion": [
        "hide income from",
        "evade taxes",
        "unreported income scheme",
        "offshore shell to avoid tax",
        "fake receipts for deduction",
    ],
    "identity_theft": [
        "steal someone's identity",
        "fake id for",
        "clone a credit card",
        "synthetic identity",
        "impersonate a bank",
    ],
    "phishing": [
        "phishing page",
        "fake login page",
        "credential harvesting",
        "spoof paypal",
        "spoof a bank site",
        "clone the login page",
    ],
    "unauthorized_pharma": [
        "sell prescription drugs without",
        "counterfeit medication",
        "unlicensed pharmacy",
        "controlled substance without a prescription",
    ],
    "copyright_infringement": [
        "crack this software",
        "pirate this",
        "remove drm",
        "keygen for",
        "bypass license check",
    ],
    "csam": [],  # never keyword-matched here; always routed to the LLM
    # classifier with zero tolerance — no keyword list is safe to publish
    # for this category, and the classifier prompt covers it explicitly.
}

# ── Layer 3: known-dangerous code patterns (Python) ─────────────────────
_DANGEROUS_CODE_PATTERNS: list[tuple[str, str]] = [
    (r"\bos\.system\s*\(", "shells out via os.system"),
    (r"\bsubprocess\.\w+\([^)]*shell\s*=\s*True", "subprocess with shell=True"),
    (r"\beval\s*\(", "uses eval()"),
    (r"\bexec\s*\(", "uses exec() on dynamic input"),
    (r"\b__import__\s*\(\s*['\"]os['\"]", "dynamically imports os"),
    (r"\bsocket\.\w*\bconnect\b.*\b(4444|1337|31337)\b", "connects to a common backdoor port"),
    (r"rm\s+-rf\s+/", "recursive delete from filesystem root"),
    (r"\bshutil\.rmtree\s*\(\s*['\"]/", "recursively deletes from filesystem root"),
    (r"base64\.b64decode\([^)]*\).*exec", "decodes and executes an obfuscated payload"),
    (r"\bkeylogger\b|\bkeystrok\w*\s*logg", "keylogging behavior"),
    (r"smtplib.*for\s+\w+\s+in\s+.*(emails|recipients|leads)", "bulk unsolicited email loop"),
]

_PHISHING_MARKERS: list[tuple[str, str]] = [
    (r"<form[^>]*action=[\"'][^\"']*(?<!aria)\.\w{2,}/[^\"']*login", "credential-harvesting form"),
    (
        r"(paypal|bankofamerica|chase|wellsfargo|apple|microsoft)\.com[^a-z]",
        "brand-domain spoofing text",
    ),
    (
        r"verify your (account|identity).{0,40}(click|link)",
        "urgency + credential-verify phishing hook",
    ),
    (
        r"your account (has been|will be) (suspended|locked|closed)",
        "account-suspension phishing hook",
    ),
]


@dataclass
class ModerationResult:
    blocked: bool
    categories: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    layer: str = ""  # "keyword" | "llm" | "none"

    def to_dict(self) -> dict:
        return {
            "blocked": self.blocked,
            "categories": self.categories,
            "confidence": self.confidence,
            "reason": self.reason,
            "layer": self.layer,
        }


@dataclass
class PlanVerdict:
    safe: bool
    risk_score: float
    reason: str

    def to_dict(self) -> dict:
        return {"safe": self.safe, "risk_score": self.risk_score, "reason": self.reason}


@dataclass
class CodeSafetyResult:
    safe: bool
    findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"safe": self.safe, "findings": self.findings}


# ── Layer 1: input moderation ────────────────────────────────────────────
def _keyword_screen(text: str) -> ModerationResult | None:
    # Collapse whitespace runs (spaces, tabs, newlines) to a single space
    # before matching: a multi-word phrase like "write a virus" is trivially
    # defeated by "write   a virus" or "write\na virus" under plain substring
    # matching, with no obfuscation intent required to slip past it.
    lowered = re.sub(r"\s+", " ", text.lower())
    hits: list[str] = []
    for category, phrases in PROHIBITED_CATEGORIES.items():
        for phrase in phrases:
            if phrase in lowered:
                hits.append(category)
                break
    if hits:
        return ModerationResult(
            blocked=True,
            categories=sorted(set(hits)),
            confidence=0.6,  # keyword match alone is a signal, not certainty
            reason=f"Matched prohibited-category phrasing: {', '.join(sorted(set(hits)))}.",
            layer="keyword",
        )
    return None


async def _llm_classify(text: str) -> ModerationResult:
    """Second pass: an LLM judges intent, not just surface phrasing — catches
    paraphrased/obfuscated requests the keyword pass misses, and clears
    keyword false positives (e.g. discussing phishing defensively).

    Fails OPEN, unlike Layer 2's evaluate_plan(). This pass sits in front of
    EVERY message — failing closed here would mean a transient AI-provider
    outage blocks all conversation, not just risky actions, which is a far
    worse outcome than occasionally letting one unmoderated message through
    the keyword screen (which still runs first and always blocks on its own,
    independent of this call). Layer 2 only gates a small set of consequential
    tools, so its fail-closed policy has bounded blast radius and protects
    much higher-stakes actions — the two layers deliberately use opposite
    failure modes for that reason."""
    try:
        from apps.core.tools.ai_client import AIModel, get_ai_client

        ai = get_ai_client()
        taxonomy = ", ".join(sorted(PROHIBITED_CATEGORIES.keys()))
        result = await ai.complete_json(
            system=(
                "You are a strict content-safety classifier for an autonomous AI agent "
                "that can execute code, control a browser, post to social media, and spend "
                "real money. Classify the user's message. Categories: "
                f"{taxonomy}. A request is unsafe if it asks the agent to help commit fraud, "
                "build malware, evade taxes, steal identities, build phishing content, "
                "distribute controlled substances without authorization, infringe copyright "
                "protections, or exploit/sexualize minors. Discussing these topics "
                "defensively (e.g. 'how do I detect phishing emails') is SAFE. "
                'Respond with ONLY this JSON: {"blocked": bool, "categories": [string], '
                '"confidence": 0.0-1.0, "reason": "one sentence"}'
            ),
            user=text[:4000],
            model=AIModel.FAST,
            max_tokens=200,
            agent_name="guardrails_moderation",
        )
        if not result:
            # Fail open (see docstring): no signal either way, and the
            # keyword screen already had first crack at obviously bad input.
            with suppress(Exception):
                await record_audit_event(
                    "moderation_classifier_unavailable",
                    {"reason": "empty response"},
                )
            return ModerationResult(
                blocked=False,
                reason="Safety classifier unavailable — allowed through (keyword screen still applies).",
                layer="llm",
            )
        return ModerationResult(
            blocked=bool(result.get("blocked", False)),
            categories=list(result.get("categories", []) or []),
            confidence=float(result.get("confidence", 0.5)),
            reason=str(result.get("reason", "")),
            layer="llm",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[guardrails] moderation classifier failed: %s", exc)
        with suppress(Exception):
            await record_audit_event("moderation_classifier_unavailable", {"reason": str(exc)})
        return ModerationResult(
            blocked=False,
            reason=f"Safety classifier error ({exc}) — allowed through (keyword screen still applies).",
            layer="llm",
        )


async def moderate_input(text: str, email: str = "") -> ModerationResult:
    """Layer 1 entrypoint. Two passes: cheap keyword screen first (if it
    hits, that alone is enough signal to block without spending an LLM
    call); otherwise an LLM classifies intent."""
    if not text or not text.strip():
        return ModerationResult(blocked=False, layer="none")

    keyword_hit = _keyword_screen(text)
    if keyword_hit is not None:
        with suppress(Exception):
            await record_audit_event(
                "moderation_blocked",
                {"email": email, "layer": "keyword", "categories": keyword_hit.categories},
            )
        return keyword_hit

    verdict = await _llm_classify(text)
    if verdict.blocked:
        with suppress(Exception):
            await record_audit_event(
                "moderation_blocked",
                {"email": email, "layer": "llm", "categories": verdict.categories},
            )
    return verdict


# ── Layer 2: constitutional plan review ──────────────────────────────────
_RISK_BLOCK_THRESHOLD = 0.6


async def evaluate_plan(
    tool: str, tool_args: dict, user_text: str = "", email: str = ""
) -> PlanVerdict:
    """Layer 2 entrypoint. Judges the SPECIFIC tool+args the planner picked
    (not the raw user text — that's Layer 1's job) against a legality/ethics
    rubric. Fails closed: any error, timeout, or malformed response is
    treated as unsafe, never as a silent pass-through."""
    try:
        from apps.core.tools.ai_client import AIModel, get_ai_client

        ai = get_ai_client()
        args_preview = json.dumps(tool_args, default=str)[:800]
        result = await ai.complete_json(
            system=(
                "You are a constitutional safety reviewer for an autonomous AI agent. "
                "You will be shown the EXACT tool call the agent is about to execute — not "
                "a hypothetical, the real next action. Judge it strictly against: (1) is it "
                "legal, (2) is it ethical, (3) could it defraud, deceive, or harm a third "
                "party, (4) does it exceed what a reasonable owner would authorize. "
                "Legitimate business/marketing/coding actions (even aggressive sales copy, "
                "flash sales, or normal code execution) are SAFE. Building phishing pages, "
                "generating malware, evading taxes, impersonating people/brands to deceive, "
                "or laundering money are UNSAFE regardless of how the request is phrased. "
                'Respond with ONLY this JSON: {"safe": bool, "risk_score": 0.0-1.0, '
                '"reason": "one sentence, specific to this tool call"}'
            ),
            user=(
                f"User asked: {user_text[:500]}\n"
                f"Agent chose tool: {tool}\n"
                f"With arguments: {args_preview}\n\n"
                "Evaluate this exact action."
            ),
            model=AIModel.REASONING,
            max_tokens=200,
            agent_name="guardrails_constitutional",
        )
        if not result:
            await record_audit_event(
                "plan_review_failed",
                {"email": email, "tool": tool, "reason": "empty classifier response"},
            )
            return PlanVerdict(
                safe=False,
                risk_score=1.0,
                reason="Constitutional reviewer returned no verdict — failing closed.",
            )
        verdict = PlanVerdict(
            safe=bool(result.get("safe", False)),
            risk_score=float(result.get("risk_score", 1.0)),
            reason=str(result.get("reason", "")),
        )
        if not verdict.safe or verdict.risk_score >= _RISK_BLOCK_THRESHOLD:
            await record_audit_event(
                "plan_review_blocked",
                {
                    "email": email,
                    "tool": tool,
                    "risk_score": verdict.risk_score,
                    "reason": verdict.reason,
                },
            )
            await get_kill_switch().record_and_check_anomaly(email=email, kind="plan_rejected")
        return verdict
    except Exception as exc:  # noqa: BLE001
        logger.warning("[guardrails] constitutional review failed for tool=%s: %s", tool, exc)
        await record_audit_event(
            "plan_review_failed", {"email": email, "tool": tool, "reason": str(exc)}
        )
        return PlanVerdict(
            safe=False, risk_score=1.0, reason=f"Reviewer error ({exc}) — failing closed."
        )


# Tools consequential enough (code execution, browser/OS control, live
# publishing, real money movement) to warrant Layer 2's extra LLM call
# before running — running a constitutional review on every one of ~150
# tools (including plain content generation, already covered by Layer 1's
# input moderation) would add real latency/cost to every benign
# interaction for no safety benefit. Shared between AriaMind.handle() (the
# normal chat path) and WorkflowEngine.run() (multi-step automations) —
# defined here, not as a private AriaMind class attribute, specifically so
# every caller that can execute a tool goes through the same gate rather
# than each needing its own copy that can drift out of sync.
CONSTITUTIONAL_REVIEW_TOOLS = frozenset(
    {
        "execute_code",
        "computer_use",
        "post_to_social",
        "github_write",
        "github_pr",
        "github_issues",
        "record_cashflow_entry",
        "track_roi",
        "update_roi_returns",
        "create_flash_sale",
        "create_product_bundle",
        "shopify_live_analytics",
        # launch_niche/auto_income create a real, immediately-purchasable
        # Gumroad product and publish public content (Medium/dev.to/Hashnode,
        # a Zapier distribution webhook) autonomously — unlike the Shopify
        # revenue-suite tools above, these call a live publish API, not just
        # draft copy. send_email/publish_article are similarly public and
        # unrecallable once sent; they only had content-safety filtering
        # (blocks unsafe *content*), nothing judging whether the action
        # itself should happen at all.
        "launch_niche",
        "auto_income",
        "send_email",
        "publish_article",
    }
)


async def review_tool_call(
    tool: str, tool_args: dict, user_text: str = "", email: str = "", chat_id: str = ""
) -> str | None:
    """Single entrypoint every tool-executing caller should use for Layer 2.
    Returns a decline message if the call should be blocked (either because
    it's an unsafe plan, or GUARDRAILS_ENABLED is off and... no — see below),
    or None if it's clear to proceed.

    Only reviews tools in CONSTITUTIONAL_REVIEW_TOOLS; anything else returns
    None immediately without an LLM call. Respects GUARDRAILS_ENABLED
    (apps.core.config.settings) as the debugging escape hatch it's meant to
    be — when disabled, this always returns None (no review happens at all,
    matching every other layer's behavior under the same flag).

    An unsafe verdict here is a judgment call (is this amount/vendor/scale
    authorized?), not one of Layer 1's categorical prohibitions — so instead
    of declining permanently, it's queued for the owner via Mission Control's
    HITL hub, who can approve (runs for real), deny (stays blocked), or
    approve with modified args. chat_id is optional because WorkflowEngine.run()
    (the other caller) has no conversation to follow up in — the "I'll let you
    know here" line is only appended when there is one."""
    if tool not in CONSTITUTIONAL_REVIEW_TOOLS:
        return None
    try:
        from apps.core.config import settings

        if not getattr(settings, "GUARDRAILS_ENABLED", True):
            return None
    except Exception:  # noqa: BLE001
        pass

    verdict = await evaluate_plan(tool, tool_args, user_text, email=email)
    if not verdict.safe:
        from apps.core.safety.hitl_queue import get_hitl_queue

        hitl_req = await get_hitl_queue().enqueue(
            chat_id=chat_id,
            email=email,
            user_text=user_text,
            tool=tool,
            tool_args=tool_args,
            risk_score=verdict.risk_score,
            risk_reason=verdict.reason,
        )
        pending = (
            f"That needs my owner's approval before I can do it "
            f"(safety review: {verdict.reason or 'flagged for review'}). "
            f"I've queued it for a decision — request `{hitl_req.request_id}`."
        )
        if chat_id:
            pending += " I'll let you know here once it's been reviewed."
        return pending
    return None


# ── Layer 3: deterministic firewall ──────────────────────────────────────
def check_code_safety(code: str) -> CodeSafetyResult:
    """Regex + (if installed) `bandit` static analysis. Deterministic on
    purpose — this is the layer that can't be reasoned around, unlike the
    two LLM layers above."""
    findings: list[str] = []
    for pattern, description in _DANGEROUS_CODE_PATTERNS:
        if re.search(pattern, code, re.IGNORECASE):
            findings.append(description)

    with suppress(Exception):
        import subprocess  # noqa: S404
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=True) as f:
            f.write(code)
            f.flush()
            proc = subprocess.run(  # noqa: S603
                ["bandit", "-q", "-f", "json", f.name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.stdout:
                report = json.loads(proc.stdout)
                for issue in report.get("results", []):
                    severity = issue.get("issue_severity", "")
                    if severity in ("HIGH", "MEDIUM"):
                        findings.append(
                            f"bandit[{severity.lower()}]: {issue.get('issue_text', '')}"
                        )

    return CodeSafetyResult(safe=not findings, findings=findings)


def check_content_safety(content: str) -> CodeSafetyResult:
    """Phishing/credential-harvesting pattern check for content the agent
    is about to publish (a landing page, an HTML email, a social post)."""
    findings: list[str] = []
    for pattern, description in _PHISHING_MARKERS:
        if re.search(pattern, content, re.IGNORECASE):
            findings.append(description)
    return CodeSafetyResult(safe=not findings, findings=findings)


# ── Layer 4: kill switch + anomaly watch ─────────────────────────────────
_KILL_SWITCH_TTL = 30 * 24 * 3600  # 30 days — an emergency freeze should require
# explicit release, not silently expire, but a hard cap avoids an orphaned
# flag surviving forever if release() is never called.
_ANOMALY_WINDOW_SECONDS = 300
_ANOMALY_TRIGGER_COUNT = 4


class KillSwitch:
    """Redis-persisted emergency freeze — global or per-user — using the
    same storage pattern as CostLedger's frozen-user flag (apps/core/ops/
    cost_ledger.py) so it survives a restart or a request landing on a
    different instance. A local in-process set covers the same-process
    fast path; Redis is checked (and warms the local set) otherwise."""

    def __init__(self) -> None:
        self._local: set[str] = set()
        self._local_anomalies: dict[str, list[float]] = {}

    @staticmethod
    def _key(scope: str) -> str:
        return f"aria:safety:killswitch:{scope}"

    async def trigger(self, reason: str, scope: str = "global", email: str = "") -> None:
        target = email if scope == "user" else "global"
        self._local.add(target)
        logger.error(
            "[guardrails] KILL SWITCH triggered (scope=%s, target=%s): %s", scope, target, reason
        )
        with suppress(Exception):
            from apps.core.memory.redis_client import get_cache

            await get_cache().set(self._key(target), reason, ttl_seconds=_KILL_SWITCH_TTL)
        with suppress(Exception):
            await record_audit_event(
                "kill_switch_triggered", {"scope": scope, "target": target, "reason": reason}
            )
        # A global trigger also freezes the owner's own account via CostLedger,
        # so a compromised/anomalous session can't keep burning budget even if
        # some other check is bypassed — belt and suspenders, not a duplicate
        # of the owner-exemption logic (that exemption is for the NORMAL burn
        # cap; this is an emergency override of it).
        if scope == "global":
            with suppress(Exception):
                from apps.core.ops.cost_ledger import get_ledger

                for e in list(self._local_anomalies.keys()):
                    await get_ledger().freeze(e)

    async def release(self, scope: str = "global", email: str = "") -> None:
        target = email if scope == "user" else "global"
        self._local.discard(target)
        with suppress(Exception):
            from apps.core.memory.redis_client import get_cache

            await get_cache().delete(self._key(target))
        logger.warning("[guardrails] kill switch released (scope=%s, target=%s)", scope, target)

    async def is_active(self, email: str = "") -> bool:
        if "global" in self._local:
            return True
        target = email or ""
        if target and target in self._local:
            return True
        with suppress(Exception):
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            if await cache.get(self._key("global")):
                self._local.add("global")
                return True
            if target and await cache.get(self._key(target)):
                self._local.add(target)
                return True
        return False

    async def record_and_check_anomaly(self, email: str, kind: str) -> bool:
        """Rolling-window anomaly counter. If the same account trips
        several Layer 2/3 rejections in a short window, that's a stronger
        signal than any single rejection — auto-trip the per-user kill
        switch rather than waiting for a human to notice the pattern."""
        now = time.time()
        key = email or "anonymous"
        window = self._local_anomalies.setdefault(key, [])
        window.append(now)
        cutoff = now - _ANOMALY_WINDOW_SECONDS
        self._local_anomalies[key] = [t for t in window if t >= cutoff]
        if len(self._local_anomalies[key]) >= _ANOMALY_TRIGGER_COUNT:
            await self.trigger(
                f"{len(self._local_anomalies[key])} safety rejections ({kind}) within "
                f"{_ANOMALY_WINDOW_SECONDS}s",
                scope="user",
                email=email,
            )
            return True
        return False


_kill_switch: KillSwitch | None = None


def get_kill_switch() -> KillSwitch:
    global _kill_switch
    if _kill_switch is None:
        _kill_switch = KillSwitch()
    return _kill_switch


# ── Audit trail ───────────────────────────────────────────────────────────
async def record_audit_event(event_type: str, data: dict) -> None:
    """Best-effort broadcast to the same admin_activity channel the rest of
    Aria's real-time observability uses (apps/core/scale/log_bus.py, wired
    into the admin console's live activity feed) — a guardrail block is
    exactly the kind of thing the owner wants to see in real time."""
    with suppress(Exception):
        from apps.core.scale import log_bus

        await log_bus.publish(
            "admin_activity",
            json.dumps(
                {"ts": time.time(), "task_type": f"guardrail:{event_type}", **data}, default=str
            ),
            level="warning",
        )
