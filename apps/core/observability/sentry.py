"""
Sentry integration with ARIA-specific enrichment.

Configures Sentry for:
  - FastAPI request tracking
  - Performance monitoring (transactions)
  - Custom tags: environment, component, fly region
  - Before-send filter: drops noisy/non-actionable errors
  - User context from session IDs
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("aria.sentry")

_initialized = False


def setup_sentry(
    dsn: str | None = None,
    traces_sample_rate: float = 0.1,
    profiles_sample_rate: float = 0.05,
) -> None:
    """
    Initialize Sentry SDK with ARIA-specific configuration.

    Call once at application startup. Subsequent calls are no-ops.

    Args:
        dsn: Sentry DSN. Falls back to SENTRY_DSN env var.
        traces_sample_rate: % of transactions sampled for performance (0.0–1.0).
        profiles_sample_rate: % of traced transactions profiled.
    """
    global _initialized
    if _initialized:
        return

    resolved_dsn = dsn or os.getenv("SENTRY_DSN")
    if not resolved_dsn:
        logger.info("[Sentry] No DSN configured — Sentry disabled")
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.httpx import HttpxIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        logging_integration = LoggingIntegration(
            level=logging.INFO,
            event_level=logging.ERROR,  # Only errors create Sentry events
        )

        sentry_sdk.init(
            dsn=resolved_dsn,
            environment=os.getenv("ENVIRONMENT", "production"),
            release=f"aria@{os.getenv('FLY_APP_VERSION', '2.0.0')}",
            traces_sample_rate=traces_sample_rate,
            profiles_sample_rate=profiles_sample_rate,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                HttpxIntegration(),
                logging_integration,
            ],
            before_send=_before_send,
            # PII scrubbing
            send_default_pii=False,
            # Attach a server name tag for Fly.io machine ID
            server_name=os.getenv("FLY_MACHINE_ID", "unknown"),
        )

        # Global tags applied to every event
        sentry_sdk.set_tag("aria.version", "2.0.0")
        sentry_sdk.set_tag("fly.region", os.getenv("FLY_REGION", "unknown"))

        _initialized = True
        logger.info("[Sentry] Initialized — environment=%s", os.getenv("ENVIRONMENT", "production"))

    except ImportError:
        logger.warning("[Sentry] sentry-sdk not installed — Sentry disabled")
    except Exception as exc:
        logger.error("[Sentry] Init failed: %s", exc)


def set_user_context(session_id: str) -> None:
    """Attach a non-PII user context to the current scope."""
    try:
        import sentry_sdk

        sentry_sdk.set_user({"id": session_id})
    except Exception:
        pass


def capture_exception(exc: Exception, **context: Any) -> None:
    """Capture an exception with optional additional context."""
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            for key, value in context.items():
                scope.set_extra(key, value)
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass


def capture_message(message: str, level: str = "info", **context: Any) -> None:
    """Capture a diagnostic message."""
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            for key, value in context.items():
                scope.set_extra(key, value)
            sentry_sdk.capture_message(message, level=level)
    except Exception:
        pass


# ── Filters ────────────────────────────────────────────────────────────────

_IGNORED_EXCEPTIONS = frozenset(
    {
        "asyncio.CancelledError",
        "starlette.exceptions.HTTPException",  # 404s, 422s are expected
        "websockets.exceptions.ConnectionClosedOK",
    }
)


def _before_send(event: dict, hint: dict) -> dict | None:
    """
    Drop non-actionable events before they reach Sentry.

    This keeps Sentry quota usage reasonable and signal-to-noise high.
    """
    exc_info = hint.get("exc_info")
    if exc_info:
        exc_type = exc_info[0]
        if exc_type is not None:
            qualified_name = f"{exc_type.__module__}.{exc_type.__qualname__}"
            if qualified_name in _IGNORED_EXCEPTIONS:
                return None

    # Drop 4xx HTTP errors (client errors, not our bugs)
    if _is_client_error(event):
        return None

    return event


def _is_client_error(event: dict) -> bool:
    """Check if the event is a client-side HTTP error (4xx)."""
    try:
        event.get("request", {})
        # Sentry attaches the response status code for web transactions
        for exc in event.get("exception", {}).get("values", []):
            if exc.get("type") == "HTTPException":
                status_code = exc.get("value", "").split()[0]
                if status_code.startswith("4"):
                    return True
    except Exception:
        pass
    return False
