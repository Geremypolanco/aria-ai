"""
workspace_tools.py — Gestión de Google Workspace (Gmail, Calendar, Drive) para ARIA AI.
Requiere GOOGLE_API_KEY con los scopes correspondientes o OAuth2.
"""
from __future__ import annotations
import logging
from typing import Any, Optional
import httpx
from apps.core.config import settings

logger = logging.getLogger("aria.workspace_tools")

class WorkspaceTools:
    """Herramientas de productividad de Google Workspace."""
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)
        self._key = settings.GOOGLE_API_KEY

    def _ok(self) -> bool:
        return bool(self._key)

    # ── GMAIL ─────────────────────────────────────────────────────
    async def gmail_list_messages(self, query: str = "is:unread", max_results: int = 10) -> dict[str, Any]:
        if not self._ok(): return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            params = {"key": self._key, "q": query, "maxResults": max_results}
            res = await self._http.get("https://gmail.googleapis.com/gmail/v1/users/me/messages", params=params)
            if res.status_code == 200:
                msgs = res.json().get("messages", [])
                return {"success": True, "messages": msgs, "count": len(msgs)}
            return {"success": False, "error": f"HTTP {res.status_code}: {res.text}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ── CALENDAR ──────────────────────────────────────────────────
    async def calendar_list_events(self, max_results: int = 10) -> dict[str, Any]:
        if not self._ok(): return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            params = {"key": self._key, "maxResults": max_results, "timeMin": "2024-01-01T00:00:00Z"}
            res = await self._http.get("https://www.googleapis.com/calendar/v3/calendars/primary/events", params=params)
            if res.status_code == 200:
                events = res.json().get("items", [])
                return {"success": True, "events": [{"summary": e.get("summary"), "start": e.get("start"), "url": e.get("htmlLink")} for e in events]}
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ── DRIVE ─────────────────────────────────────────────────────
    async def drive_list_files(self, query: str = "", max_results: int = 10) -> dict[str, Any]:
        if not self._ok(): return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            params = {"key": self._key, "pageSize": max_results, "fields": "files(id, name, mimeType, webViewLink)"}
            if query: params["q"] = query
            res = await self._http.get("https://www.googleapis.com/drive/v3/files", params=params)
            if res.status_code == 200:
                files = res.json().get("files", [])
                return {"success": True, "files": files}
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
