"""
mcp_agent.py — MCP (Model Context Protocol) Client for ARIA.

Turns ARIA into an **MCP Client** using the official Anthropic SDK
(`anthropic`) and the official MCP SDK (`mcp`). It allows ARIA to:

  1. Connect to external MCP servers via STDIO (local) or SSE / HTTP (remote).
  2. Run the "Protocol Initialization" phase and dynamically list the
     tools each server exposes.
  3. Map each MCP tool's JSON Schema to the *function
     calling* format Claude expects (`{name, description, input_schema}`).
  4. Run the agentic loop: when Claude requests a tool, ARIA
     executes it on the MCP server and returns the result to the model.

Design:
  - `MCPServerConfig`   → describes a server (transport + parameters).
  - `MCPConnection`     → a live MCP session (initialize + list_tools + call_tool).
  - `MCPAgent`          → aggregates tools from N servers and runs the
                          function calling loop against Claude.

The Anthropic SDK is always used through `AsyncAnthropic` — never raw HTTP —
in accordance with the official Claude API guide.
"""

from __future__ import annotations

import logging
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger("aria.mcp_agent")

# Default model: Anthropic's most capable (see the claude-api guide).
DEFAULT_MODEL = "claude-opus-4-8"

DEFAULT_SYSTEM = (
    "You are ARIA, an autonomous AI that solves tasks using the tools "
    "available via MCP. When a tool can answer better than your "
    "internal knowledge, use it. Briefly explain what you did when finished."
)

# Anthropic requires tool names matching ^[a-zA-Z0-9_-]{1,64}$
_TOOL_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")


# ──────────────────────────────────────────────────────────────────────────
# MCP server configuration
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class MCPServerConfig:
    """Describes how to connect to an MCP server.

    STDIO (local servers — preferred):
        MCPServerConfig(name="mem", transport="stdio",
                        command="python3", args=["server.py"])

    SSE / HTTP (remote servers):
        MCPServerConfig(name="remote", transport="sse",
                        url="https://host/sse", headers={"Authorization": "..."})
    """

    name: str
    transport: Literal["stdio", "sse", "http"] = "stdio"
    # STDIO
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    # SSE / HTTP
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if self.transport == "stdio":
            if not self.command:
                raise ValueError(f"[{self.name}] stdio transport requires 'command'")
        elif self.transport in ("sse", "http"):
            if not self.url:
                raise ValueError(f"[{self.name}] {self.transport} transport requires 'url'")
        else:
            raise ValueError(f"[{self.name}] unsupported transport: {self.transport}")


def _sanitize_tool_name(server: str, tool: str) -> str:
    """Unique, valid name for Anthropic: `server__tool`, <=64 chars."""
    raw = f"{server}__{tool}"
    safe = _TOOL_NAME_RE.sub("_", raw)
    return safe[:64]


# ──────────────────────────────────────────────────────────────────────────
# A live MCP connection
# ──────────────────────────────────────────────────────────────────────────
class MCPConnection:
    """Wraps an MCP session (ClientSession) keeping the transport alive."""

    def __init__(self, config: MCPServerConfig):
        config.validate()
        self.config = config
        self._stack = AsyncExitStack()
        self._session: Any = None  # mcp.ClientSession
        self.tools: list[Any] = []  # list of mcp.types.Tool

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def connect(self) -> list[Any]:
        """Opens the transport, runs the `initialize` handshake, and lists tools."""
        from mcp import ClientSession

        cfg = self.config
        logger.info("[MCP:%s] Connecting via %s...", cfg.name, cfg.transport)

        if cfg.transport == "stdio":
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env)
            read, write = await self._stack.enter_async_context(stdio_client(params))
        elif cfg.transport == "sse":
            from mcp.client.sse import sse_client

            read, write = await self._stack.enter_async_context(
                sse_client(url=cfg.url, headers=cfg.headers or None)
            )
        else:  # http (Streamable HTTP)
            from mcp.client.streamable_http import streamablehttp_client

            read, write, _ = await self._stack.enter_async_context(
                streamablehttp_client(url=cfg.url, headers=cfg.headers or None)
            )

        session = await self._stack.enter_async_context(ClientSession(read, write))
        # Protocol Initialization — MCP handshake.
        init = await session.initialize()
        self._session = session

        server_name = getattr(getattr(init, "serverInfo", None), "name", cfg.name)
        logger.info("[MCP:%s] Initialized (server: %s)", cfg.name, server_name)

        # Dynamic tool discovery.
        listed = await session.list_tools()
        self.tools = list(listed.tools)
        logger.info(
            "[MCP:%s] %d tools discovered: %s",
            cfg.name,
            len(self.tools),
            ", ".join(t.name for t in self.tools) or "(none)",
        )
        return self.tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Invokes a tool on the MCP server. Returns CallToolResult."""
        if not self._session:
            raise RuntimeError(f"[MCP:{self.name}] not connected")
        logger.info("[MCP:%s] call_tool %s(%s)", self.name, tool_name, arguments)
        return await self._session.call_tool(tool_name, arguments or {})

    async def aclose(self) -> None:
        await self._stack.aclose()
        self._session = None


# ──────────────────────────────────────────────────────────────────────────
# MCP schema → Anthropic tool mapping (function calling)
# ──────────────────────────────────────────────────────────────────────────
def mcp_tool_to_anthropic(tool: Any, *, override_name: str | None = None) -> dict[str, Any]:
    """Converts an MCP tool into the definition Claude expects.

    MCP exposes: tool.name, tool.description, tool.inputSchema (JSON Schema).
    Anthropic expects: {"name", "description", "input_schema"} where
    input_schema is an object-type JSON Schema.
    """
    schema = getattr(tool, "inputSchema", None) or {"type": "object", "properties": {}}
    # Anthropic requires an object schema; normalize if missing.
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    if schema.get("type") != "object":
        schema = {"type": "object", "properties": schema.get("properties", {})}
    schema.setdefault("properties", {})

    return {
        "name": override_name or tool.name,
        "description": getattr(tool, "description", None) or f"MCP tool {tool.name}",
        "input_schema": schema,
    }


def _result_to_text(result: Any) -> tuple[str, bool]:
    """Flattens an MCP CallToolResult into text for Anthropic's tool_result."""
    is_error = bool(getattr(result, "isError", False))
    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        btype = getattr(block, "type", None)
        if btype == "text":
            parts.append(getattr(block, "text", ""))
        elif btype == "resource":
            res = getattr(block, "resource", None)
            text = getattr(res, "text", None)
            parts.append(text if text is not None else str(res))
        else:
            parts.append(str(block))
    text = "\n".join(p for p in parts if p) or ("(no content)" if not is_error else "error")
    return text, is_error


# ──────────────────────────────────────────────────────────────────────────
# Agent: N MCP connections + function calling loop with Claude
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class MCPToolResult:
    tool: str
    arguments: dict[str, Any]
    output: str
    is_error: bool


@dataclass
class MCPAgentResult:
    text: str
    tool_calls: list[MCPToolResult]
    stop_reason: str | None
    turns: int


class MCPAgent:
    """MCP client + function calling bridge to Claude.

    Usage:
        agent = MCPAgent([MCPServerConfig(name="mem", command="python3",
                                          args=["server.py"])])
        async with agent:
            result = await agent.run("Save that my name is Geremy and retrieve it.")
            print(result.text)
    """

    def __init__(
        self,
        servers: list[MCPServerConfig],
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        system: str = DEFAULT_SYSTEM,
    ):
        self.servers = servers
        self.model = model
        self.system = system
        self._api_key = api_key
        self._connections: list[MCPConnection] = []
        # anthropic_name -> (connection, real_mcp_name)
        self._routing: dict[str, tuple[MCPConnection, str]] = {}
        self._anthropic: Any = None

    # ── lifecycle ─────────────────────────────────────────────
    async def __aenter__(self) -> MCPAgent:
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def connect(self) -> None:
        """Connects to all servers and builds the routing table."""
        for cfg in self.servers:
            conn = MCPConnection(cfg)
            await conn.connect()
            self._connections.append(conn)
            for tool in conn.tools:
                anth_name = _sanitize_tool_name(cfg.name, tool.name)
                self._routing[anth_name] = (conn, tool.name)

    async def aclose(self) -> None:
        for conn in reversed(self._connections):
            try:
                await conn.aclose()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[MCP:%s] error closing: %s", conn.name, exc)
        self._connections.clear()
        self._routing.clear()

    # ── tools exposed to Claude ──────────────────────────
    def anthropic_tools(self) -> list[dict[str, Any]]:
        """All MCP tools mapped to Claude's format."""
        tools: list[dict[str, Any]] = []
        for anth_name, (conn, real) in self._routing.items():
            tool = next((t for t in conn.tools if t.name == real), None)
            if tool is not None:
                tools.append(mcp_tool_to_anthropic(tool, override_name=anth_name))
        return tools

    async def _dispatch_tool(self, anth_name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        route = self._routing.get(anth_name)
        if route is None:
            return f"Unknown tool: {anth_name}", True
        conn, real = route
        try:
            result = await conn.call_tool(real, arguments)
            return _result_to_text(result)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[MCP] failed executing %s: %s", anth_name, exc)
            return f"Error executing {anth_name}: {exc}", True

    def _client(self) -> Any:
        if self._anthropic is None:
            from anthropic import AsyncAnthropic

            self._anthropic = AsyncAnthropic(api_key=self._api_key)
        return self._anthropic

    # ── agentic function calling loop ───────────────────────
    async def run(
        self,
        user_message: str,
        *,
        max_tokens: int = 4096,
        max_turns: int = 8,
    ) -> MCPAgentResult:
        """Runs the loop: Claude ↔ MCP tools until Claude finishes."""
        client = self._client()
        tools = self.anthropic_tools()
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
        collected: list[MCPToolResult] = []
        stop_reason: str | None = None

        for turn in range(1, max_turns + 1):
            response = await client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=self.system,
                tools=tools,
                messages=messages,
            )
            stop_reason = response.stop_reason

            if response.stop_reason != "tool_use":
                text = "".join(
                    b.text for b in response.content if getattr(b, "type", None) == "text"
                )
                return MCPAgentResult(
                    text=text.strip(),
                    tool_calls=collected,
                    stop_reason=stop_reason,
                    turns=turn,
                )

            # Preserve the assistant's turn (includes the tool_use blocks).
            messages.append({"role": "assistant", "content": response.content})

            tool_result_blocks: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                output, is_error = await self._dispatch_tool(block.name, block.input or {})
                collected.append(
                    MCPToolResult(
                        tool=block.name,
                        arguments=block.input or {},
                        output=output,
                        is_error=is_error,
                    )
                )
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                        "is_error": is_error,
                    }
                )

            messages.append({"role": "user", "content": tool_result_blocks})

        return MCPAgentResult(
            text="(turn limit reached without a final response)",
            tool_calls=collected,
            stop_reason=stop_reason,
            turns=max_turns,
        )
