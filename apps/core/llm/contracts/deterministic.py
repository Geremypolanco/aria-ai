"""
U3 — "LLM on the edges, math in the core."

Deterministic numeric guards for values that originate from an LLM (or any
untrusted source) and reach money, reports, or users. These functions are
pure and total: they NEVER raise on bad input — they fall back to a safe
default and log the adjustment. No LLM call happens in this module, ever.

Rule: a price the LLM proposes is a *suggestion*; the price that is
charged/published is computed here.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

logger = logging.getLogger("aria.llm_contracts")


def _coerce_decimal(value: object) -> Decimal | None:
    """Best-effort coercion to Decimal. Returns None for anything that is
    not a finite number (None, bools, NaN/inf, non-numeric strings)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, Decimal):
            number = value
        elif isinstance(value, float):
            number = Decimal(str(value))
        elif isinstance(value, int):
            number = Decimal(value)
        elif isinstance(value, str):
            text = value.strip().replace("$", "").replace(",", "")
            if not text:
                return None
            number = Decimal(text)
        else:
            return None
    except (InvalidOperation, ValueError, ArithmeticError):
        return None
    if not number.is_finite():
        return None
    return number


def safe_price_cents(
    value: object,
    *,
    default_cents: int,
    min_cents: int,
    max_cents: int,
) -> int:
    """Coerce an LLM/user-supplied price (in cents) into a safe int within
    ``[min_cents, max_cents]``. Never raises: unparseable input falls back
    to ``default_cents``; out-of-range input is clamped. Adjustments are
    logged so they stay visible.
    """
    number = _coerce_decimal(value)
    if number is None:
        logger.warning(
            "[deterministic] price_cents %r unparseable — using default %d",
            value,
            default_cents,
        )
        return default_cents
    cents = int(number.to_integral_value(rounding=ROUND_HALF_UP))
    if cents < min_cents or cents > max_cents:
        clamped = min(max(cents, min_cents), max_cents)
        logger.warning(
            "[deterministic] price_cents %d out of bounds [%d, %d] — clamped to %d",
            cents,
            min_cents,
            max_cents,
            clamped,
        )
        return clamped
    return cents


def usd_to_cents(
    value_usd: object,
    *,
    default_cents: int,
    min_usd: float,
    max_usd: float,
) -> int:
    """Coerce an LLM/user-supplied price in dollars to int cents, clamped to
    ``[min_usd, max_usd]`` dollars. Never raises. Rounds half-up to the cent.
    """
    number = _coerce_decimal(value_usd)
    if number is None:
        logger.warning(
            "[deterministic] price_usd %r unparseable — using default %d cents",
            value_usd,
            default_cents,
        )
        return default_cents
    if number < Decimal(str(min_usd)) or number > Decimal(str(max_usd)):
        clamped = min(max(number, Decimal(str(min_usd))), Decimal(str(max_usd)))
        logger.warning(
            "[deterministic] price_usd %s out of bounds [%s, %s] — clamped to %s",
            number,
            min_usd,
            max_usd,
            clamped,
        )
        number = clamped
    return int((number * 100).to_integral_value(rounding=ROUND_HALF_UP))
