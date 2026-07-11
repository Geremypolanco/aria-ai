"""
self_healing.py — Self-Healing Workers & Auto-Retry.

Wraps a background mission (e.g. publishing to Instagram / YouTube / LinkedIn)
so that **transient** failures — network blips, temporary OAuth-token expiry,
third-party API timeouts / 5xx / rate limits — do NOT abort the task. Instead
the task is paused and retried with an exponential backoff schedule
(5, 15, 30 minutes) up to 3 attempts, before the user is alerted.

Permanent errors (bad request, auth revoked, validation) are NOT retried — they
fail fast and alert immediately.

`sleep` is injectable so the backoff is instant in tests.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("aria.self_healing")

# Backoff schedule in seconds: 5 min, 15 min, 30 min (max 3 retries).
RETRY_DELAYS: tuple[int, ...] = (5 * 60, 15 * 60, 30 * 60)
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1  # initial try + 3 retries

# Substrings that mark a transient/retryable failure.
_RETRYABLE_MARKERS = (
    "timeout",
    "timed out",
    "temporarily",
    "temporary",
    "connection",
    "connect",
    "reset by peer",
    "network",
    "unreachable",
    "econn",
    "429",
    "rate limit",
    "rate-limit",
    "too many requests",
    "500",
    "502",
    "503",
    "504",
    "server error",
    "bad gateway",
    "service unavailable",
    "token expired",
    "expired token",
    "token has expired",
    "invalid_grant",  # transient OAuth refresh hiccup
)

# Exception *type names* that are retryable regardless of message.
_RETRYABLE_TYPES = (
    "TimeoutError",
    "ConnectTimeout",
    "ReadTimeout",
    "ConnectError",
    "ConnectionError",
    "ClientConnectorError",
    "ServerDisconnectedError",
    "ClientOSError",
    "ReadError",
)


def is_retryable(exc: BaseException) -> bool:
    """Classify an exception as transient (retryable) vs permanent."""
    if type(exc).__name__ in _RETRYABLE_TYPES:
        return True
    msg = str(exc).lower()
    return any(m in msg for m in _RETRYABLE_MARKERS)


@dataclass
class RetryOutcome:
    ok: bool
    attempts: int
    result: Any = None
    error: str | None = None
    delays_used: list[int] = field(default_factory=list)
    retryable: bool = True


async def run_with_self_healing(
    task: Callable[[], Awaitable[Any]],
    *,
    name: str = "mission",
    on_alert: Callable[[RetryOutcome], Awaitable[None]] | None = None,
    delays: tuple[int, ...] = RETRY_DELAYS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> RetryOutcome:
    """Run `task`, retrying transient failures with the backoff schedule.

    Returns a RetryOutcome. On final failure (permanent error, or all retries
    exhausted) calls `on_alert` once, if provided.
    """
    delays_used: list[int] = []
    last_error: str | None = None
    retryable = True

    for attempt in range(1, len(delays) + 2):  # initial + len(delays) retries
        try:
            result = await task()
            if attempt > 1:
                logger.info("[heal:%s] recovered on attempt %d", name, attempt)
            return RetryOutcome(ok=True, attempts=attempt, result=result, delays_used=delays_used)
        except Exception as exc:  # noqa: BLE001 — we classify below
            last_error = f"{type(exc).__name__}: {exc}"
            retryable = is_retryable(exc)
            if not retryable:
                logger.warning("[heal:%s] permanent error, no retry: %s", name, last_error)
                break
            if attempt <= len(delays):
                delay = delays[attempt - 1]
                delays_used.append(delay)
                logger.info(
                    "[heal:%s] transient error (attempt %d/%d): %s — retrying in %ds",
                    name,
                    attempt,
                    len(delays) + 1,
                    last_error,
                    delay,
                )
                await sleep(delay)
            else:
                logger.warning("[heal:%s] retries exhausted: %s", name, last_error)

    outcome = RetryOutcome(
        ok=False,
        attempts=len(delays_used) + 1,
        error=last_error,
        delays_used=delays_used,
        retryable=retryable,
    )
    if on_alert is not None:
        try:
            await on_alert(outcome)
        except Exception as exc:  # noqa: BLE001
            logger.error("[heal:%s] alert callback failed: %s", name, exc)
    return outcome
