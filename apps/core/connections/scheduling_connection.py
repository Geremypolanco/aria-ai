"""
Scheduling connection para ARIA AI.
Soporta Calendly (OAuth) y Cal.com (API key).
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("aria.connections.scheduling")

CALENDLY_AUTH_URL = "https://auth.calendly.com/oauth/authorize"
CALENDLY_TOKEN_URL = "https://auth.calendly.com/oauth/token"
CALENDLY_API = "https://api.calendly.com"
CALENDLY_SCOPES = "default"
CALENDLY_REDIRECT = "https://aria-ai.fly.dev/oauth/callback/calendly"

CALCOM_API = "https://api.cal.com/v1"


class CalendlyConnection:

    def _client_id(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "CALENDLY_CLIENT_ID", None)

    def _client_secret(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "CALENDLY_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> Optional[str]:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "response_type": "code",
            "redirect_uri": CALENDLY_REDIRECT,
            "state": chat_id,
        }
        return f"{CALENDLY_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> Optional[dict]:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("CALENDLY_CLIENT_ID / CALENDLY_CLIENT_SECRET no configurados")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(CALENDLY_TOKEN_URL, data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": CALENDLY_REDIRECT,
                "client_id": cid,
                "client_secret": sec,
            })
            r.raise_for_status()
            data = r.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "organization": data.get("organization"),
                "service_user": data.get("owner", "calendly_user"),
            }

    def _h(self, tokens: dict) -> dict:
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    async def get_user(self, tokens: dict) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{CALENDLY_API}/users/me", headers=self._h(tokens))
            r.raise_for_status()
            return r.json().get("resource", {})

    async def list_event_types(self, tokens: dict) -> list[dict]:
        user = await self.get_user(tokens)
        user_uri = user.get("uri", "")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{CALENDLY_API}/event_types",
                headers=self._h(tokens),
                params={"user": user_uri, "active": True},
            )
            r.raise_for_status()
            events = r.json().get("collection", [])
            return [
                {
                    "name": e.get("name"),
                    "slug": e.get("slug"),
                    "duration": e.get("duration"),
                    "scheduling_url": e.get("scheduling_url"),
                    "description": e.get("description_plain", ""),
                }
                for e in events
            ]

    async def list_scheduled_events(self, tokens: dict, count: int = 10) -> list[dict]:
        user = await self.get_user(tokens)
        user_uri = user.get("uri", "")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{CALENDLY_API}/scheduled_events",
                headers=self._h(tokens),
                params={"user": user_uri, "count": count, "sort": "start_time:desc"},
            )
            r.raise_for_status()
            events = r.json().get("collection", [])
            return [
                {
                    "name": e.get("name"),
                    "status": e.get("status"),
                    "start_time": e.get("start_time"),
                    "end_time": e.get("end_time"),
                    "location": e.get("location", {}).get("join_url", e.get("location", {}).get("location", "")),
                }
                for e in events
            ]

    async def cancel_event(self, tokens: dict, event_uuid: str, reason: str = "") -> dict:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{CALENDLY_API}/scheduled_events/{event_uuid}/cancellation",
                headers={**self._h(tokens), "Content-Type": "application/json"},
                json={"reason": reason},
            )
            return {"success": r.status_code in (200, 201), "status": r.status_code}


class CalComConnection:
    """Cal.com usando API key (CALCOM_API_KEY) — no requiere OAuth."""

    def _api_key(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "CALCOM_API_KEY", None)

    def _h(self) -> dict:
        key = self._api_key()
        return {"Authorization": f"Bearer {key}"} if key else {}

    async def list_event_types(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{CALCOM_API}/event-types", headers=self._h())
            r.raise_for_status()
            return [
                {
                    "id": et.get("id"),
                    "title": et.get("title"),
                    "slug": et.get("slug"),
                    "length": et.get("length"),
                    "description": et.get("description", ""),
                }
                for et in r.json().get("event_types", [])
            ]

    async def list_bookings(self, status: str = "upcoming") -> list[dict]:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{CALCOM_API}/bookings",
                headers=self._h(),
                params={"status": status},
            )
            r.raise_for_status()
            return [
                {
                    "id": b.get("id"),
                    "title": b.get("title"),
                    "start": b.get("startTime"),
                    "end": b.get("endTime"),
                    "status": b.get("status"),
                    "attendees": [a.get("email") for a in b.get("attendees", [])],
                }
                for b in r.json().get("bookings", [])
            ]

    async def cancel_booking(self, booking_id: int, reason: str = "") -> dict:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.delete(
                f"{CALCOM_API}/bookings/{booking_id}",
                headers=self._h(),
                params={"reason": reason} if reason else {},
            )
            return {"success": r.status_code == 200, "status": r.status_code}
