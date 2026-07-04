"""
ARIA Agent System — Tool Registry.
Registro central de herramientas con metadatos, validación de parámetros,
y enrutamiento a implementaciones concretas.

Cada herramienta tiene:
  - name: nombre único
  - description: descripción para el agente
  - params_schema: schema de parámetros
  - execute_fn: función asíncrona de ejecución
  - timeout_seconds: timeout por defecto
  - requires_sandbox: si necesita contenedor Docker
  - requires_browser: si necesita Playwright
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine

from core.vault.client import VaultClient
from sandbox.manager import SandboxManager

logger = logging.getLogger("aria.tools.registry")


class ToolDefinition:
    """Definición de una herramienta registrada."""

    def __init__(
        self,
        name: str,
        description: str,
        params_schema: dict[str, Any],
        execute_fn: Callable[..., Coroutine[Any, Any, dict[str, Any]]],
        timeout_seconds: int = 30,
        requires_sandbox: bool = False,
        requires_browser: bool = False,
        requires_vault: bool = False,
        category: str = "general",
    ):
        self.name = name
        self.description = description
        self.params_schema = params_schema
        self.execute_fn = execute_fn
        self.timeout_seconds = timeout_seconds
        self.requires_sandbox = requires_sandbox
        self.requires_browser = requires_browser
        self.requires_vault = requires_vault
        self.category = category

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "params_schema": self.params_schema,
            "timeout_seconds": self.timeout_seconds,
            "requires_sandbox": self.requires_sandbox,
            "requires_browser": self.requires_browser,
            "requires_vault": self.requires_vault,
            "category": self.category,
        }


class ToolRegistry:
    """
    Registro central que gestiona todas las herramientas disponibles.

    - Registrar herramientas
    - Ejecutar herramientas con manejo de timeout y errores
    - Validar parámetros contra schema
    - Inyectar dependencias (sandbox, vault, browser)
    """

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._sandbox: SandboxManager | None = None
        self._vault: VaultClient | None = None
        self._browser_url: str | None = None

    async def initialize(
        self,
        sandbox: SandboxManager | None = None,
        vault: VaultClient | None = None,
        browser_url: str | None = None,
    ) -> None:
        """Configura las dependencias compartidas."""
        self._sandbox = sandbox
        self._vault = vault
        self._browser_url = browser_url
        self._register_all()

    def _register_all(self) -> None:
        """Registra todas las herramientas disponibles."""
        self._tools.clear()

        # ── Terminal ──
        self.register(ToolDefinition(
            name="terminal_run",
            description="Ejecuta un comando en un sandbox Docker aislado. "
                        "Útil para scripts, instalaciones, scraping, análisis de datos.",
            params_schema={
                "command": {
                    "type": "string",
                    "description": "Comando bash a ejecutar",
                    "required": True,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout en segundos",
                    "default": 60,
                    "required": False,
                },
                "workdir": {
                    "type": "string",
                    "description": "Directorio de trabajo",
                    "default": "/sandbox",
                    "required": False,
                },
            },
            execute_fn=self._exec_terminal_run,
            timeout_seconds=120,
            requires_sandbox=True,
            category="execution",
        ))

        # ── Browser Navigation ──
        self.register(ToolDefinition(
            name="browser_navigate",
            description="Navega a una URL en el navegador headless. "
                        "Carga la página y espera a que esté lista.",
            params_schema={
                "url": {
                    "type": "string",
                    "description": "URL completa a navegar",
                    "required": True,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout de carga en segundos",
                    "default": 30,
                    "required": False,
                },
            },
            execute_fn=self._exec_browser_navigate,
            timeout_seconds=60,
            requires_browser=True,
            category="browser",
        ))

        # ── Browser Click ──
        self.register(ToolDefinition(
            name="browser_click",
            description="Hace click en un elemento de la página usando un selector CSS.",
            params_schema={
                "selector": {
                    "type": "string",
                    "description": "Selector CSS del elemento a clickear",
                    "required": True,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout en segundos",
                    "default": 15,
                    "required": False,
                },
            },
            execute_fn=self._exec_browser_click,
            timeout_seconds=30,
            requires_browser=True,
            category="browser",
        ))

        # ── Browser Extract ──
        self.register(ToolDefinition(
            name="browser_extract",
            description="Extrae datos de la página actual usando selectores CSS. "
                        "Soporta formatos: text, json, table, markdown.",
            params_schema={
                "selectors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de selectores CSS a extraer",
                    "required": True,
                },
                "format": {
                    "type": "string",
                    "description": "Formato de salida: text, json, table, markdown",
                    "default": "text",
                    "required": False,
                },
                "schema": {
                    "type": "object",
                    "description": "Schema de extracción estructurada (opcional)",
                    "required": False,
                },
            },
            execute_fn=self._exec_browser_extract,
            timeout_seconds=30,
            requires_browser=True,
            category="browser",
        ))

        # ── Secrets Get ──
        self.register(ToolDefinition(
            name="secrets_get",
            description="Obtiene un secreto de Vault. "
                        "Usar para API keys, tokens, contraseñas y config sensible.",
            params_schema={
                "path": {
                    "type": "string",
                    "description": "Ruta del secreto (ej: agents/shopify)",
                    "required": True,
                },
                "key": {
                    "type": "string",
                    "description": "Clave específica (opcional, si no se provee lista las claves)",
                    "required": False,
                },
            },
            execute_fn=self._exec_secrets_get,
            timeout_seconds=10,
            requires_vault=True,
            category="secrets",
        ))

        # ── Secrets Set ──
        self.register(ToolDefinition(
            name="secrets_set",
            description="Guarda un secreto en Vault. "
                        "Usar para almacenar API keys, tokens y config sensible de forma segura.",
            params_schema={
                "path": {
                    "type": "string",
                    "description": "Ruta del secreto",
                    "required": True,
                },
                "data": {
                    "type": "object",
                    "description": "Datos a guardar (key: value)",
                    "required": True,
                },
            },
            execute_fn=self._exec_secrets_set,
            timeout_seconds=10,
            requires_vault=True,
            category="secrets",
        ))

        logger.info("ToolRegistry: %d herramientas registradas", len(self._tools))

    def register(self, tool_def: ToolDefinition) -> None:
        """Registra una herramienta."""
        self._tools[tool_def.name] = tool_def

    def get(self, name: str) -> ToolDefinition | None:
        """Obtiene una herramienta por nombre."""
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        """Lista todas las herramientas registradas."""
        return [t.to_dict() for t in self._tools.values()]

    def list_by_category(self, category: str) -> list[dict[str, Any]]:
        """Lista herramientas de una categoría."""
        return [
            t.to_dict()
            for t in self._tools.values()
            if t.category == category
        ]

    # ── Ejecución ─────────────────────────────────────────

    async def execute(
        self,
        tool_name: str,
        params: dict[str, Any],
        task_id: str | None = None,
        session_id: str = "default",
    ) -> dict[str, Any]:
        """
        Ejecuta una herramienta por nombre.

        Valida parámetros, inyecta dependencias, maneja timeout y errores.
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return {
                "success": False,
                "error": f"Herramienta '{tool_name}' no encontrada",
                "available_tools": list(self._tools.keys()),
            }

        # Validar parámetros requeridos
        validation_error = self._validate_params(tool, params)
        if validation_error:
            return {
                "success": False,
                "error": validation_error,
                "tool": tool_name,
            }

        start = time.time()

        try:
            # Ejecutar con timeout
            result = await asyncio.wait_for(
                self._execute_with_deps(tool, params, task_id, session_id),
                timeout=tool.timeout_seconds,
            )

            duration_ms = int((time.time() - start) * 1000)
            result["duration_ms"] = duration_ms
            result["tool"] = tool_name

            logger.debug(
                "ToolRegistry: %s ejecutado en %dms",
                tool_name,
                duration_ms,
            )
            return result

        except asyncio.TimeoutError:
            logger.error("ToolRegistry: timeout en %s (%ds)", tool_name, tool.timeout_seconds)
            return {
                "success": False,
                "error": f"Timeout: {tool_name} excedió {tool.timeout_seconds}s",
                "tool": tool_name,
                "duration_ms": tool.timeout_seconds * 1000,
            }
        except Exception as e:
            logger.error("ToolRegistry: error en %s: %s", tool_name, e, exc_info=True)
            return {
                "success": False,
                "error": str(e)[:500],
                "tool": tool_name,
                "duration_ms": int((time.time() - start) * 1000),
            }

    async def _execute_with_deps(
        self,
        tool: ToolDefinition,
        params: dict[str, Any],
        task_id: str | None,
        session_id: str,
    ) -> dict[str, Any]:
        """
        Ejecuta la herramienta inyectando las dependencias necesarias.
        """
        kwargs: dict[str, Any] = {}

        if tool.requires_sandbox:
            if not self._sandbox:
                return {"success": False, "error": "Sandbox no disponible"}
            kwargs["sandbox"] = self._sandbox
            kwargs["task_id"] = task_id or "unknown"

        if tool.requires_browser:
            if not self._browser_url:
                return {"success": False, "error": "Browser no disponible"}
            kwargs["browser_url"] = self._browser_url
            kwargs["session_id"] = session_id

        if tool.requires_vault:
            if not self._vault:
                return {"success": False, "error": "Vault no disponible"}
            kwargs["vault"] = self._vault
            kwargs["task_id"] = task_id

        # Las herramientas de browser toman params como segundo argumento
        if tool.requires_browser:
            kwargs["params"] = params
        else:
            kwargs["params"] = params

        return await tool.execute_fn(**kwargs)

    def _validate_params(
        self,
        tool: ToolDefinition,
        params: dict[str, Any],
    ) -> str | None:
        """
        Valida que los parámetros requeridos estén presentes.
        """
        schema = tool.params_schema
        for param_name, param_config in schema.items():
            if param_config.get("required", False):
                if param_name not in params or params[param_name] is None:
                    return f"Parámetro requerido '{param_name}' no especificado para {tool.name}"
        return None

    # ── Handlers de herramientas ──────────────────────────

    async def _exec_terminal_run(
        self,
        sandbox: SandboxManager,
        task_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        from tools.terminal_run import execute
        return await execute(sandbox, task_id, params)

    async def _exec_browser_navigate(
        self,
        browser_url: str,
        params: dict[str, Any],
        session_id: str,
    ) -> dict[str, Any]:
        from tools.browser_navigate import execute
        return await execute(browser_url, params, session_id)

    async def _exec_browser_click(
        self,
        browser_url: str,
        params: dict[str, Any],
        session_id: str,
    ) -> dict[str, Any]:
        from tools.browser_click import execute
        return await execute(browser_url, params, session_id)

    async def _exec_browser_extract(
        self,
        browser_url: str,
        params: dict[str, Any],
        session_id: str,
    ) -> dict[str, Any]:
        from tools.browser_extract import execute
        return await execute(browser_url, params, session_id)

    async def _exec_secrets_get(
        self,
        vault: VaultClient,
        params: dict[str, Any],
        task_id: str,
    ) -> dict[str, Any]:
        from tools.secrets_get import execute
        return await execute(vault, params, task_id)

    async def _exec_secrets_set(
        self,
        vault: VaultClient,
        params: dict[str, Any],
        task_id: str,
    ) -> dict[str, Any]:
        from tools.secrets_set import execute
        return await execute(vault, params, task_id)
