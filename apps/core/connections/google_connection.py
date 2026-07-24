"""
Google OAuth connection for ARIA AI.
Scopes: Gmail (read+send), Calendar (read+write), Drive (read).

Requires in Fly.io secrets:
  GOOGLE_CLIENT_ID     → from console.cloud.google.com → Credentials → OAuth 2.0
  GOOGLE_CLIENT_SECRET → same place
  (GOOGLE_API_KEY already exists — this is DIFFERENT, it's OAuth for user accounts)
"""

from __future__ import annotations

import base64
import logging
from datetime import UTC
from email.mime.text import MIMEText
from urllib.parse import urlencode

import httpx

from apps.core.connections.base import BaseConnector
from apps.core.connections.registry import register_connector

logger = logging.getLogger("aria.connections.google")

REDIRECT_URI = "https://aria-ai.fly.dev/oauth/callback/google"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = " ".join(
    [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/userinfo.email",
    ]
)


@register_connector("google", display_name="Google (Gmail, Calendar, Drive)")
class GoogleConnection(BaseConnector):

    def _client_id(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "GOOGLE_CLIENT_ID", None)

    def _client_secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "GOOGLE_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> str | None:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": chat_id,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> dict | None:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not configured")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": cid,
                    "client_secret": sec,
                    "redirect_uri": REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            r.raise_for_status()
            data = r.json()
            # Get user email
            email = await self._get_email(data["access_token"])
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
            r = await http.post(
                TOKEN_URL,
                data={
                    "refresh_token": tokens["refresh_token"],
                    "client_id": cid,
                    "client_secret": sec,
                    "grant_type": "refresh_token",
                },
            )
            r.raise_for_status()
            data = r.json()
            tokens["access_token"] = data["access_token"]
            return tokens

    async def _get_email(self, access_token: str) -> str:
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            return r.json().get("email", "unknown") if r.status_code == 200 else "unknown"

    def _headers(self, tokens: dict) -> dict:
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    # ── GMAIL ──────────────────────────────────────────────────────────────

    async def gmail_list(self, tokens: dict, max_results: int = 10, query: str = "") -> list[dict]:
        """Lists recent Gmail messages."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            params = {"maxResults": max_results, "q": query or "is:unread"}
            r = await http.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers=self._headers(tokens),
                params=params,
            )
            if r.status_code != 200:
                raise RuntimeError(f"Gmail error {r.status_code}: {r.text[:200]}")
            msgs = r.json().get("messages", [])
            results = []
            for m in msgs[:5]:  # fetch details for first 5
                detail = await http.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{m['id']}",
                    headers=self._headers(tokens),
                    params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
                )
                if detail.status_code == 200:
                    d = detail.json()
                    headers = {
                        h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])
                    }
                    results.append(
                        {
                            "id": m["id"],
                            "subject": headers.get("Subject", "(no subject)"),
                            "from": headers.get("From", ""),
                            "date": headers.get("Date", ""),
                            "snippet": d.get("snippet", ""),
                        }
                    )
            return results

    async def gmail_send(self, tokens: dict, to: str, subject: str, body: str) -> dict:
        """Sends an email via Gmail."""
        msg = MIMEText(body, "plain", "utf-8")
        msg["to"] = to
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers={**self._headers(tokens), "Content-Type": "application/json"},
                json={"raw": raw},
            )
            r.raise_for_status()
            return {"success": True, "message_id": r.json().get("id")}

    async def gmail_read(self, tokens: dict, message_id: str) -> dict:
        """Reads the full body of an email."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
                headers=self._headers(tokens),
                params={"format": "full"},
            )
            r.raise_for_status()
            data = r.json()
            headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
            # Extract body
            parts = data.get("payload", {}).get("parts", [])
            body = ""
            for p in parts:
                if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
                    body = base64.urlsafe_b64decode(p["body"]["data"]).decode(
                        "utf-8", errors="replace"
                    )
                    break
            if not body and data.get("payload", {}).get("body", {}).get("data"):
                body = base64.urlsafe_b64decode(data["payload"]["body"]["data"]).decode(
                    "utf-8", errors="replace"
                )
            return {
                "id": message_id,
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
                "body": body[:2000],
            }

    # ── CALENDAR ──────────────────────────────────────────────────────────

    async def calendar_list(self, tokens: dict, max_results: int = 10) -> list[dict]:
        """Lists upcoming calendar events."""
        from datetime import datetime

        now = datetime.now(UTC).isoformat()
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers=self._headers(tokens),
                params={
                    "maxResults": max_results,
                    "orderBy": "startTime",
                    "singleEvents": True,
                    "timeMin": now,
                },
            )
            if r.status_code != 200:
                raise RuntimeError(f"Calendar error {r.status_code}: {r.text[:200]}")
            events = r.json().get("items", [])
            return [
                {
                    "id": e.get("id"),
                    "title": e.get("summary", "(no title)"),
                    "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
                    "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
                    "description": e.get("description", "")[:200],
                    "location": e.get("location", ""),
                }
                for e in events
            ]

    async def calendar_create(
        self,
        tokens: dict,
        title: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
    ) -> dict:
        """Creates an event in Google Calendar."""
        event = {
            "summary": title,
            "description": description,
            "location": location,
            "start": {"dateTime": start, "timeZone": "America/New_York"},
            "end": {"dateTime": end, "timeZone": "America/New_York"},
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={**self._headers(tokens), "Content-Type": "application/json"},
                json=event,
            )
            r.raise_for_status()
            d = r.json()
            return {"success": True, "event_id": d.get("id"), "link": d.get("htmlLink")}

    # ── DRIVE ─────────────────────────────────────────────────────────────

    async def drive_search(self, tokens: dict, query: str, max_results: int = 10) -> list[dict]:
        """Searches for files in Google Drive."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                "https://www.googleapis.com/drive/v3/files",
                headers=self._headers(tokens),
                params={
                    "q": f"name contains '{query}' and trashed=false",
                    "pageSize": max_results,
                    "fields": "files(id,name,mimeType,modifiedTime,webViewLink,size)",
                },
            )
            r.raise_for_status()
            return [
                {
                    "id": f.get("id"),
                    "name": f.get("name"),
                    "type": f.get("mimeType", "").split(".")[-1],
                    "modified": f.get("modifiedTime", ""),
                    "link": f.get("webViewLink", ""),
                    "size_bytes": int(f.get("size", 0)),
                }
                for f in r.json().get("files", [])
            ]
