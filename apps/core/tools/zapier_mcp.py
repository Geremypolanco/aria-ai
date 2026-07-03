"""
zapier_mcp.py — Minimal Model Context Protocol (streamable HTTP) client for the
user's Zapier MCP server.

This is the bridge that lets ARIA publish to every account the owner has already
connected in Zapier (Instagram, YouTube, Pinterest, LinkedIn, Buffer, ...) using a
SINGLE credential — the Zapier MCP endpoint URL (which embeds its own key) — instead
of provisioning OAuth apps for each platform.

Configuration: set the ``ZAPIER_MCP_URL`` secret to the full MCP endpoint URL copied
from https://mcp.zapier.com (it looks like ``https://mcp.zapier.com/api/mcp/s/<token>/mcp``).
Degrades gracefully to a no-op when unconfigured.

Protocol notes: the Zapier MCP server speaks JSON-RPC 2.0 over "streamable HTTP".
Responses arrive either as ``application/json`` or as an SSE stream
(``text/event-stream`` with ``event: message`` / ``data: {...}`` frames). We parse
both. A stateful session is established with an ``initialize`` handshake; the server
returns an ``Mcp-Session-Id`` header that we echo on every subsequent request.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.tools.zapier_mcp")

_PROTOCOL_VERSION = "2025-06-18"


class ZapierMCPClient:
    """Tiny JSON-RPC-over-HTTP client for a single Zapier MCP server."""

    def __init__(self, url: str | None = None, timeout: float = 90.0) -> None:
        # 90s: Zapier publish actions (video transcode, etc.) can be slow.
        self.url = (url or getattr(settings, "ZAPIER_MCP_URL", None) or "").strip()
        self.timeout = timeout
        self._session_id: str | None = None
        self._rpc_id = 0
        self._initialized = False

    @property
    def configured(self) -> bool:
        return bool(self.url)

    # ── low-level transport ───────────────────────────────────────────────

    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    @staticmethod
    def _parse_body(resp: httpx.Response) -> dict[str, Any]:
        """Return the JSON-RPC payload from either a JSON or SSE response body."""
        ctype = resp.headers.get("content-type", "")
        text = resp.text
        if "text/event-stream" in ctype or text.lstrip().startswith("event:"):
            # Parse SSE frames; keep the last `data:` JSON object that has a result/error.
            last: dict[str, Any] = {}
            for line in text.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:") :].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                    last = obj
            return last
        try:
            return resp.json()
        except (json.JSONDecodeError, ValueError):
            return {}

    async def _rpc(
        self,
        client: httpx.AsyncClient,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        is_notification: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not is_notification:
            body["id"] = self._next_id()

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        resp = await client.post(self.url, json=body, headers=headers)
        # Capture the session id handed back on initialize.
        sid = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id")
        if sid:
            self._session_id = sid
        if is_notification:
            return {}
        resp.raise_for_status()
        return self._parse_body(resp)

    async def _ensure_initialized(self, client: httpx.AsyncClient) -> None:
        if self._initialized:
            return
        init = await self._rpc(
            client,
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "aria-content-operator", "version": "1.0"},
            },
        )
        if init.get("error"):
            raise RuntimeError(f"MCP initialize failed: {init['error']}")
        # Best-effort initialized notification (some servers require it before tools/*).
        try:
            await self._rpc(client, "notifications/initialized", {}, is_notification=True)
        except Exception as exc:  # noqa: BLE001 - notification is best-effort
            logger.debug("[ZapierMCP] initialized notification skipped: %s", exc)
        self._initialized = True

    # ── public API ────────────────────────────────────────────────────────

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return the raw tool descriptors exposed by the server."""
        if not self.configured:
            return []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await self._ensure_initialized(client)
            out = await self._rpc(client, "tools/list", {})
        if out.get("error"):
            raise RuntimeError(f"tools/list failed: {out['error']}")
        return out.get("result", {}).get("tools", []) or []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Invoke a tool by exact name. Returns a normalized dict:
        ``{"success": bool, "text": str, "raw": <result>, "error": str|None}``.
        """
        if not self.configured:
            return {"success": False, "error": "ZAPIER_MCP_URL not configured", "text": ""}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                await self._ensure_initialized(client)
                out = await self._rpc(
                    client, "tools/call", {"name": name, "arguments": arguments}
                )
        except Exception as exc:  # noqa: BLE001 - surface transport errors as data
            logger.error("[ZapierMCP] call_tool(%s) transport error: %s", name, exc)
            return {"success": False, "error": str(exc), "text": ""}

        if out.get("error"):
            return {"success": False, "error": str(out["error"]), "text": "", "raw": out}

        result = out.get("result", {}) or {}
        # MCP content blocks → concatenated text.
        text_parts = [
            block.get("text", "")
            for block in result.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = "\n".join(p for p in text_parts if p)
        is_error = bool(result.get("isError"))
        # Zapier embeds a JSON string in the text block; treat an explicit error field there as failure.
        if not is_error and text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and parsed.get("isError"):
                    is_error = True
            except json.JSONDecodeError:
                pass
        return {"success": not is_error, "text": text, "raw": result, "error": None}

    async def find_tool(self, *keywords: str) -> str | None:
        """
        Find the name of a tool whose name contains ALL given keywords
        (case-insensitive). Useful to resolve e.g. ("instagram", "video") without
        hardcoding Zapier's exact tool naming. Returns None if not found.
        """
        tools = await self.list_tools()
        kws = [k.lower() for k in keywords]
        for tool in tools:
            name = str(tool.get("name", "")).lower()
            if all(k in name for k in kws):
                return tool["name"]
        return None

    async def self_test(self) -> dict[str, Any]:
        """Health check: verify the endpoint is reachable and list available tools."""
        if not self.configured:
            return {"ok": False, "error": "ZAPIER_MCP_URL not configured", "tool_count": 0}
        try:
            tools = await self.list_tools()
            return {
                "ok": True,
                "tool_count": len(tools),
                "sample_tools": [t.get("name") for t in tools[:15]],
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "tool_count": 0}


_client: ZapierMCPClient | None = None


def get_zapier_mcp() -> ZapierMCPClient:
    """Process-wide singleton."""
    global _client
    if _client is None:
        _client = ZapierMCPClient()
    return _client
