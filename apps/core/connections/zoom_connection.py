"""
Zoom OAuth connection for ARIA AI.
Scopes: meeting:read meeting:write user:read.

Requiere en Fly.io secrets:
  ZOOM_CLIENT_ID     → desde marketplace.zoom.us → Develop → Build App
  ZOOM_CLIENT_SECRET → mismo lugar
"""

from __future__ import annotations

import base64
import logging
from urllib.parse import urlencode

import httpx

from apps.core.connections.base import BaseConnector
from apps.core.connections.registry import register_connector

logger = logging.getLogger("aria.connections.zoom")

REDIRECT_URI = "https://aria-ai.fly.dev/oauth/callback/zoom"
AUTH_URL = "https://zoom.us/oauth/authorize"
TOKEN_URL = "https://zoom.us/oauth/token"
SCOPES = "meeting:read meeting:write user:read"

ZOOM_BASE = "https://api.zoom.us/v2"


@register_connector("zoom", display_name="Zoom (meetings, grabaciones)")
class ZoomConnection(BaseConnector):

    def _client_id(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "ZOOM_CLIENT_ID", None)

    def _client_secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "ZOOM_CLIENT_SECRET", None)

    def _basic_auth_header(self) -> str:
        """Base64-encoded Basic auth header for token endpoints."""
        cid = self._client_id() or ""
        sec = self._client_secret() or ""
        credentials = base64.b64encode(f"{cid}:{sec}".encode()).decode()
        return f"Basic {credentials}"

    def get_auth_url(self, chat_id: str) -> str | None:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "state": chat_id,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> dict | None:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("ZOOM_CLIENT_ID / ZOOM_CLIENT_SECRET no configurados")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                TOKEN_URL,
                headers={"Authorization": self._basic_auth_header()},
                data={
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            r.raise_for_status()
            data = r.json()
            # Fetch user email from /users/me
            me_r = await http.get(
                f"{ZOOM_BASE}/users/me",
                headers={"Authorization": f"Bearer {data['access_token']}"},
            )
            email = me_r.json().get("email", "unknown") if me_r.status_code == 200 else "unknown"
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in", 3600),
                "scope": data.get("scope", ""),
                "service_user": email,
            }

    async def refresh_token(self, tokens: dict) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                TOKEN_URL,
                headers={"Authorization": self._basic_auth_header()},
                data={
                    "refresh_token": tokens["refresh_token"],
                    "grant_type": "refresh_token",
                },
            )
            r.raise_for_status()
            data = r.json()
            tokens["access_token"] = data["access_token"]
            if data.get("refresh_token"):
                tokens["refresh_token"] = data["refresh_token"]
            return tokens

    def _headers(self, tokens: dict) -> dict:
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    # ── MEETINGS ─────────────────────────────────────────────────────────

    async def list_meetings(self, tokens: dict, meeting_type: str = "upcoming") -> list[dict]:
        """List meetings for the authenticated user.

        meeting_type: 'scheduled', 'live', 'upcoming' (default), or 'previous_meetings'.
        """
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{ZOOM_BASE}/users/me/meetings",
                headers=self._headers(tokens),
                params={"type": meeting_type, "page_size": 30},
            )
            if r.status_code != 200:
                raise RuntimeError(f"Zoom list_meetings error {r.status_code}: {r.text[:200]}")
            meetings = r.json().get("meetings", [])
            return [
                {
                    "id": str(m.get("id", "")),
                    "topic": m.get("topic", "(no topic)"),
                    "start_time": m.get("start_time", ""),
                    "duration": m.get("duration", 0),
                    "join_url": m.get("join_url", ""),
                }
                for m in meetings
            ]

    async def create_meeting(
        self, tokens: dict, topic: str, start_time: str, duration_min: int = 60, agenda: str = ""
    ) -> dict:
        """Create a Zoom meeting.

        start_time: ISO 8601 UTC string, e.g. '2024-06-01T14:00:00Z'.
        """
        payload = {
            "topic": topic,
            "type": 2,  # scheduled meeting
            "start_time": start_time,
            "duration": duration_min,
            "agenda": agenda,
            "settings": {
                "host_video": True,
                "participant_video": True,
                "join_before_host": False,
                "waiting_room": True,
            },
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{ZOOM_BASE}/users/me/meetings",
                headers={**self._headers(tokens), "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            d = r.json()
            return {
                "id": str(d.get("id", "")),
                "topic": d.get("topic", ""),
                "join_url": d.get("join_url", ""),
                "passcode": d.get("password", ""),
                "start_time": d.get("start_time", ""),
                "duration": d.get("duration", duration_min),
            }

    async def get_meeting(self, tokens: dict, meeting_id: str) -> dict:
        """Get details for a specific meeting."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{ZOOM_BASE}/meetings/{meeting_id}",
                headers=self._headers(tokens),
            )
            if r.status_code != 200:
                raise RuntimeError(f"Zoom get_meeting error {r.status_code}: {r.text[:200]}")
            d = r.json()
            return {
                "id": str(d.get("id", "")),
                "topic": d.get("topic", ""),
                "status": d.get("status", ""),
                "start_time": d.get("start_time", ""),
                "duration": d.get("duration", 0),
                "join_url": d.get("join_url", ""),
                "passcode": d.get("password", ""),
                "agenda": d.get("agenda", ""),
                "host_email": d.get("host_email", ""),
            }

    async def delete_meeting(self, tokens: dict, meeting_id: str) -> dict:
        """Delete (cancel) a meeting."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.delete(
                f"{ZOOM_BASE}/meetings/{meeting_id}",
                headers=self._headers(tokens),
            )
            if r.status_code not in (200, 204):
                raise RuntimeError(f"Zoom delete_meeting error {r.status_code}: {r.text[:200]}")
            return {"success": True, "meeting_id": meeting_id}
