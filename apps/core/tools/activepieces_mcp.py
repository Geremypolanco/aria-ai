"""ActivePieces MCP adapter for ARIA.

This adapter provides a small, well-known surface that ARIA's codebase can
call. It intentionally keeps behaviour conservative and easy to mock in
tests: list_flows(), execute_flow(), self_test(), status_for(email).

It reads configuration from environment variables:
- ACTIVEPIECES_MCP_URL
- ACTIVEPIECES_API_KEY

See docs/integrations/activepieces.md for deployment notes.
"""
from __future__ import annotations

import os
import logging
from typing import Any, Dict, List

from apps.core.integrations.activepieces_client import get_activepieces_client

logger = logging.getLogger("aria.activepieces_mcp")


class ActivePiecesMCP:
    def __init__(self, url: str | None = None, api_key: str | None = None):
        self.url = url or os.environ.get("ACTIVEPIECES_MCP_URL")
        self.api_key = api_key or os.environ.get("ACTIVEPIECES_API_KEY")
        self.client = get_activepieces_client(self.url, self.api_key)

    async def self_test(self) -> Dict[str, Any]:
        return await self.client.self_test()

    async def list_flows(self) -> List[Dict[str, Any]]:
        return await self.client.list_flows()

    async def execute_flow(self, flow_id: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return await self.client.execute_flow(flow_id, inputs)

    async def get_execution_status(self, exec_id: str) -> Dict[str, Any]:
        return await self.client.get_execution_status(exec_id)

    async def status_for(self, email: str) -> Dict[str, Any]:
        # Provide a small status object similar to other MCP adapters.
        try:
            health = await self.self_test()
            return {"ok": health.get("ok", False), "health": health}
        except Exception as exc:
            logger.debug("activepieces status_for failed: %s", exc)
            return {"ok": False, "error": str(exc)}


# Singleton accessor
_mcp_singleton: ActivePiecesMCP | None = None


def get_activepieces_mcp() -> ActivePiecesMCP:
    global _mcp_singleton
    if _mcp_singleton is None:
        _mcp_singleton = ActivePiecesMCP()
    return _mcp_singleton
