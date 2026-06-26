"""
zapier_connector.py — Dispatches automation events to Zapier webhooks.
Reads ZAPIER_WEBHOOK_URL from environment. Degrades gracefully when unconfigured.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.tools.zapier")


class ZapierConnector:
    """
    Dispatches ARIA lifecycle events to Zapier for downstream automation
    (Twitter, LinkedIn, Slack, email, etc.).
    """

    EVENT_NEW_PRODUCT = "NEW_PRODUCT"
    EVENT_CONTENT_READY = "CONTENT_READY"
    EVENT_SALE_ALERT = "SALE_ALERT"
    EVENT_SYSTEM_ERROR = "SYSTEM_ERROR"
    EVENT_CREATION_READY = "CREATION_READY"

    def __init__(self) -> None:
        self.timeout = 20.0
        # Never fall back to a hardcoded URL — require explicit configuration
        self.webhook_url = getattr(settings, "ZAPIER_WEBHOOK_URL", None) or ""
        if not self.webhook_url:
            logger.warning("[Zapier] ZAPIER_WEBHOOK_URL not configured — events will be no-ops")

    async def dispatch_event(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        Dispatch a structured event to the configured Zapier webhook.
        Always injects a timestamp so downstream zaps can log/sort events.
        """
        if not self.webhook_url:
            logger.debug("[Zapier] Skipping %s — no webhook URL configured", event_type)
            return {"success": False, "error": "ZAPIER_WEBHOOK_URL not configured"}

        payload = {
            "source": "ARIA AI",
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": data,
        }

        if "image_url" in data:
            payload["has_media"] = True
            payload["media_url"] = data["image_url"]
            payload["media_type"] = "image/hf"

        logger.info("[Zapier] Dispatching %s", event_type)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.webhook_url, json=payload)
                resp.raise_for_status()
                logger.info("[Zapier] %s dispatched → HTTP %d", event_type, resp.status_code)
                return {"success": True, "status": resp.status_code}
        except Exception as exc:
            logger.error("[Zapier] Error dispatching %s: %s", event_type, exc)
            return {"success": False, "error": str(exc)}

    async def trigger_webhook(self, webhook_url: str, data: dict[str, Any]) -> dict[str, Any]:
        """Backward-compat alias."""
        return await self.dispatch_event("GENERIC_TRIGGER", data)
