"""
ARIA Agent System — Sandbox Manager.
Gestiona contenedores Docker efímeros para ejecución aislada de comandos.

Cada tarea obtiene su propio contenedor con:
- Límites de memoria, CPU y tiempo
- Sin acceso a red (opcional)
- Sistema de archivos limpio
- Destrucción automática al finalizar
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound, NotFound

from core.config.settings import settings

logger = logging.getLogger("aria.sandbox")


class SandboxError(Exception):
    """Error base del Sandbox."""
    pass


class SandboxTimeout(SandboxError):
    """Timeout en ejecución de comando."""
    pass


class SandboxContainer:
    """
    Representa un contenedor sandbox activo para una tarea.
    Se destruye automáticamente al salir del context manager.
    """

    def __init__(
        self,
        container_id: str,
        task_id: str,
        memory_limit: str,
        cpu_limit: float,
    ):
        self.container_id = container_id
        self.task_id = task_id
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.created_at = time.time()
        self._running = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "container_id": self.container_id,
            "task_id": self.task_id[:8],
            "memory_limit": self.memory_limit,
            "cpu_limit": self.cpu_limit,
            "uptime_seconds": round(time.time() - self.created_at, 1),
        }


class SandboxManager:
    """
    Gestiona el ciclo de vida completo de contenedores sandbox.

    - Pool de contenedores para reutilización (opcional)
    - Timeout global de contenedor
    - Límites de recursos por tarea
    """

    def __init__(self):
        self._docker_client: docker.DockerClient | None = None
        self._containers: dict[str, SandboxContainer] = {}  # task_id -> container
        self._container_tasks: dict[str, str] = {}  # container_id -> task_id
        self._cleanup_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Inicializa el cliente Docker."""
        try:
            self._docker_client = docker.from_env()
            self._docker_client.ping()
            logger.info("SandboxManager: conectado a Docker daemon")

            # Verificar que la imagen existe
            try:
                self._docker_client.images.get(settings.SANDBOX_IMAGE)
                logger.info("SandboxManager: imagen %s encontrada", settings.SANDBOX_IMAGE)
            except ImageNotFound:
                logger.warning(
                    "SandboxManager: imagen %s no encontrada, se construirá en primer uso",
                    settings.SANDBOX_IMAGE,
                )

            # Loop de limpieza de contenedores huérfanos
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        except DockerException as e:
            logger.error("SandboxManager: error conectando a Docker: %s", e)
            raise SandboxError(f"No se pudo conectar a Docker: {e}") from e

    async def stop(self) -> None:
        """Destruye todos los contenedores activos y cierra conexión."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Destruir contenedores activos
        task_ids = list(self._containers.keys())
        for task_id in task_ids:
            try:
                await self.destroy_container(task_id)
            except Exception as e:
                logger.error("SandboxManager: error destruyendo contenedor %s: %s", task_id[:8], e)

        if self._docker_client:
            self._docker_client.close()
            self._docker_client = None

        logger.info("SandboxManager: detenido")

    # ── Gestión de Contenedores ──────────────────────────

    async def create_container(self, task_id: str) -> SandboxContainer:
        """
        Crea un nuevo contenedor sandbox para una tarea.
        Retorna el objeto SandboxContainer.
        """
        if not self._docker_client:
            raise SandboxError("Docker no inicializado")

        if task_id in self._containers:
            logger.warning("SandboxManager: tarea %s ya tiene contenedor activo", task_id[:8])
            return self._containers[task_id]

        container_name = f"aria-sandbox-{uuid.uuid4().hex[:12]}"

        try:
            container = self._docker_client.containers.create(
                image=settings.SANDBOX_IMAGE,
                name=container_name,
                command=["sleep", "infinity"],  # Mantener vivo hasta que se necesite
                detach=True,
                stdin_open=True,
                tty=True,
                mem_limit=settings.SANDBOX_MEMORY_LIMIT,
                nano_cpus=int(settings.SANDBOX_CPU_LIMIT * 1e9),
                network_disabled=False,  # True si se quiere sin red
                read_only=False,
                working_dir="/sandbox",
                environment={
                    "TASK_ID": task_id,
                    "DEBIAN_FRONTEND": "noninteractive",
                },
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
            )

            container.start()
            sandbox_container = SandboxContainer(
                container_id=container.id,
                task_id=task_id,
                memory_limit=settings.SANDBOX_MEMORY_LIMIT,
                cpu_limit=settings.SANDBOX_CPU_LIMIT,
            )

            self._containers[task_id] = sandbox_container
            self._container_tasks[container.id] = task_id

            logger.info(
                "SandboxManager: contenedor %s creado para tarea %s",
                container_name,
                task_id[:8],
            )
            return sandbox_container

        except DockerException as e:
            logger.error("SandboxManager: error creando contenedor: %s", e)
            raise SandboxError(f"Error creando contenedor: {e}") from e

    async def get_container(self, task_id: str) -> SandboxContainer | None:
        """Retorna el contenedor de una tarea, si existe."""
        return self._containers.get(task_id)

    async def destroy_container(self, task_id: str) -> bool:
        """Destruye el contenedor de una tarea."""
        container = self._containers.pop(task_id, None)
        if not container:
            return False

        try:
            docker_container = self._docker_client.containers.get(container.container_id)
            docker_container.stop(timeout=5)
            docker_container.remove(force=True)
            self._container_tasks.pop(container.container_id, None)
            logger.info("SandboxManager: contenedor destruido para tarea %s", task_id[:8])
            return True
        except NotFound:
            # Contenedor ya no existe
            self._container_tasks.pop(container.container_id, None)
            return True
        except DockerException as e:
            logger.error("SandboxManager: error destruyendo contenedor: %s", e)
            return False

    # ── Ejecución de Comandos ─────────────────────────────

    async def run_command(
        self,
        task_id: str,
        command: str,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """
        Ejecuta un comando en el contenedor de una tarea.

        Si la tarea no tiene contenedor, crea uno.
        timeout: segundos (default: SANDBOX_TIMEOUT_SECONDS)
        """
        if not self._docker_client:
            raise SandboxError("Docker no inicializado")

        container = self._containers.get(task_id)
        if not container:
            # Auto-create container para la tarea
            container = await self.create_container(task_id)

        timeout = timeout or settings.SANDBOX_TIMEOUT_SECONDS
        start = time.time()

        try:
            docker_container = self._docker_client.containers.get(container.container_id)

            exec_result = docker_container.exec_run(
                cmd=["/bin/bash", "-c", command],
                workdir="/sandbox",
                environment={"TASK_ID": task_id},
                timeout=timeout,
                demux=True,  # Separar stdout/stderr
            )

            duration_ms = int((time.time() - start) * 1000)
            exit_code = exec_result.exit_code
            stdout_bytes, stderr_bytes = exec_result.output

            stdout = (stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else "")
            stderr = (stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else "")

            logger.debug(
                "SandboxManager: comando ejecutado (exit=%d, %dms): %s",
                exit_code,
                duration_ms,
                command[:80],
            )

            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "output_text": stdout if exit_code == 0 else f"Error: {stderr[:500]}",
                "truncated": len(stdout) > 10000 or len(stderr) > 10000,
            }

        except docker.errors.APIError as e:
            if "timeout" in str(e).lower():
                raise SandboxTimeout(f"Timeout después de {timeout}s: {command[:50]}")
            raise SandboxError(f"Error Docker: {e}") from e
        except NotFound:
            self._containers.pop(task_id, None)
            self._container_tasks.pop(container.container_id, None)
            raise SandboxError(f"Contenedor no encontrado para tarea {task_id[:8]}")

    async def write_file(self, task_id: str, path: str, content: str) -> bool:
        """
        Escribe un archivo dentro del contenedor.
        """
        container = self._containers.get(task_id)
        if not container:
            return False

        try:
            docker_container = self._docker_client.containers.get(container.container_id)
            # Usar tee para escribir el archivo
            result = docker_container.exec_run(
                cmd=["/bin/bash", "-c", f"cat > {path} << 'ARIAEOF'\n{content}\nARIAEOF"],
                timeout=10,
            )
            return result.exit_code == 0
        except Exception as e:
            logger.error("SandboxManager: error escribiendo archivo: %s", e)
            return False

    async def read_file(self, task_id: str, path: str) -> str | None:
        """
        Lee un archivo dentro del contenedor.
        """
        result = await self.run_command(task_id, f"cat {path}")
        if result["exit_code"] == 0:
            return result["stdout"]
        return None

    # ── Limpieza ──────────────────────────────────────────

    async def _cleanup_loop(self) -> None:
        """Limpia periódicamente contenedores huérfanos y tareas expiradas."""
        while True:
            try:
                await asyncio.sleep(300)  # Cada 5 minutos
                await self._cleanup_orphans()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("SandboxManager: error en limpieza: %s", e)

    async def _cleanup_orphans(self) -> None:
        """Busca y destruye contenedores que ya no tienen tarea asociada."""
        if not self._docker_client:
            return

        try:
            # Contenedores Docker activos con prefijo aria-sandbox
            all_containers = self._docker_client.containers.list(
                filters={"name": "aria-sandbox"},
            )

            for c in all_containers:
                if c.id not in self._container_tasks:
                    logger.warning(
                        "SandboxManager: limpiando contenedor huérfano %s",
                        c.name,
                    )
                    try:
                        c.stop(timeout=5)
                        c.remove(force=True)
                    except Exception:
                        pass

            # Limpiar referencias internas de tareas muertas
            dead_tasks = [
                task_id for task_id, container in list(self._containers.items())
                if container.container_id not in {c.id for c in all_containers}
            ]
            for task_id in dead_tasks:
                self._containers.pop(task_id, None)

        except Exception as e:
            logger.error("SandboxManager: error limpiando huérfanos: %s", e)

    # ── Estado ────────────────────────────────────────────

    @property
    def active_containers(self) -> int:
        return len(self._containers)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "active_containers": self.active_containers,
            "containers": [
                c.to_dict() for c in self._containers.values()
            ],
            "memory_limit": settings.SANDBOX_MEMORY_LIMIT,
            "cpu_limit": settings.SANDBOX_CPU_LIMIT,
            "timeout_seconds": settings.SANDBOX_TIMEOUT_SECONDS,
        }
