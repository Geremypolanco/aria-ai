"""
Abandoned cart recovery system — registers abandoned carts and generates
multi-step email + SMS recovery sequences with progressive discounts.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_REDIS_KEY = "shopify:cart_recovery:v1"
_REDIS_TTL = 86400 * 30  # 30 days

# Delays (hours) and discounts for each recovery step
_RECOVERY_STEPS = [
    {"delay_hours": 1, "discount_pct": 0.0, "step": 1},
    {"delay_hours": 24, "discount_pct": 0.05, "step": 2},
    {"delay_hours": 72, "discount_pct": 0.10, "step": 3},
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class AbandonedCart:
    cart_id: str
    user_id: str
    email: str
    cart_items: list[dict]
    cart_value: float
    abandoned_at: float
    recovery_attempts: int = 0
    status: str = "abandoned"  # "abandoned" | "recovering" | "recovered" | "expired"
    last_attempt_ts: float = 0.0
    discount_offered: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "cart_id": self.cart_id,
            "user_id": self.user_id,
            "email": self.email,
            "cart_items": self.cart_items,
            "cart_value": self.cart_value,
            "abandoned_at": self.abandoned_at,
            "recovery_attempts": self.recovery_attempts,
            "status": self.status,
            "last_attempt_ts": self.last_attempt_ts,
            "discount_offered": self.discount_offered,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AbandonedCart:
        return cls(**d)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class CartRecoveryEngine:
    """Manages abandoned cart registration and AI-powered recovery sequences."""

    def __init__(self) -> None:
        self._carts: list[dict] = []
        self._loaded = False

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            from apps.core.memory.redis_client import get_cache  # type: ignore

            cache = get_cache()
            data = await cache.get(_REDIS_KEY)
            if data and isinstance(data, list):
                self._carts = data
        except Exception:
            logger.exception("CartRecoveryEngine._load failed")
        self._loaded = True

    async def _save(self) -> None:
        try:
            from apps.core.memory.redis_client import get_cache  # type: ignore

            cache = get_cache()
            await cache.set(_REDIS_KEY, self._carts, ttl_seconds=_REDIS_TTL)
        except Exception:
            logger.exception("CartRecoveryEngine._save failed")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register_abandoned_cart(
        self,
        user_id: str,
        email: str,
        items: list[dict],
        cart_value: float,
    ) -> AbandonedCart:
        """Register a newly abandoned cart."""
        await self._load()

        now = time.time()
        cart = AbandonedCart(
            cart_id=str(uuid.uuid4()),
            user_id=user_id,
            email=email,
            cart_items=list(items),
            cart_value=cart_value,
            abandoned_at=now,
            created_at=now,
        )
        self._carts.append(cart.to_dict())
        await self._save()
        return cart

    # ------------------------------------------------------------------
    # Recovery sequences
    # ------------------------------------------------------------------

    async def generate_recovery_sequence(self, cart: AbandonedCart) -> list[dict]:
        """
        Return a 3-email recovery sequence with progressive discounts.
        Uses AI for subject/body; falls back to templates.
        """
        item_names = [i.get("title", "item") for i in cart.cart_items[:3]]
        items_str = ", ".join(item_names) if item_names else "your items"
        value_str = f"${cart.cart_value:.2f}"

        emails: list[dict] = []

        templates = [
            {
                "step": 1,
                "delay_hours": 1,
                "discount_pct": 0.0,
                "subject_template": f"You left something behind — {items_str}",
                "body_template": (
                    f"Hi there,\n\nWe noticed you left {items_str} in your cart. "
                    f"Your cart totals {value_str} and is waiting for you.\n\n"
                    "Complete your purchase now before your items sell out!\n\n"
                    "[Complete Purchase]"
                ),
            },
            {
                "step": 2,
                "delay_hours": 24,
                "discount_pct": 0.05,
                "subject_template": "Still thinking about it? Here's 5% off",
                "body_template": (
                    f"Hi there,\n\nYour cart with {items_str} is still waiting. "
                    "As a thank you for your interest, we're offering you 5% off your order.\n\n"
                    "Use code COMEBACK5 at checkout.\n\n[Claim Your 5% Discount]"
                ),
            },
            {
                "step": 3,
                "delay_hours": 72,
                "discount_pct": 0.10,
                "subject_template": "Last chance — 10% off your cart",
                "body_template": (
                    f"Hi there,\n\nThis is your last chance to grab {items_str} at a discount. "
                    "We're offering 10% off — but this offer expires in 24 hours.\n\n"
                    "Use code LASTCHANCE10 at checkout.\n\n[Claim Your 10% Discount]"
                ),
            },
        ]

        for tmpl in templates:
            subject = tmpl["subject_template"]
            body = tmpl["body_template"]

            try:
                from apps.core.tools.ai_client import AIModel, get_ai_client  # type: ignore

                ai = get_ai_client()
                if ai is not None:
                    discount_note = (
                        f" Offer a {int(tmpl['discount_pct'] * 100)}% discount."
                        if tmpl["discount_pct"] > 0
                        else " No discount — just a reminder."
                    )
                    system = (
                        "You are an e-commerce email specialist. "
                        "Write a short, friendly cart recovery email. "
                        "Respond in this exact format:\n"
                        "SUBJECT: <subject line>\nBODY: <email body>"
                    )
                    user = (
                        f"Cart recovery email #{tmpl['step']}. "
                        f"Customer left: {items_str} (total: {value_str}). "
                        f"This email is sent {tmpl['delay_hours']}h after abandonment.{discount_note}"
                    )
                    resp = await ai.complete(system, user, AIModel.CREATIVE, 250)
                    if resp and resp.success and resp.content:
                        lines = resp.content.strip().splitlines()
                        ai_subject = None
                        body_started = False
                        body_parts: list[str] = []
                        for line in lines:
                            if line.startswith("SUBJECT:") and not ai_subject:
                                ai_subject = line[8:].strip()
                            elif line.startswith("BODY:"):
                                body_started = True
                                rest = line[5:].strip()
                                if rest:
                                    body_parts.append(rest)
                            elif body_started:
                                body_parts.append(line)
                        if ai_subject:
                            subject = ai_subject
                        if body_parts:
                            body = "\n".join(body_parts)
            except Exception:
                logger.debug("AI email generation failed for step %s", tmpl["step"])

            emails.append(
                {
                    "subject": subject,
                    "body": body,
                    "delay_hours": tmpl["delay_hours"],
                    "discount_pct": tmpl["discount_pct"],
                }
            )

        return emails

    async def generate_sms_recovery(self, cart: AbandonedCart) -> str:
        """Generate an SMS recovery message under 160 characters."""
        item_names = [i.get("title", "item") for i in cart.cart_items[:2]]
        items_str = ", ".join(item_names) if item_names else "your items"
        value_str = f"${cart.cart_value:.2f}"

        fallback = f"You left {items_str} in your cart ({value_str}). Complete your order: [link]"
        # Ensure fallback is within 160 chars
        if len(fallback) > 160:
            fallback = f"Your cart ({value_str}) is waiting! Complete your order now: [link]"

        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client  # type: ignore

            ai = get_ai_client()
            if ai is not None:
                system = (
                    "Write an SMS cart recovery message. "
                    "It MUST be under 160 characters. Be concise and friendly."
                )
                user = (
                    f"Cart: {items_str}, value: {value_str}. "
                    "Include a short call-to-action and [link] placeholder. Under 160 chars."
                )
                resp = await ai.complete(system, user, AIModel.FAST, 80)
                if resp and resp.success and resp.content:
                    msg = resp.content.strip()
                    if len(msg) <= 160:
                        return msg
                    # Truncate if AI went over
                    return msg[:157] + "..."
        except Exception:
            logger.debug("AI SMS generation failed")

        return fallback

    # ------------------------------------------------------------------
    # Recovery scheduling
    # ------------------------------------------------------------------

    def due_recovery_carts(self) -> list[dict]:
        """Return carts that need a follow-up based on time since last attempt."""
        now = time.time()
        due: list[dict] = []

        for cart in self._carts:
            if cart.get("status") not in {"abandoned", "recovering"}:
                continue
            attempts = cart.get("recovery_attempts", 0)
            if attempts >= 3:
                continue

            cart.get("last_attempt_ts", 0.0)
            abandoned_at = cart.get("abandoned_at", now)

            if attempts == 0:
                # First email: 1h after abandonment
                threshold = abandoned_at + 3600
            elif attempts == 1:
                # Second email: 24h after abandonment
                threshold = abandoned_at + 86400
            else:
                # Third email: 72h after abandonment
                threshold = abandoned_at + 72 * 3600

            if now >= threshold:
                due.append(cart)

        return due

    async def mark_recovered(self, cart_id: str, revenue: float) -> bool:
        """Mark a cart as recovered after a successful purchase."""
        await self._load()
        for cart in self._carts:
            if cart["cart_id"] == cart_id:
                cart["status"] = "recovered"
                cart["cart_value"] = revenue
                await self._save()
                return True
        return False

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def recovery_stats(self) -> dict:
        total = len(self._carts)
        recovered = [c for c in self._carts if c.get("status") == "recovered"]
        recovery_rate = len(recovered) / max(total, 1)
        revenue_recovered = sum(c.get("cart_value", 0.0) for c in recovered)
        avg_cart_value = sum(c.get("cart_value", 0.0) for c in self._carts) / max(total, 1)
        return {
            "total_abandoned": total,
            "recovered": len(recovered),
            "recovery_rate": round(recovery_rate, 3),
            "revenue_recovered": round(revenue_recovered, 2),
            "avg_cart_value": round(avg_cart_value, 2),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine: CartRecoveryEngine | None = None


def get_cart_recovery_engine() -> CartRecoveryEngine:
    global _engine
    if _engine is None:
        _engine = CartRecoveryEngine()
    return _engine
