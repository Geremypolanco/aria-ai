"""
Slack connection para ARIA AI.

Dos modos:
1. Webhook (simple): solo SLACK_WEBHOOK_URL en secrets — enviar mensajes inmediatamente
2. OAuth completo: SLACK_CLIENT_ID + SLACK_CLIENT_SECRET — leer + escribir en cualquier canal

Para el modo webhook: ve a api.slack.com/apps → Incoming Webhooks → Add New Webhook
Para OAuth: ve a api.slack.com/apps → Create App → OAuth & Permissions
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import httpx

from apps.core.connections.base import BaseConnector
from apps.core.connections.registry import register_connector

logger = logging.getLogger("aria.connections.slack")

REDIRECT_URI = "https://aria-ai.fly.dev/oauth/callback/slack"
AUTH_URL = "https://slack.com/oauth/v2/authorize"
TOKEN_URL = "https://slack.com/api/oauth.v2.access"
SCOPES = "channels:read,channels:history,chat:write,files:read,users:read"


@register_connector("slack", display_name="Slack (mensajes, canales)")
class SlackConnection(BaseConnector):

    def _client_id(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "SLACK_CLIENT_ID", None)

    def _client_secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "SLACK_CLIENT_SECRET", None)

    def _webhook_url(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "SLACK_WEBHOOK_URL", None)

    def get_auth_url(self, chat_id: str) -> str | None:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "scope": SCOPES,
            "redirect_uri": REDIRECT_URI,
            "state": chat_id,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> dict | None:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("SLACK_CLIENT_ID / SLACK_CLIENT_SECRET no configurados")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": cid,
                    "client_secret": sec,
                    "redirect_uri": REDIRECT_URI,
                },
            )
            r.raise_for_status()
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(f"Slack OAuth error: {data.get('error')}")
            authed = data.get("authed_user", {})
            return {
                "access_token": data.get("access_token"),
                "bot_token": data.get("access_token"),
                "team_id": data.get("team", {}).get("id"),
                "team_name": data.get("team", {}).get("name"),
                "service_user": authed.get("id", "bot"),
            }

    # ── Modo webhook (simple) ──────────────────────────────────────────────

    async def send_webhook(self, text: str, blocks: list | None = None) -> dict:
        """Envía mensaje via Incoming Webhook (modo simple sin OAuth)."""
        url = self._webhook_url()
        if not url:
            return {"success": False, "error": "SLACK_WEBHOOK_URL no configurado"}
        payload: dict = {"text": text}
        if blocks:
            payload["blocks"] = blocks
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.post(url, json=payload)
            return {"success": r.status_code == 200, "status": r.status_code}

    # ── Modo OAuth (completo) ──────────────────────────────────────────────

    def _h(self, tokens: dict) -> dict:
        return {"Authorization": f"Bearer {tokens.get('bot_token') or tokens.get('access_token')}"}

    async def list_channels(self, tokens: dict) -> list[dict]:
        """Lista canales del workspace."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                "https://slack.com/api/conversations.list",
                headers=self._h(tokens),
                params={"limit": 50, "exclude_archived": True},
            )
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(f"Slack error: {data.get('error')}")
            return [
                {
                    "id": c["id"],
                    "name": c["name"],
                    "is_private": c.get("is_private", False),
                    "members": c.get("num_members", 0),
                }
                for c in data.get("channels", [])
            ]

    async def send_message(self, tokens: dict, channel: str, text: str) -> dict:
        """Envía mensaje a un canal (requiere OAuth)."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                "https://slack.com/api/chat.postMessage",
                headers={**self._h(tokens), "Content-Type": "application/json"},
                json={"channel": channel, "text": text, "mrkdwn": True},
            )
            data = r.json()
            return {"success": data.get("ok"), "ts": data.get("ts"), "error": data.get("error")}

    async def read_channel(self, tokens: dict, channel: str, limit: int = 20) -> list[dict]:
        """Lee mensajes recientes de un canal."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                "https://slack.com/api/conversations.history",
                headers=self._h(tokens),
                params={"channel": channel, "limit": limit},
            )
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(f"Slack error: {data.get('error')}")
            return [
                {
                    "ts": m.get("ts"),
                    "user": m.get("user", "bot"),
                    "text": m.get("text", ""),
                    "type": m.get("type"),
                }
                for m in data.get("messages", [])
                if m.get("type") == "message"
            ]
