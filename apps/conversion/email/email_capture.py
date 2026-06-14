"""
Email Capture Engine — Captures emails and syncs to Klaviyo for marketing automation.
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional
from apps.core.tools.ai_client import get_ai_client, AIModel

from apps.core.memory.redis_client import get_cache

_CAPTURES_KEY = "conversion:email_captures:v1"
_CAPTURES_TTL = 86400 * 90  # 90 days


@dataclass
class EmailCaptureEvent:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    email: str = ""
    source: str = ""
    lead_data: dict = field(default_factory=dict)
    klaviyo_synced: bool = False
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "email": self.email,
            "source": self.source,
            "lead_data": self.lead_data,
            "klaviyo_synced": self.klaviyo_synced,
            "created_at": self.created_at,
        }


def _is_valid_email(email: str) -> bool:
    """Basic email validation — checks for @ and . presence."""
    return "@" in email and "." in email.split("@")[-1]


class EmailCaptureEngine:
    def __init__(self) -> None:
        self._captures: list[dict] = []
        self._loaded = False
        self._klaviyo_key = os.environ.get("KLAVIYO_PRIVATE_KEY", "")

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_CAPTURES_KEY)
                if isinstance(data, list):
                    self._captures = data
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_CAPTURES_KEY, self._captures[-1000:], ttl_seconds=_CAPTURES_TTL)
        except Exception:
            pass

    async def capture(
        self,
        email: str,
        source: str,
        lead_data: dict = {},
    ) -> EmailCaptureEvent:
        await self._load()

        valid = _is_valid_email(email)
        klaviyo_synced = False

        if valid and self._klaviyo_key:
            properties = {
                "source": source,
                **{k: v for k, v in lead_data.items() if isinstance(v, (str, int, float, bool))},
            }
            klaviyo_synced = await self._sync_to_klaviyo(email, properties)

        event = EmailCaptureEvent(
            email=email,
            source=source,
            lead_data=lead_data,
            klaviyo_synced=klaviyo_synced,
        )

        self._captures.append(event.to_dict())
        await self._save()
        return event

    async def _sync_to_klaviyo(self, email: str, properties: dict) -> bool:
        """Sync profile to Klaviyo. Gracefully degrades if API key missing or request fails."""
        if not self._klaviyo_key:
            return False
        try:
            import httpx
            headers = {
                "Authorization": f"Klaviyo-API-Key {self._klaviyo_key}",
                "revision": "2024-10-15",
                "Content-Type": "application/json",
            }
            payload = {
                "data": {
                    "type": "profile",
                    "attributes": {
                        "email": email,
                        "properties": properties,
                    },
                }
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://a.klaviyo.com/api/profiles/",
                    json=payload,
                    headers=headers,
                    timeout=10.0,
                )
                return resp.status_code in (200, 201, 409)
        except Exception:
            return False

    async def add_to_list(self, email: str, list_id: str) -> bool:
        """Add profile to a Klaviyo list."""
        if not self._klaviyo_key:
            return False
        try:
            import httpx
            # First, find or create profile to get profile_id
            headers = {
                "Authorization": f"Klaviyo-API-Key {self._klaviyo_key}",
                "revision": "2024-10-15",
                "Content-Type": "application/json",
            }
            payload = {
                "data": [
                    {"type": "profile", "attributes": {"email": email}}
                ]
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://a.klaviyo.com/api/lists/{list_id}/relationships/profiles/",
                    json=payload,
                    headers=headers,
                    timeout=10.0,
                )
                return resp.status_code in (200, 201, 204)
        except Exception:
            return False

    async def trigger_flow(
        self,
        email: str,
        flow_trigger: str,
        properties: dict = {},
    ) -> bool:
        """Trigger a Klaviyo flow via event tracking."""
        if not self._klaviyo_key:
            return False
        try:
            import httpx
            headers = {
                "Authorization": f"Klaviyo-API-Key {self._klaviyo_key}",
                "revision": "2024-10-15",
                "Content-Type": "application/json",
            }
            payload = {
                "data": {
                    "type": "event",
                    "attributes": {
                        "metric": {"data": {"type": "metric", "attributes": {"name": flow_trigger}}},
                        "profile": {"data": {"type": "profile", "attributes": {"email": email}}},
                        "properties": properties,
                        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    },
                }
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://a.klaviyo.com/api/events/",
                    json=payload,
                    headers=headers,
                    timeout=10.0,
                )
                return resp.status_code in (200, 201, 202)
        except Exception:
            return False

    def capture_stats(self) -> dict:
        """Stats on email captures."""
        total = len(self._captures)
        synced = sum(1 for c in self._captures if c.get("klaviyo_synced"))
        by_source: dict[str, int] = {}
        valid_count = 0

        for c in self._captures:
            src = c.get("source", "unknown")
            by_source[src] = by_source.get(src, 0) + 1
            if _is_valid_email(c.get("email", "")):
                valid_count += 1

        return {
            "total_captures": total,
            "klaviyo_synced": synced,
            "by_source": by_source,
            "conversion_rate": valid_count / total if total > 0 else 0.0,
        }

    def recent_captures(self, limit: int = 20) -> list[dict]:
        """Return most recent captures."""
        return list(reversed(self._captures[-limit:]))


_email_capture_instance: Optional[EmailCaptureEngine] = None


def get_email_capture_engine() -> EmailCaptureEngine:
    global _email_capture_instance
    if _email_capture_instance is None:
        _email_capture_instance = EmailCaptureEngine()
    return _email_capture_instance
