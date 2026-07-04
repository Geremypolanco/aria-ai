"""
ARIA Agent System — Browser Manager.
Gestiona instancias de Playwright/Chromium en contenedor Docker aislado.

Cada sesión de navegador tiene:
- Perfil persistente (cookies, localStorage, sesiones)
- Chromium headless con sandbox
- Timeout configurable
- Aislamiento total entre sesiones
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

import docker
from docker.errors import DockerException, NotFound

from core.config.settings import settings

logger = logging.getLogger("aria.browser")


class BrowserError(Exception):
    """Error base del Browser Manager."""
    pass


class BrowserSession:
    """
    Representa una sesión de navegador activa.
    """

    def __init__(
        self,
        session_id: str,
        container_id: str,
        cdp_url: str | None = None,
    ):
        self.session_id = session_id
        self.container_id = container_id
        self.cdp_url = cdp_url
        self.created_at = time.time()
        self.last_active_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "container_id": self.container_id[:12],
            "cdp_url": self.cdp_url,
            "uptime_seconds": round(time.time() - self.created_at, 1),
        }


class BrowserManager:
    """
    Gestiona el ciclo de vida de navegadores headless en contenedores Docker.

    - Sesiones aisladas por user/session
    - Perfiles persistentes en volúmenes Docker
    - CDP (Chrome DevTools Protocol) para control remoto
    - Timeout automático de sesiones inactivas
    """

    def __init__(self):
        self._docker_client: docker.DockerClient | None = None
        self._sessions: dict[str, BrowserSession] = {}  # session_id -> session
        self._cleanup_task: asyncio.Task | None = None
        self._browser_port = 9222

    async def start(self) -> None:
        """Inicializa el cliente Docker."""
        try:
            self._docker_client = docker.from_env()
            self._docker_client.ping()
            logger.info("BrowserManager: conectado a Docker daemon")

            # Loop de limpieza
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        except DockerException as e:
            logger.error("BrowserManager: error conectando a Docker: %s", e)
            raise BrowserError(f"No se pudo conectar a Docker: {e}") from e

    async def stop(self) -> None:
        """Detiene todas las sesiones activas."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        session_ids = list(self._sessions.keys())
        for session_id in session_ids:
            await self.close_session(session_id)

        if self._docker_client:
            self._docker_client.close()

        logger.info("BrowserManager: detenido")

    # ── Gestión de Sesiones ──────────────────────────────

    async def create_session(self, session_id: str | None = None) -> BrowserSession:
        """
        Crea una nueva sesión de navegador.

        Si session_id ya existe, retorna la sesión existente.
        """
        if session_id and session_id in self._sessions:
            logger.debug("BrowserManager: reusando sesión %s", session_id[:8])
            return self._sessions[session_id]

        if not self._docker_client:
            raise BrowserError("Docker no inicializado")

        session_id = session_id or uuid.uuid4().hex
        container_name = f"aria-browser-{uuid.uuid4().hex[:12]}"

        try:
            # Crear volumen para perfil persistente
            profile_volume = f"aria-profile-{session_id[:12]}"

            container = self._docker_client.containers.create(
                image=settings.BROWSER_IMAGE,
                name=container_name,
                detach=True,
                environment={
                    "SESSION_ID": session_id,
                    "BROWSER_TIMEOUT_SECONDS": str(settings.BROWSER_TIMEOUT_SECONDS),
                    "BROWSER_HEADLESS": str(settings.BROWSER_HEADLESS).lower(),
                },
                volumes=[f"{profile_volume}:/app/profiles/{session_id[:12]}"],
                ports={f"{self._browser_port}/tcp": None},  # Puerto aleatorio
                shm_size="2g",
                mem_limit="2g",
                nano_cpus=int(2 * 1e9),
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
            )

            container.start()

            # Obtener el puerto mapeado
            container.reload()
            host_port = container.attrs["NetworkSettings"]["Ports"].get(
                f"{self._browser_port}/tcp",
                [],
            )
            cdp_port = host_port[0]["HostPort"] if host_port else self._browser_port
            cdp_url = f"http://localhost:{cdp_port}"

            session = BrowserSession(
                session_id=session_id,
                container_id=container.id,
                cdp_url=cdp_url,
            )

            self._sessions[session_id] = session

            logger.info(
                "BrowserManager: sesión %s creada (container=%s)",
                session_id[:8],
                container_name,
            )
            return session

        except DockerException as e:
            logger.error("BrowserManager: error creando sesión: %s", e)
            raise BrowserError(f"Error creando sesión de navegador: {e}") from e

    async def close_session(self, session_id: str) -> bool:
        """Cierra una sesión de navegador."""
        session = self._sessions.pop(session_id, None)
        if not session:
            return False

        try:
            container = self._docker_client.containers.get(session.container_id)
            container.stop(timeout=10)
            container.remove(force=True)
            logger.info("BrowserManager: sesión %s cerrada", session_id[:8])
            return True
        except NotFound:
            return True
        except DockerException as e:
            logger.error("BrowserManager: error cerrando sesión: %s", e)
            return False

    async def execute_cdp(self, session_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """
        Ejecuta un comando CDP (Chrome DevTools Protocol) en una sesión.

        command: {"method": "Page.navigate", "params": {"url": "..."}}
        """
        session = self._sessions.get(session_id)
        if not session:
            raise BrowserError(f"Sesión no encontrada: {session_id[:8]}")

        # Fase 4: stub CDP — se implementa con websocket al CDP en Fase 5
        # Por ahora simula respuestas básicas
        import httpx

        method = command.get("method", "")
        params = command.get("params", {})

        if method == "Page.navigate":
            return {
                "result": {
                    "frameId": uuid.uuid4().hex,
                    "loaderId": uuid.uuid4().hex,
                    "url": params.get("url", ""),
                }
            }
        elif method == "Runtime.evaluate":
            return {
                "result": {
                    "type": "string",
                    "value": f"[SIMULATED] {params.get('expression', '')}",
                }
            }
        elif method == "Page.captureScreenshot":
            return {
                "result": {
                    "data": "[BASE64_SIMULATED_SCREENSHOT]",
                }
            }
        else:
            return {
                "result": {
                    "type": "string",
                    "value": f"CDP method {method} simulated",
                }
            }

    async def navigate(self, session_id: str, url: str, timeout: int = 30) -> dict[str, Any]:
        """Navega a una URL."""
        result = await self.execute_cdp(session_id, {
            "method": "Page.navigate",
            "params": {"url": url},
        })
        session = self._sessions.get(session_id)
        if session:
            session.last_active_at = time.time()
        return result

    async def extract_data(
        self,
        session_id: str,
        selectors: list[str],
        format: str = "text",
    ) -> dict[str, Any]:
        """Extrae datos de la página actual."""
        session = self._sessions.get(session_id)
        if session:
            session.last_active_at = time.time()

        results = {}
        for selector in selectors:
            expr = f"JSON.stringify(Array.from(document.querySelectorAll('{selector}')).map(e => e.innerText))"
            result = await self.execute_cdp(session_id, {
                "method": "Runtime.evaluate",
                "params": {"expression": expr},
            })
            results[selector] = result.get("result", {}).get("value", f"[{selector}]")

        return {
            "extracted": results,
            "format": format,
            "count": len(selectors),
        }

    # ── Limpieza ──────────────────────────────────────────

    async def _cleanup_loop(self) -> None:
        """Cierra sesiones inactivas periódicamente."""
        while True:
            try:
                await asyncio.sleep(300)  # Cada 5 minutos
                await self._cleanup_stale_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("BrowserManager: error en limpieza: %s", e)

    async def _cleanup_stale_sessions(self) -> None:
        """Cierra sesiones inactivas por más de 30 minutos."""
        stale_timeout = 1800  # 30 minutos
        now = time.time()

        stale_sessions = [
            session_id
            for session_id, session in self._sessions.items()
            if now - session.last_active_at > stale_timeout
        ]

        for session_id in stale_sessions:
            logger.info("BrowserManager: cerrando sesión inactiva %s", session_id[:8])
            await self.close_session(session_id)

    # ── Estado ────────────────────────────────────────────

    @property
    def active_sessions(self) -> int:
        return len(self._sessions)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "active_sessions": self.active_sessions,
            "sessions": [s.to_dict() for s in self._sessions.values()],
            "browser_image": settings.BROWSER_IMAGE,
            "timeout_seconds": settings.BROWSER_TIMEOUT_SECONDS,
            "headless": settings.BROWSER_HEADLESS,
        }
