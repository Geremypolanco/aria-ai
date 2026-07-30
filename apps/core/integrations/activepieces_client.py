# ActivePieces MCP client for ARIA

"""Minimal async client for talking to an Activepieces MCP endpoint.

This client implements a pragmatic, forgiving surface: ActivePieces' MCP
endpoints have varied across versions and deployment choices (some expose
/api/flows, some /mcp/flows, some a /health path). The client tries a small
set of expected endpoints and returns the first successful response.

The goal here is to provide a resilient adapter that lets ARIA call a
self-hosted Activepieces instance (infra/activepieces) and execute flows
or list available flows without hard-coupling to a single URL shape.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("aria.activepieces_client")


class ActivePiecesClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = 8.0):
        self.base = (base_url or os.environ.get("ACTIVEPIECES_MCP_URL") or "").rstrip("/")
        self.api_key = api_key or os.environ.get("ACTIVEPIECES_API_KEY")
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=self.timeout)

    def _headers(self) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def _try_get(self, path: str) -> Optional[httpx.Response]:
        url = f"{self.base}{path}"
        try:
            resp = await self._client.get(url, headers=self._headers())
            if resp.status_code == 200:
                return resp
        except Exception as exc:  # pragma: no cover - best-effort network call
            logger.debug("activepieces GET %s failed: %s", url, exc)
        return None

    async def _try_post(self, path: str, json: Any) -> Optional[httpx.Response]:
        url = f"{self.base}{path}"
        try:
            resp = await self._client.post(url, json=json, headers=self._headers())
            if resp.status_code in (200, 201):
                return resp
        except Exception as exc:  # pragma: no cover
            logger.debug("activepieces POST %s failed: %s", url, exc)
        return None

    async def self_test(self) -> Dict[str, Any]:
        """Check reachability and return a small health dict."""
        if not self.base:
            return {"ok": False, "error": "ACTIVEPIECES_MCP_URL not configured"}

        # try a small set of expected health endpoints
        candidates = ["/api/health", "/health", "/", "/api/ping"]
        for p in candidates:
            r = await self._try_get(p)
            if r:
                try:
                    return {"ok": True, "endpoint": p, "body": r.json()}
                except Exception:
                    return {"ok": True, "endpoint": p, "status": r.status_code}
        return {"ok": False, "error": "no reachable health endpoint on ActivePieces MCP"}

    async def list_flows(self) -> List[Dict[str, Any]]:
        """Attempt to discover flows/pieces on the target MCP instance.

        Returns a list of dicts (may be empty on failure)."""
        if not self.base:
            return []
        candidates = ["/api/flows", "/flows", "/api/pieces", "/mcp/flows"]
        for p in candidates:
            r = await self._try_get(p)
            if r:
                try:
                    data = r.json()
                    # allow both {"data": [...]} and direct lists
                    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                        return data["data"]
                    if isinstance(data, list):
                        return data
                except Exception:
                    logger.debug("activepieces: list_flows but failed to parse JSON from %s", p)
        return []

    async def execute_flow(self, flow_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Try to start a flow execution and return the execution response.

        The concrete endpoint shape differs between installs; try several
        known endpoints and return the first successful result.
        """
        if not self.base:
            raise RuntimeError("ACTIVEPIECES_MCP_URL not configured")

        payload = {"flow_id": flow_id, "input": input_data}
        candidates = ["/api/executions", "/executions", "/mcp/execute", "/api/run"]
        for p in candidates:
            r = await self._try_post(p, payload)
            if r:
                try:
                    return {"ok": True, "endpoint": p, "result": r.json()}
                except Exception:
                    return {"ok": True, "endpoint": p, "status": r.status_code}
        return {"ok": False, "error": "no execution endpoint accepted the request"}

    async def get_execution_status(self, exec_id: str) -> Dict[str, Any]:
        """Query execution status (best-effort)."""
        if not self.base:
            return {"ok": False, "error": "ACTIVEPIECES_MCP_URL not configured"}
        candidates = [f"/api/executions/{exec_id}", f"/executions/{exec_id}", f"/mcp/executions/{exec_id}"]
        for p in candidates:
            r = await self._try_get(p)
            if r:
                try:
                    return {"ok": True, "endpoint": p, "result": r.json()}
                except Exception:
                    return {"ok": True, "endpoint": p, "status": r.status_code}
        return {"ok": False, "error": "execution not found"}

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass


# Convenience singleton factory used by the adapter below.
_client_singleton: ActivePiecesClient | None = None


def get_activepieces_client(base_url: str | None = None, api_key: str | None = None) -> ActivePiecesClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = ActivePiecesClient(base_url=base_url, api_key=api_key)
    return _client_singleton
