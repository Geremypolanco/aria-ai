"""
Founding-member launch offer — a *real*, capped discount for the first customers.

30% off for life for the first 25 paying customers, delivered as a Stripe coupon
(``duration=forever``) exposed through a promotion code (``FOUNDER30``). The cap is
enforced by Stripe (``max_redemptions=25``), so the scarcity is genuine: once 25
customers redeem it, Stripe stops accepting the code and the offer is truly over —
no fake "only 3 left!" theatrics.

Checkout already sets ``allow_promotion_codes=True``, so a customer just enters
``FOUNDER30`` at Stripe checkout. This module only has to make sure the coupon and
code exist, and describe the offer for the UI.

Everything here fails safe: any Stripe error leaves checkout working normally
(just without the discount) rather than breaking a purchase.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("aria.founding")

ACTIVE = True
CODE = "FOUNDER30"
PERCENT_OFF = 30
CAP = 25
_COUPON_ID = "aria_founder_30_forever"

# Cache the "is the promo live" result so we hit Stripe at most once per process
# until it succeeds. None = not yet checked.
_ensured: bool | None = None


def public_offer() -> dict | None:
    """A UI-safe description of the offer, or None when it's off."""
    if not ACTIVE:
        return None
    return {
        "code": CODE,
        "percent_off": PERCENT_OFF,
        "cap": CAP,
        "headline": f"Founding member: {PERCENT_OFF}% off for life",
        "detail": (
            f"The first {CAP} customers lock in {PERCENT_OFF}% off, forever. "
            f"Enter code {CODE} at checkout."
        ),
        "duration": "forever",
    }


async def ensure_promo(stripe_key: str | None) -> bool:
    """Idempotently create the coupon + promotion code in Stripe. Returns True if
    the promo is available. Fail-open: returns False (no discount) on any problem,
    never raises, never blocks checkout."""
    global _ensured
    if not ACTIVE or not stripe_key:
        return False
    if _ensured is True:
        return True
    try:
        import stripe

        stripe.api_key = stripe_key

        # 1) Coupon (idempotent by fixed id).
        try:
            stripe.Coupon.retrieve(_COUPON_ID)
        except Exception:
            stripe.Coupon.create(
                id=_COUPON_ID,
                percent_off=PERCENT_OFF,
                duration="forever",
                max_redemptions=CAP,
                name=f"Founding member — {PERCENT_OFF}% off for life",
            )

        # 2) Promotion code (customer-facing). Reuse if it already exists.
        existing = stripe.PromotionCode.list(code=CODE, limit=1).data
        if not existing:
            stripe.PromotionCode.create(coupon=_COUPON_ID, code=CODE)

        _ensured = True
        return True
    except Exception as e:  # noqa: BLE001 — never let billing break on the promo
        logger.warning("founding promo ensure failed (checkout unaffected): %s", e)
        return False
