"""
cost_ledger.py — AI Burn-Rate Cap.

Tracks the real USD cost of every LLM API call per user, per calendar month,
and enforces a **hard throttle**: when a paid user (Pro / Business) consumes
more than a configured fraction (default 70%) of the API-cost budget baked into
their plan margin, their missions are frozen until they upgrade or the month
resets.

Design notes:
- Monthly cost accumulation (`record`/`month_cost`) is process-local (a dict),
  deterministic and unit-testable. It does NOT persist across restarts or
  aggregate across instances (fly.toml runs separate web/worker processes) —
  that needs an atomic distributed counter, a bigger design decision than a
  freeze flag, and is intentionally left as a known limitation for now.
- The freeze decision (`freeze`/`unfreeze`/`is_frozen`/`evaluate`) — the part
  that actually enforces the cap — IS persisted to the shared cache
  (Redis/Upstash), best-effort, so a throttled user stays throttled across a
  restart or a request landing on a different instance.
- Pricing is a static table of USD per 1M tokens. Providers without per-token
  billing to us (HuggingFace free tier, Groq) are treated as ~$0.
- NOTHING here fabricates figures: if no usage was recorded, cost is $0.00.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

logger = logging.getLogger("aria.cost_ledger")

# USD per 1M tokens (input, output). Approximate list prices; adjust as needed.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    # OpenAI (common)
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    # Providers we consume via free / flat tiers → ~0 marginal cost to us
    "_free": (0.0, 0.0),
}

# Monthly API-cost budget (USD) baked into each plan's margin. Throttling kicks
# in at THROTTLE_FRACTION of this. Tune to protect real margin.
PLAN_API_BUDGET_USD: dict[str, float] = {
    "free": 0.50,
    "pro": 8.00,  # of the $29 price
    "business": 28.00,  # of the $99 price
}
THROTTLE_FRACTION = 0.70


def estimate_cost(model: str | None, input_tokens: int, output_tokens: int) -> float:
    """USD cost for a single call. Unknown/free providers → $0."""
    key = (model or "").strip()
    price_in, price_out = MODEL_PRICING.get(key, MODEL_PRICING["_free"])
    return round((input_tokens / 1e6) * price_in + (output_tokens / 1e6) * price_out, 6)


def _month_key(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return now.strftime("%Y%m")


class CostLedger:
    """Per-(month, user) USD accumulator with a hard-throttle decision."""

    def __init__(self) -> None:
        self._cost: dict[tuple[str, str], float] = {}  # (month, email) -> usd
        self._frozen: set[str] = set()  # emails frozen this month

    # ── recording ────────────────────────────────────────────────
    def record(
        self,
        email: str,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
        *,
        now: datetime | None = None,
    ) -> float:
        """Record a call's cost for the user and return the USD amount."""
        cost = estimate_cost(model, input_tokens, output_tokens)
        if email:
            key = (_month_key(now), email.strip().lower())
            self._cost[key] = round(self._cost.get(key, 0.0) + cost, 6)
        return cost

    def month_cost(self, email: str, *, now: datetime | None = None) -> float:
        return self._cost.get((_month_key(now), (email or "").strip().lower()), 0.0)

    # ── throttle decision ────────────────────────────────────────
    def budget(self, plan: str) -> float:
        return PLAN_API_BUDGET_USD.get((plan or "free").lower(), PLAN_API_BUDGET_USD["free"])

    def usage_fraction(self, email: str, plan: str, *, now: datetime | None = None) -> float:
        budget = self.budget(plan)
        if budget <= 0:
            return 0.0
        return round(self.month_cost(email, now=now) / budget, 4)

    def over_threshold(self, email: str, plan: str, *, now: datetime | None = None) -> bool:
        """True when the user has burned >= THROTTLE_FRACTION of their budget."""
        return self.usage_fraction(email, plan, now=now) >= THROTTLE_FRACTION

    # ── freeze state (persisted — this is the actual enforcement) ──
    @staticmethod
    def _frozen_key(email: str, now: datetime | None = None) -> str:
        return f"aria:frozen:{_month_key(now)}:{email}"

    async def freeze(self, email: str, *, now: datetime | None = None) -> None:
        if not email:
            return
        email = email.strip().lower()
        self._frozen.add(email)
        try:
            from apps.core.memory.redis_client import get_cache

            await get_cache().set(self._frozen_key(email, now), "1", ttl_seconds=32 * 24 * 3600)
        except Exception as exc:  # noqa: BLE001 — enforcement still holds locally
            logger.debug("[cost] freeze persist failed for %s: %s", email, exc)

    async def unfreeze(self, email: str, *, now: datetime | None = None) -> None:
        email = (email or "").strip().lower()
        self._frozen.discard(email)
        try:
            from apps.core.memory.redis_client import get_cache

            await get_cache().delete(self._frozen_key(email, now))
        except Exception as exc:  # noqa: BLE001
            logger.debug("[cost] unfreeze persist failed for %s: %s", email, exc)

    async def is_frozen(self, email: str, *, now: datetime | None = None) -> bool:
        email = (email or "").strip().lower()
        if email in self._frozen:
            return True
        # Not seen by this process — check the shared store (covers a restart
        # or a request landing on a different instance/worker).
        try:
            from apps.core.memory.redis_client import get_cache

            if await get_cache().get(self._frozen_key(email, now)):
                self._frozen.add(email)  # warm the local cache
                return True
        except Exception as exc:  # noqa: BLE001 — fail open on cache errors
            logger.debug("[cost] is_frozen cache check failed for %s: %s", email, exc)
        return False

    def frozen_users(self) -> list[str]:
        """Users frozen *on this process* — informational (admin console),
        not authoritative across instances the way is_frozen() is."""
        return sorted(self._frozen)

    async def evaluate(self, email: str, plan: str, *, now: datetime | None = None) -> bool:
        """Freeze the user if they're a paid plan over the threshold. Returns
        True if the user is (now) frozen."""
        if (plan or "").lower() in ("pro", "business") and self.over_threshold(
            email, plan, now=now
        ):
            await self.freeze(email, now=now)
        return await self.is_frozen(email, now=now)


# ── singleton ─────────────────────────────────────────────────────
_ledger: CostLedger | None = None


def get_ledger() -> CostLedger:
    global _ledger
    if _ledger is None:
        _ledger = CostLedger()
    return _ledger


async def notify_burn_cap(email: str, plan: str, fraction: float) -> None:
    """Best-effort upgrade email when a user is throttled. Falls back to a log
    if no email transport is configured — never fabricates a 'sent' status."""
    subject = "You've hit your ARIA usage cap for this month"
    body = (
        f"Hi,\n\nYou've used {int(fraction * 100)}% of your {plan.title()} plan's "
        "monthly AI capacity, so ARIA has paused new missions to protect your account. "
        "Upgrade for more capacity, or your allowance resets at the start of next month.\n\n— ARIA"
    )
    try:
        from apps.core.integrations.gmail_engine import send_email  # type: ignore

        await send_email(to=email, subject=subject, body=body)
        logger.info("[cost] burn-cap email sent to %s", email)
    except Exception as exc:  # noqa: BLE001 — no transport / not configured
        logger.warning("[cost] burn-cap email not sent (%s); logged only for %s", exc, email)
