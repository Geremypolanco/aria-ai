"""
Microsoft Graph API OAuth connection for ARIA AI.
Scopes: Outlook mail (read+send), Calendar (read+write), OneDrive (read+write),
        Teams (channels + messages).

Requiere en Fly.io secrets:
  MICROSOFT_CLIENT_ID     → desde portal.azure.com → App registrations
  MICROSOFT_CLIENT_SECRET → mismo lugar
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("aria.connections.microsoft")

REDIRECT_URI = "https://aria-ai.fly.dev/oauth/callback/microsoft"
AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
SCOPES = "offline_access Mail.ReadWrite Mail.Send Calendars.ReadWrite Files.ReadWrite Team.ReadBasic.All Chat.ReadWrite"

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class MicrosoftConnection:

    def _client_id(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "MICROSOFT_CLIENT_ID", None)

    def _client_secret(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "MICROSOFT_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> Optional[str]:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "response_mode": "query",
            "state": chat_id,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> Optional[dict]:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("MICROSOFT_CLIENT_ID / MICROSOFT_CLIENT_SECRET no configurados")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(TOKEN_URL, data={
                "code": code,
                "client_id": cid,
                "client_secret": sec,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
                "scope": SCOPES,
            })
            r.raise_for_status()
            data = r.json()
            # Fetch user email from /me
            me_r = await http.get(
                f"{GRAPH_BASE}/me",
                headers={"Authorization": f"Bearer {data['access_token']}"},
            )
            email = me_r.json().get("mail") or me_r.json().get("userPrincipalName", "unknown") \
                if me_r.status_code == 200 else "unknown"
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in", 3600),
                "scope": data.get("scope", ""),
                "service_user": email,
            }

    async def refresh_token(self, tokens: dict) -> dict:
        cid = self._client_id()
        sec = self._client_secret()
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(TOKEN_URL, data={
                "refresh_token": tokens["refresh_token"],
                "client_id": cid,
                "client_secret": sec,
                "grant_type": "refresh_token",
                "scope": SCOPES,
            })
            r.raise_for_status()
            data = r.json()
            tokens["access_token"] = data["access_token"]
            if data.get("refresh_token"):
                tokens["refresh_token"] = data["refresh_token"]
            return tokens

    def _headers(self, tokens: dict) -> dict:
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    # ── OUTLOOK MAIL ──────────────────────────────────────────────────────

    async def outlook_list(self, tokens: dict, max_results: int = 10, query: str = "") -> list[dict]:
        """List recent Outlook messages."""
        params: dict[str, Any] = {
            "$top": max_results,
            "$select": "id,subject,from,receivedDateTime,bodyPreview",
            "$orderby": "receivedDateTime desc",
        }
        if query:
            params["$search"] = f'"{query}"'
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{GRAPH_BASE}/me/messages",
                headers=self._headers(tokens),
                params=params,
            )
            if r.status_code != 200:
                raise RuntimeError(f"Outlook list error {r.status_code}: {r.text[:200]}")
            messages = r.json().get("value", [])
            return [
                {
                    "id": m.get("id"),
                    "subject": m.get("subject", "(no subject)"),
                    "from": m.get("from", {}).get("emailAddress", {}).get("address", ""),
                    "date": m.get("receivedDateTime", ""),
                    "snippet": m.get("bodyPreview", "")[:200],
                }
                for m in messages
            ]

    async def outlook_send(self, tokens: dict, to: str, subject: str, body: str) -> dict:
        """Send an email via Outlook."""
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to}}],
            },
            "saveToSentItems": True,
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{GRAPH_BASE}/me/sendMail",
                headers={**self._headers(tokens), "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            # sendMail returns 202 No Content on success
            return {"success": True, "message_id": None}

    # ── CALENDAR ─────────────────────────────────────────────────────────

    async def calendar_list(self, tokens: dict, max_results: int = 10) -> list[dict]:
        """List upcoming calendar events."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {
            "$top": max_results,
            "$select": "id,subject,start,end,location,bodyPreview,organizer",
            "$orderby": "start/dateTime asc",
            "startdatetime": now,
            "enddatetime": "9999-12-31T00:00:00Z",
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{GRAPH_BASE}/me/calendarView",
                headers=self._headers(tokens),
                params=params,
            )
            if r.status_code != 200:
                raise RuntimeError(f"Calendar list error {r.status_code}: {r.text[:200]}")
            events = r.json().get("value", [])
            return [
                {
                    "id": e.get("id"),
                    "title": e.get("subject", "(no title)"),
                    "start": e.get("start", {}).get("dateTime", ""),
                    "end": e.get("end", {}).get("dateTime", ""),
                    "location": e.get("location", {}).get("displayName", ""),
                    "description": e.get("bodyPreview", "")[:200],
                    "organizer": e.get("organizer", {}).get("emailAddress", {}).get("address", ""),
                }
                for e in events
            ]

    async def calendar_create(self, tokens: dict, title: str, start: str, end: str,
                               description: str = "", location: str = "") -> dict:
        """Create a calendar event."""
        event = {
            "subject": title,
            "body": {"contentType": "Text", "content": description},
            "start": {"dateTime": start, "timeZone": "America/New_York"},
            "end": {"dateTime": end, "timeZone": "America/New_York"},
            "location": {"displayName": location},
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{GRAPH_BASE}/me/events",
                headers={**self._headers(tokens), "Content-Type": "application/json"},
                json=event,
            )
            r.raise_for_status()
            d = r.json()
            return {
                "success": True,
                "event_id": d.get("id"),
                "link": d.get("webLink"),
            }

    # ── ONEDRIVE ─────────────────────────────────────────────────────────

    async def onedrive_search(self, tokens: dict, query: str, max_results: int = 10) -> list[dict]:
        """Search files in OneDrive."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{GRAPH_BASE}/me/drive/root/search(q='{query}')",
                headers=self._headers(tokens),
                params={
                    "$top": max_results,
                    "$select": "id,name,size,lastModifiedDateTime,webUrl,file,folder",
                },
            )
            if r.status_code != 200:
                raise RuntimeError(f"OneDrive search error {r.status_code}: {r.text[:200]}")
            items = r.json().get("value", [])
            return [
                {
                    "id": f.get("id"),
                    "name": f.get("name"),
                    "type": "folder" if "folder" in f else f.get("file", {}).get("mimeType", "file"),
                    "modified": f.get("lastModifiedDateTime", ""),
                    "link": f.get("webUrl", ""),
                    "size_bytes": f.get("size", 0),
                }
                for f in items
            ]

    # ── TEAMS ────────────────────────────────────────────────────────────

    async def teams_list_channels(self, tokens: dict) -> list[dict]:
        """List Teams and their channels the user belongs to."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            # Get joined teams first
            teams_r = await http.get(
                f"{GRAPH_BASE}/me/joinedTeams",
                headers=self._headers(tokens),
                params={"$select": "id,displayName,description"},
            )
            if teams_r.status_code != 200:
                raise RuntimeError(f"Teams list error {teams_r.status_code}: {teams_r.text[:200]}")
            teams = teams_r.json().get("value", [])
            results = []
            for team in teams:
                channels_r = await http.get(
                    f"{GRAPH_BASE}/teams/{team['id']}/channels",
                    headers=self._headers(tokens),
                    params={"$select": "id,displayName,description"},
                )
                channels = channels_r.json().get("value", []) if channels_r.status_code == 200 else []
                results.append({
                    "team_id": team.get("id"),
                    "team_name": team.get("displayName"),
                    "description": team.get("description", ""),
                    "channels": [
                        {
                            "channel_id": c.get("id"),
                            "channel_name": c.get("displayName"),
                            "description": c.get("description", ""),
                        }
                        for c in channels
                    ],
                })
            return results

    async def teams_send_message(self, tokens: dict, team_id: str, channel_id: str,
                                  message: str) -> dict:
        """Send a message to a Teams channel."""
        payload = {
            "body": {"content": message, "contentType": "text"},
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages",
                headers={**self._headers(tokens), "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            d = r.json()
            return {
                "success": True,
                "message_id": d.get("id"),
                "created_at": d.get("createdDateTime"),
            }
