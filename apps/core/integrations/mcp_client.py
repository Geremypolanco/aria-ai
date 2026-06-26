"""
mcp_client.py — Cliente del Protocolo de Contexto del Modelo (MCP) para ARIA.

Este cliente permite a ARIA conectarse e interactuar con cualquier servidor MCP,
extendiendo dinámicamente sus capacidades con nuevas herramientas, recursos y prompts.
"""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    import asyncio

logger = logging.getLogger("aria.mcp_client")


class McpClient:
    """Cliente MCP para interactuar con servidores que implementan el Model Context Protocol."""

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
        """Establece conexión e inicializa el servidor MCP."""
        logger.info(f"[MCP Client] Conectando a {self.server_url}...")
        try:
            # Asumimos transporte HTTP por ahora
            response = await self._send_request(
                method="initialize",
                params={
                    "protocolVersion": "2025-06-18",  # Usar la versión más reciente de la especificación
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
                    f"[MCP Client] Conectado a {self.server_url}. Session ID: {self.session_id}"
                )
                logger.debug(f"[MCP Client] Capacidades del servidor: {self.capabilities}")
                await self.discover_all_primitives()
                return True
            logger.error(f"[MCP Client] Fallo en inicialización: {response}")
            return False
        except Exception as exc:
            logger.error(f"[MCP Client] Error al conectar: {exc}")
            return False

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """Envía una solicitud JSON-RPC al servidor MCP."""
        self._request_id_counter += 1
        request_id = self._request_id_counter

        request_payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.server_url, json=request_payload, timeout=30)
                response.raise_for_status()
                response_json = response.json()

                if "result" in response_json:
                    return response_json["result"]
                if "error" in response_json:
                    logger.error("[MCP Client] Error del servidor: %s", response_json["error"])
                    return None
                logger.warning(f"[MCP Client] Respuesta inesperada: {response_json}")
                return None
        except httpx.HTTPStatusError as e:
            logger.error(f"[MCP Client] Error HTTP {e.response.status_code}: {e.response.text}")
            return None
        except Exception as exc:
            logger.error(f"[MCP Client] Error enviando solicitud: {exc}")
            return None

    async def discover_all_primitives(self):
        """Descubre todas las herramientas, recursos y prompts disponibles."""
        if self.capabilities.get("tools"):
            await self.list_tools()
        if self.capabilities.get("resources"):  # Asumiendo que los recursos también se listan
            await self.list_resources()
        if self.capabilities.get("prompts"):  # Asumiendo que los prompts también se listan
            await self.list_prompts()

    async def list_tools(self) -> list[dict[str, Any]]:
        """Lista las herramientas disponibles en el servidor MCP."""
        response = await self._send_request(method="tools/list", params={})
        if response and response.get("tools"):
            self.tools = {tool["name"]: tool for tool in response["tools"]}
            logger.info(f"[MCP Client] Descubiertas {len(self.tools)} herramientas.")
            return list(self.tools.values())
        return []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """Invoca una herramienta en el servidor MCP."""
        if tool_name not in self.tools:
            logger.warning(f"[MCP Client] Herramienta [33m{tool_name}[0m no encontrada.")
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Herramienta {tool_name} no encontrada."}],
            }

        logger.info(
            f"[MCP Client] Llamando herramienta [32m{tool_name}[0m con argumentos: {arguments}"
        )
        response = await self._send_request(
            method="tools/call",
            params={
                "name": tool_name,
                "arguments": arguments,
            },
        )
        return response

    async def list_resources(self) -> list[dict[str, Any]]:
        """Lista los recursos disponibles en el servidor MCP."""
        response = await self._send_request(method="resources/list", params={})
        if response and response.get("resources"):
            self.resources = {res["uri"]: res for res in response["resources"]}
            logger.info(f"[MCP Client] Descubiertos {len(self.resources)} recursos.")
            return list(self.resources.values())
        return []

    async def get_resource(self, uri: str) -> dict[str, Any] | None:
        """Obtiene el contenido de un recurso del servidor MCP."""
        response = await self._send_request(method="resources/get", params={"uri": uri})
        return response

    async def list_prompts(self) -> list[dict[str, Any]]:
        """Lista los prompts disponibles en el servidor MCP."""
        response = await self._send_request(method="prompts/list", params={})
        if response and response.get("prompts"):
            self.prompts = {p["name"]: p for p in response["prompts"]}
            logger.info(f"[MCP Client] Descubiertos {len(self.prompts)} prompts.")
            return list(self.prompts.values())
        return []

    async def get_prompt(self, name: str) -> dict[str, Any] | None:
        """Obtiene un prompt del servidor MCP."""
        response = await self._send_request(method="prompts/get", params={"name": name})
        return response

    def register_notification_handler(self, method: str, handler: Callable):
        """Registra un handler para notificaciones MCP."""
        if method not in self._notification_handlers:
            self._notification_handlers[method] = []
        self._notification_handlers[method].append(handler)

    async def _handle_notification(self, notification: dict[str, Any]):
        """Maneja notificaciones entrantes."""
        method = notification.get("method")
        if method and method in self._notification_handlers:
            for handler in self._notification_handlers[method]:
                await handler(notification.get("params", {}))
        else:
            logger.warning(f"[MCP Client] Notificación no manejada: {notification}")

    async def shutdown(self):
        """Cierra la conexión con el servidor MCP."""
        logger.info(f"[MCP Client] Desconectando de {self.server_url}...")
        try:
            await self._send_request(method="shutdown", params={})
        except Exception as exc:
            logger.warning(f"[MCP Client] Error al enviar shutdown: {exc}")


class McpManager:
    """Gestiona múltiples clientes MCP."""

    def __init__(self):
        self.clients: dict[str, McpClient] = {}

    async def add_server(
        self, server_name: str, server_url: str, client_info: dict[str, str]
    ) -> McpClient | None:
        """Añade y conecta un nuevo servidor MCP."""
        client = McpClient(server_url, client_info)
        if await client.connect():
            self.clients[server_name] = client
            return client
        return None

    def get_client(self, server_name: str) -> McpClient | None:
        """Obtiene un cliente MCP por nombre."""
        return self.clients.get(server_name)

    async def call_tool_on_server(
        self, server_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Llama a una herramienta en un servidor MCP específico."""
        client = self.get_client(server_name)
        if client:
            return await client.call_tool(tool_name, arguments)
        logger.error(f"[MCP Manager] Servidor MCP [31m{server_name}[0m no encontrado.")
        return None

    async def shutdown_all(self):
        """Cierra todos los clientes MCP."""
        for client in self.clients.values():
            await client.shutdown()
        self.clients.clear()


mcp_manager = McpManager()
