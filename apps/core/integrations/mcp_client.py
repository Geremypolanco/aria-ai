"""
mcp_client.py — Model Context Protocol (MCP) Client for ARIA.

This client allows ARIA to connect to and interact with any MCP server,
dynamically extending its capabilities with new tools, resources, and prompts.
"""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    import asyncio

logger = logging.getLogger("aria.mcp_client")


class McpClient:
    """MCP client for interacting with servers that implement the Model Context Protocol."""

    def __init__(self, server_url: str, client_info: dict[str, str]):
        self.server_url = server_url
        self.client_info = client_info
        self.session_id: str | None = None
        self.capabilities: dict[str, Any] = {}
        self.tools: dict[str, Any] = {}
        self.resources: dict[str, Any] = {}
        self.prompts: dict[str, Any] = {}
        self._request_id_counter = 0
        self._response_callbacks: dict[int, asyncio.Future] = {}
        self._notification_handlers: dict[str, list[Callable]] = {}

    async def connect(self) -> bool:
        """Establishes connection and initializes the MCP server."""
        logger.info(f"[MCP Client] Connecting to {self.server_url}...")
        try:
            # We assume HTTP transport for now
            response = await self._send_request(
                method="initialize",
                params={
                    "protocolVersion": "2025-06-18",  # Use the latest spec version
                    "capabilities": {
                        "elicitation": {},
                        "logging": {},
                    },
                    "clientInfo": self.client_info,
                },
            )

            if response and response.get("capabilities"):
                self.session_id = response.get("sessionId", "default")
                self.capabilities = response["capabilities"]
                logger.info(
                    f"[MCP Client] Connected to {self.server_url}. Session ID: {self.session_id}"
                )
                logger.debug(f"[MCP Client] Server capabilities: {self.capabilities}")
                await self.discover_all_primitives()
                return True
            logger.error(f"[MCP Client] Initialization failed: {response}")
            return False
        except Exception as exc:
            logger.error(f"[MCP Client] Error connecting: {exc}")
            return False

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """Sends a JSON-RPC request to the MCP server."""
        self._request_id_counter += 1
        request_id = self._request_id_counter

        request_payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        try:
            from apps.core.tools.web_tools import _assert_public_url

            await _assert_public_url(self.server_url)
            async with httpx.AsyncClient() as client:
                response = await client.post(self.server_url, json=request_payload, timeout=30)
                response.raise_for_status()
                response_json = response.json()

                if "result" in response_json:
                    return response_json["result"]
                if "error" in response_json:
                    logger.error("[MCP Client] Server error: %s", response_json["error"])
                    return None
                logger.warning(f"[MCP Client] Unexpected response: {response_json}")
                return None
        except httpx.HTTPStatusError as e:
            logger.error(f"[MCP Client] HTTP error {e.response.status_code}: {e.response.text}")
            return None
        except Exception as exc:
            logger.error(f"[MCP Client] Error sending request: {exc}")
            return None

    async def discover_all_primitives(self):
        """Discovers all available tools, resources, and prompts."""
        if self.capabilities.get("tools"):
            await self.list_tools()
        if self.capabilities.get("resources"):  # Assuming resources are also listed
            await self.list_resources()
        if self.capabilities.get("prompts"):  # Assuming prompts are also listed
            await self.list_prompts()

    async def list_tools(self) -> list[dict[str, Any]]:
        """Lists the tools available on the MCP server."""
        response = await self._send_request(method="tools/list", params={})
        if response and response.get("tools"):
            self.tools = {tool["name"]: tool for tool in response["tools"]}
            logger.info(f"[MCP Client] Discovered {len(self.tools)} tools.")
            return list(self.tools.values())
        return []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """Invokes a tool on the MCP server."""
        if tool_name not in self.tools:
            logger.warning(f"[MCP Client] Tool [33m{tool_name}[0m not found.")
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Tool {tool_name} not found."}],
            }

        logger.info(f"[MCP Client] Calling tool [32m{tool_name}[0m with arguments: {arguments}")
        response = await self._send_request(
            method="tools/call",
            params={
                "name": tool_name,
                "arguments": arguments,
            },
        )
        return response

    async def list_resources(self) -> list[dict[str, Any]]:
        """Lists the resources available on the MCP server."""
        response = await self._send_request(method="resources/list", params={})
        if response and response.get("resources"):
            self.resources = {res["uri"]: res for res in response["resources"]}
            logger.info(f"[MCP Client] Discovered {len(self.resources)} resources.")
            return list(self.resources.values())
        return []

    async def get_resource(self, uri: str) -> dict[str, Any] | None:
        """Gets the content of a resource from the MCP server."""
        response = await self._send_request(method="resources/get", params={"uri": uri})
        return response

    async def list_prompts(self) -> list[dict[str, Any]]:
        """Lists the prompts available on the MCP server."""
        response = await self._send_request(method="prompts/list", params={})
        if response and response.get("prompts"):
            self.prompts = {p["name"]: p for p in response["prompts"]}
            logger.info(f"[MCP Client] Discovered {len(self.prompts)} prompts.")
            return list(self.prompts.values())
        return []

    async def get_prompt(self, name: str) -> dict[str, Any] | None:
        """Gets a prompt from the MCP server."""
        response = await self._send_request(method="prompts/get", params={"name": name})
        return response

    def register_notification_handler(self, method: str, handler: Callable):
        """Registers a handler for MCP notifications."""
        if method not in self._notification_handlers:
            self._notification_handlers[method] = []
        self._notification_handlers[method].append(handler)

    async def _handle_notification(self, notification: dict[str, Any]):
        """Handles incoming notifications."""
        method = notification.get("method")
        if method and method in self._notification_handlers:
            for handler in self._notification_handlers[method]:
                await handler(notification.get("params", {}))
        else:
            logger.warning(f"[MCP Client] Unhandled notification: {notification}")

    async def shutdown(self):
        """Closes the connection with the MCP server."""
        logger.info(f"[MCP Client] Disconnecting from {self.server_url}...")
        try:
            await self._send_request(method="shutdown", params={})
        except Exception as exc:
            logger.warning(f"[MCP Client] Error sending shutdown: {exc}")


class McpManager:
    """Manages multiple MCP clients."""

    def __init__(self):
        self.clients: dict[str, McpClient] = {}

    async def add_server(
        self, server_name: str, server_url: str, client_info: dict[str, str]
    ) -> McpClient | None:
        """Adds and connects a new MCP server."""
        client = McpClient(server_url, client_info)
        if await client.connect():
            self.clients[server_name] = client
            return client
        return None

    def get_client(self, server_name: str) -> McpClient | None:
        """Gets an MCP client by name."""
        return self.clients.get(server_name)

    async def call_tool_on_server(
        self, server_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Calls a tool on a specific MCP server."""
        client = self.get_client(server_name)
        if client:
            return await client.call_tool(tool_name, arguments)
        logger.error(f"[MCP Manager] MCP server [31m{server_name}[0m not found.")
        return None

    async def shutdown_all(self):
        """Closes all MCP clients."""
        for client in self.clients.values():
            await client.shutdown()
        self.clients.clear()


mcp_manager = McpManager()
