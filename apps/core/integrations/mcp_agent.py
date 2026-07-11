"""
mcp_agent.py — Cliente MCP (Model Context Protocol) para ARIA.

Convierte a ARIA en un **Cliente MCP** usando el SDK oficial de Anthropic
(`anthropic`) y el SDK oficial de MCP (`mcp`). Permite que ARIA:

  1. Se conecte a servidores MCP externos por STDIO (local) o SSE / HTTP (remoto).
  2. Ejecute la fase de "Protocol Initialization" y liste dinámicamente las
     herramientas que expone cada servidor.
  3. Mapee el JSON Schema de cada herramienta MCP al formato de *function
     calling* que espera Claude (`{name, description, input_schema}`).
  4. Corra el bucle agéntico: cuando Claude pide una herramienta, ARIA la
     ejecuta en el servidor MCP y devuelve el resultado al modelo.

Diseño:
  - `MCPServerConfig`   → describe un servidor (transporte + parámetros).
  - `MCPConnection`     → una sesión MCP viva (initialize + list_tools + call_tool).
  - `MCPAgent`          → agrega herramientas de N servidores y ejecuta el loop
                          de function calling contra Claude.

El SDK de Anthropic se usa siempre a través de `AsyncAnthropic` — nunca por HTTP
crudo — de acuerdo con la guía oficial de la API de Claude.
"""

from __future__ import annotations

import logging
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger("aria.mcp_agent")

# Modelo por defecto: el más capaz de Anthropic (ver guía claude-api).
DEFAULT_MODEL = "claude-opus-4-8"

DEFAULT_SYSTEM = (
    "Eres ARIA, una IA autónoma que resuelve tareas usando las herramientas "
    "disponibles vía MCP. Cuando una herramienta pueda responder mejor que tu "
    "conocimiento interno, úsala. Explica brevemente qué hiciste al terminar."
)

# Anthropic exige nombres de herramienta que casen con ^[a-zA-Z0-9_-]{1,64}$
_TOOL_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")


# ──────────────────────────────────────────────────────────────────────────
# Configuración de un servidor MCP
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class MCPServerConfig:
    """Describe cómo conectarse a un servidor MCP.

    STDIO (servidores locales — prioritario):
        MCPServerConfig(name="mem", transport="stdio",
                        command="python3", args=["server.py"])

    SSE / HTTP (servidores remotos):
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
                raise ValueError(f"[{self.name}] transporte stdio requiere 'command'")
        elif self.transport in ("sse", "http"):
            if not self.url:
                raise ValueError(f"[{self.name}] transporte {self.transport} requiere 'url'")
        else:
            raise ValueError(f"[{self.name}] transporte no soportado: {self.transport}")


def _sanitize_tool_name(server: str, tool: str) -> str:
    """Nombre único y válido para Anthropic: `server__tool`, <=64 chars."""
    raw = f"{server}__{tool}"
    safe = _TOOL_NAME_RE.sub("_", raw)
    return safe[:64]


# ──────────────────────────────────────────────────────────────────────────
# Una conexión MCP viva
# ──────────────────────────────────────────────────────────────────────────
class MCPConnection:
    """Envuelve una sesión MCP (ClientSession) manteniendo vivo el transporte."""

    def __init__(self, config: MCPServerConfig):
        config.validate()
        self.config = config
        self._stack = AsyncExitStack()
        self._session: Any = None  # mcp.ClientSession
        self.tools: list[Any] = []  # lista de mcp.types.Tool

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def connect(self) -> list[Any]:
        """Abre el transporte, ejecuta el handshake `initialize` y lista tools."""
        from mcp import ClientSession

        cfg = self.config
        logger.info("[MCP:%s] Conectando vía %s...", cfg.name, cfg.transport)

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
        # Protocol Initialization — handshake MCP.
        init = await session.initialize()
        self._session = session

        server_name = getattr(getattr(init, "serverInfo", None), "name", cfg.name)
        logger.info("[MCP:%s] Inicializado (servidor: %s)", cfg.name, server_name)

        # Descubrimiento dinámico de herramientas.
        listed = await session.list_tools()
        self.tools = list(listed.tools)
        logger.info(
            "[MCP:%s] %d herramientas descubiertas: %s",
            cfg.name,
            len(self.tools),
            ", ".join(t.name for t in self.tools) or "(ninguna)",
        )
        return self.tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Invoca una herramienta en el servidor MCP. Devuelve CallToolResult."""
        if not self._session:
            raise RuntimeError(f"[MCP:{self.name}] no conectado")
        logger.info("[MCP:%s] call_tool %s(%s)", self.name, tool_name, arguments)
        return await self._session.call_tool(tool_name, arguments or {})

    async def aclose(self) -> None:
        await self._stack.aclose()
        self._session = None


# ──────────────────────────────────────────────────────────────────────────
# Mapeo de esquema MCP → herramienta Anthropic (function calling)
# ──────────────────────────────────────────────────────────────────────────
def mcp_tool_to_anthropic(tool: Any, *, override_name: str | None = None) -> dict[str, Any]:
    """Convierte una herramienta MCP en la definición que espera Claude.

    MCP expone: tool.name, tool.description, tool.inputSchema (JSON Schema).
    Anthropic espera: {"name", "description", "input_schema"} donde
    input_schema es un JSON Schema de tipo objeto.
    """
    schema = getattr(tool, "inputSchema", None) or {"type": "object", "properties": {}}
    # Anthropic requiere un schema de objeto; normalizamos si falta.
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
    """Aplana un CallToolResult de MCP a texto para el tool_result de Anthropic."""
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
    text = "\n".join(p for p in parts if p) or ("(sin contenido)" if not is_error else "error")
    return text, is_error


# ──────────────────────────────────────────────────────────────────────────
# Agente: N conexiones MCP + bucle de function calling con Claude
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
    """Cliente MCP + puente de function calling hacia Claude.

    Uso:
        agent = MCPAgent([MCPServerConfig(name="mem", command="python3",
                                          args=["server.py"])])
        async with agent:
            result = await agent.run("Guarda que me llamo Geremy y recupéralo.")
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
        # nombre_anthropic -> (conexión, nombre_real_mcp)
        self._routing: dict[str, tuple[MCPConnection, str]] = {}
        self._anthropic: Any = None

    # ── ciclo de vida ─────────────────────────────────────────────
    async def __aenter__(self) -> MCPAgent:
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def connect(self) -> None:
        """Conecta a todos los servidores y construye la tabla de ruteo."""
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
                logger.warning("[MCP:%s] error al cerrar: %s", conn.name, exc)
        self._connections.clear()
        self._routing.clear()

    # ── herramientas expuestas a Claude ──────────────────────────
    def anthropic_tools(self) -> list[dict[str, Any]]:
        """Todas las herramientas MCP mapeadas al formato de Claude."""
        tools: list[dict[str, Any]] = []
        for anth_name, (conn, real) in self._routing.items():
            tool = next((t for t in conn.tools if t.name == real), None)
            if tool is not None:
                tools.append(mcp_tool_to_anthropic(tool, override_name=anth_name))
        return tools

    async def _dispatch_tool(self, anth_name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        route = self._routing.get(anth_name)
        if route is None:
            return f"Herramienta desconocida: {anth_name}", True
        conn, real = route
        try:
            result = await conn.call_tool(real, arguments)
            return _result_to_text(result)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[MCP] fallo ejecutando %s: %s", anth_name, exc)
            return f"Error ejecutando {anth_name}: {exc}", True

    def _client(self) -> Any:
        if self._anthropic is None:
            from anthropic import AsyncAnthropic

            self._anthropic = AsyncAnthropic(api_key=self._api_key)
        return self._anthropic

    # ── bucle agéntico de function calling ───────────────────────
    async def run(
        self,
        user_message: str,
        *,
        max_tokens: int = 4096,
        max_turns: int = 8,
    ) -> MCPAgentResult:
        """Corre el loop: Claude ↔ herramientas MCP hasta que Claude termina."""
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

            # Preservamos el turno del asistente (incluye los bloques tool_use).
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
            text="(límite de turnos alcanzado sin respuesta final)",
            tool_calls=collected,
            stop_reason=stop_reason,
            turns=max_turns,
        )
