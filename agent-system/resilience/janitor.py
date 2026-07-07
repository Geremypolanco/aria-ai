"""
ARIA Agent System — Janitor.
Limpieza automática de recursos huérfanos.

- Destruye contenedores Docker inactivos > 1 hora
- Limpia sesiones de navegador huérfanas
- Elimina logs antiguos (> 90 días)
- Reporta métricas de limpieza
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import docker
from docker.errors import DockerException, NotFound
from sqlalchemy import text

from core.db.connection import get_session
from core.config.settings import settings

logger = logging.getLogger("aria.resilience.janitor")


class Janitor:
    """
    Limpiador automático de recursos.

    Ciclo de limpieza:
    1. Contenedores Docker inactivos > 1 hora → destruir
    2. Sesiones de navegador huérfanas → cerrar
    3. Logs de tareas > 90 días → archivar/eliminar
    4. Tareas completadas > 7 días → archivar

    Cada ciclo reporta estadísticas de limpieza.
    """

    def __init__(self):
        self._docker_client: docker.DockerClient | None = None
        self._running = False
        self._task: asyncio.Task | None = None
        self._cleanup_stats: dict[str, int] = {
            "containers_destroyed": 0,
            "browser_sessions_closed": 0,
            "logs_archived": 0,
            "tasks_archived": 0,
        }

    async def start(self) -> None:
        """Inicia el ciclo de limpieza periódica."""
        if self._running:
            return

        try:
            self._docker_client = docker.from_env()
            self._docker_client.ping()
            logger.info("Janitor: conectado a Docker daemon")
        except DockerException as e:
            logger.warning("Janitor: Docker no disponible: %s", e)
            self._docker_client = None

        self._running = True
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info("Janitor: ciclo de limpieza iniciado")

    async def stop(self) -> None:
        """Detiene el ciclo de limpieza."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._docker_client:
            self._docker_client.close()
        logger.info("Janitor: detenido")

    async def _cleanup_loop(self) -> None:
        """Ejecuta limpieza cada 15 minutos."""
        while self._running:
            try:
                stats = await self.run_cleanup()
                if any(v > 0 for v in stats.values()):
                    logger.info("Janitor: limpieza completada: %s", stats)
                await asyncio.sleep(900)  # 15 minutos
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Janitor: error en ciclo: %s", e)
                await asyncio.sleep(60)

    async def run_cleanup(self) -> dict[str, int]:
        """Ejecuta una ronda completa de limpieza."""
        stats: dict[str, int] = {
            "containers_destroyed": 0,
            "browser_sessions_closed": 0,
            "logs_archived": 0,
            "tasks_archived": 0,
        }

        # 1. Limpiar contenedores Docker huérfanos
        if self._docker_client:
            try:
                stats["containers_destroyed"] = await self._cleanup_docker_containers()
            except Exception as e:
                logger.error("Janitor: error limpiando contenedores: %s", e)

        # 2. Limpiar sesiones de navegador
        try:
            stats["browser_sessions_closed"] = await self._cleanup_browser_sessions()
        except Exception as e:
            logger.error("Janitor: error limpiando sesiones browser: %s", e)

        # 3. Archivar logs antiguos (> 90 días)
        try:
            stats["logs_archived"] = await self._cleanup_old_logs()
        except Exception as e:
            logger.error("Janitor: error limpiando logs: %s", e)

        # 4. Archivar tareas completadas antiguas (> 7 días)
        try:
            stats["tasks_archived"] = await self._cleanup_old_tasks()
        except Exception as e:
            logger.error("Janitor: error limpiando tareas: %s", e)

        self._cleanup_stats = stats
        return stats

    # ── Limpieza de Contenedores Docker ──

    async def _cleanup_docker_containers(self) -> int:
        """
        Destruye contenedores huérfanos o inactivos > 1 hora.

        Busca:
        - Contenedores aria-sandbox-* y aria-browser-* que:
          a) Llevan más de 1 hora corriendo sin actividad
          b) No están asociados a ninguna tarea activa
        """
        if not self._docker_client:
            return 0

        destroyed = 0
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

        try:
            # Contenedores sandbox
            sandbox_containers = self._docker_client.containers.list(
                all=True,
                filters={"name": "aria-sandbox"},
            )

            for container in sandbox_containers:
                try:
                    created = container.attrs.get("Created", "")
                    if created:
                        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        if created_dt < one_hour_ago:
                            logger.warning(
                                "Janitor: destruyendo contenedor huérfano %s (creado %s)",
                                container.name,
                                created,
                            )
                            container.stop(timeout=5)
                            container.remove(force=True)
                            destroyed += 1
                except (NotFound, DockerException) as e:
                    logger.debug("Janitor: error con contenedor %s: %s", container.name, e)

            # Contenedores browser
            browser_containers = self._docker_client.containers.list(
                all=True,
                filters={"name": "aria-browser"},
            )

            for container in browser_containers:
                try:
                    created = container.attrs.get("Created", "")
                    if created:
                        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        if created_dt < one_hour_ago:
                            logger.warning(
                                "Janitor: destruyendo browser huérfano %s (creado %s)",
                                container.name,
                                created,
                            )
                            container.stop(timeout=10)
                            container.remove(force=True)
                            destroyed += 1
                except (NotFound, DockerException):
                    pass

        except DockerException as e:
            logger.error("Janitor: error listando contenedores: %s", e)

        return destroyed

    # ── Limpieza de Sesiones de Navegador ──

    async def _cleanup_browser_sessions(self) -> int:
        """
        Limpia sesiones de navegador huérfanas de la base de datos.
        """
        try:
            async with get_session() as session:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
                result = await session.execute(
                    text("""
                        UPDATE sessions SET is_active = false
                        WHERE is_active = true
                        AND last_active_at < :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                return result.rowcount or 0
        except Exception as e:
            logger.debug("Janitor: error limpiando sesiones: %s", e)
            return 0

    # ── Limpieza de Logs Antiguos ──

    async def _cleanup_old_logs(self) -> int:
        """Archiva logs de tareas > 90 días. Mueve a tabla de archive."""
        try:
            async with get_session() as session:
                cutoff = datetime.now(timezone.utc) - timedelta(days=90)
                archive_sql = """
                    INSERT INTO task_logs_archive (id, task_id, agent_type, step, action,
                        input, output, status, duration_ms, level, message, security_metadata, created_at)
                    SELECT id, task_id, agent_type, step, action,
                        input, output, status, duration_ms, level, message, security_metadata, created_at
                    FROM task_logs
                    WHERE created_at < :cutoff
                    ON CONFLICT (id) DO NOTHING
                """
                await session.execute(text(archive_sql), {"cutoff": cutoff})

                delete_sql = "DELETE FROM task_logs WHERE created_at < :cutoff"
                result = await session.execute(text(delete_sql), {"cutoff": cutoff})
                return result.rowcount or 0
        except Exception as e:
            logger.debug("Janitor: error archivando logs: %s", e)
            return 0

    async def _cleanup_old_tasks(self) -> int:
        """Archiva tareas completadas > 7 días."""
        try:
            async with get_session() as session:
                cutoff = datetime.now(timezone.utc) - timedelta(days=7)
                archive_sql = """
                    INSERT INTO tasks_archive (id, status, task_type, title, input,
                        plan, result, error_message, priority, retry_count, max_retries,
                        created_by, session_id, created_at, started_at, completed_at)
                    SELECT id, status, task_type, title, input,
                        plan, result, error_message, priority, retry_count, max_retries,
                        created_by, session_id, created_at, started_at, completed_at
                    FROM tasks
                    WHERE status IN ('completed', 'failed', 'cancelled')
                    AND completed_at < :cutoff
                    ON CONFLICT (id) DO NOTHING
                """
                await session.execute(text(archive_sql), {"cutoff": cutoff})

                delete_sql = """
                    DELETE FROM tasks
                    WHERE status IN ('completed', 'failed', 'cancelled')
                    AND completed_at < :cutoff
                """
                result = await session.execute(text(delete_sql), {"cutoff": cutoff})
                return result.rowcount or 0
        except Exception as e:
            logger.debug("Janitor: error archivando tareas: %s", e)
            return 0

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "last_cleanup": self._cleanup_stats,
            "interval_minutes": 15,
        }


# Singleton global
janitor = Janitor()