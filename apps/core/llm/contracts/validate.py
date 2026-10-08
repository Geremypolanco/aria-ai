"""
validate_or_retry — anti-hallucination enforcement with controlled degradation.

Every structured LLM output goes through this gate before it can reach a
report, a listing, or a price::

    1. Call ``fn()`` to obtain a candidate result.
    2. Validate it against the pydantic schema.
    3. If it fails, wait (exponential backoff) and retry the call —
       up to 3 attempts total.
    4. If it still fails, return a ``DeadLetterEntry``. The output is
       quarantined, NEVER invented, padded, or silently coerced.

Mirrors ``validate.ts`` from ``@polanco/llm-contracts``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from apps.core.llm.contracts.dead_letter import DeadLetterEntry

logger = logging.getLogger("aria.llm_contracts")


@dataclass
class ValidateResult:
    """Outcome of :func:`validate_or_retry`."""

    ok: bool
    data: Any = None
    dead_letter: DeadLetterEntry | None = None


def _validate_against(schema: type[BaseModel] | Callable[[Any], Any], candidate: Any) -> Any:
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_validate(candidate)
    if callable(schema):
        return schema(candidate)
    raise TypeError(f"schema must be a pydantic BaseModel subclass or callable, got {schema!r}")


def _describe_errors(exc: ValidationError) -> list[str]:
    out: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "(root)"
        out.append(f"{loc}: {err.get('msg', 'invalid')}")
    return out


async def validate_or_retry(
    fn: Callable[[], Awaitable[Any]],
    schema: type[BaseModel] | Callable[[Any], Any],
    *,
    max_attempts: int = 3,
    base_delay_s: float = 0.1,
    schema_name: str = "unknown",
    agent_name: str = "",
) -> ValidateResult:
    """Run ``fn()``, validate against ``schema``, retry with exponential
    backoff, and degrade to a dead-letter entry after ``max_attempts``.

    NEVER invents data to fill a failing schema.
    """
    attempts_total = max(1, int(max_attempts))
    base_delay_s = max(0.0, float(base_delay_s))
    last_errors: list[str] = ["no attempts were made"]
    attempts = 0

    for attempt in range(1, attempts_total + 1):
        attempts = attempt
        try:
            candidate = await fn()
        except Exception as exc:  # noqa: BLE001 — a throwing fn is a failed attempt, not fatal
            last_errors = [f"fn() raised: {exc}"]
        else:
            try:
                data = _validate_against(schema, candidate)
            except ValidationError as exc:
                last_errors = _describe_errors(exc)
            except Exception as exc:  # noqa: BLE001 — custom callable validators may raise anything
                last_errors = [f"validator raised: {exc}"]
            else:
                return ValidateResult(ok=True, data=data)

        if attempt < attempts_total and base_delay_s > 0:
            await asyncio.sleep(base_delay_s * (2 ** (attempt - 1)))

    logger.warning(
        "[validate] schema=%s failed after %d attempts: %s",
        schema_name,
        attempts,
        "; ".join(last_errors[:3]),
    )
    return ValidateResult(
        ok=False,
        dead_letter=DeadLetterEntry(
            schema=schema_name,
            errors=last_errors,
            attempts=attempts,
            agent=agent_name,
        ),
    )
