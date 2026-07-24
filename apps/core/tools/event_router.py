"""
event_router.py — Event routing with RudderStack for ARIA AI.

Allows ARIA to send tracking events to multiple destinations:
  - PostHog (Analytics)
  - Google Analytics
  - Data Warehouses
  - CRMs

Reference: https://www.rudderstack.com/docs/sources/event-streams/sdks/rudderstack-python-sdk/
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("aria.event_router")

# ── RudderStack import with fallback ─────────────────────────────────────────
try:
    import rudderanalytics

    RUDDER_AVAILABLE = True
    logger.info("[RudderStack] SDK loaded successfully.")
except ImportError:
    RUDDER_AVAILABLE = False
    logger.warning("[RudderStack] rudder-sdk-python not installed.")


class AriaEventRouter:
    """
    ARIA's event router.
    Centralizes tracking to distribute it to multiple platforms.
    """

    def __init__(self, write_key: str = "", data_plane_url: str = "") -> None:
        self.write_key = write_key
        self.data_plane_url = data_plane_url

        if RUDDER_AVAILABLE and write_key:
            rudderanalytics.write_key = write_key
            rudderanalytics.data_plane_url = data_plane_url
            logger.info("[EventRouter] RudderStack initialized.")

    def track_event(self, user_id: str, event: str, properties: dict[str, Any] | None = None):
        """Sends a tracking event."""
        if not RUDDER_AVAILABLE or not self.write_key:
            logger.debug("[EventRouter] Simulated tracking: %s for %s", event, user_id)
            return

        try:
            rudderanalytics.track(user_id, event, properties or {})
            logger.info("[EventRouter] Event '%s' sent to RudderStack.", event)
        except Exception as exc:
            logger.error("[EventRouter] Error sending event: %s", exc)


# ── Singleton ────────────────────────────────────────────────────────────────
_event_router_instance: AriaEventRouter | None = None


def get_event_router() -> AriaEventRouter:
    """Returns the event router singleton."""
    global _event_router_instance
    if _event_router_instance is None:
        import os

        _event_router_instance = AriaEventRouter(
            write_key=os.getenv("RUDDERSTACK_WRITE_KEY", ""),
            data_plane_url=os.getenv("RUDDERSTACK_DATA_PLANE_URL", ""),
        )
    return _event_router_instance
