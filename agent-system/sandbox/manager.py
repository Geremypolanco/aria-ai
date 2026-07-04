"""
ARIA Agent System — Sandbox Manager.
Contenedores Docker efímeros para ejecución aislada de comandos.
Implementación completa en Fase 3.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("aria.sandbox")


class SandboxError(Exception):
    """Error base del Sandbox."""
    pass


class SandboxTimeout(SandboxError):
    """Timeout en ejecución de comando."""
    pass


class SandboxManager:
    """
    Gestiona contenedores Docker efímeros para ejecución segura.

    - Cada tarea obtiene su propio contenedor
    - El contenedor se destruye al finalizar
    - Límites de memoria, CPU y tiempo
    - Sin acceso a red externa (opcional)
    """

    def __init__(self):
        self._docker_client = None
        self._active_containers: dict[str, str] = {}  # task_id -> container_id

    async def start(self) -> None:
        """Inicializa el cliente Docker."""
        raise NotImplementedError("Fase 3: implementar SandboxManager.start()")

    async def run_command(self, task_id: str, command: str, timeout: int = 30) -> dict:
        """
        Ejecuta un comando en un contenedor aislado.
        Retorna: {stdout, stderr, exit_code, duration_ms}
        """
        raise NotImplementedError("Fase 3: implementar SandboxManager.run_command()")

    async def cleanup(self, task_id: str) -> None:
        """Destruye el contenedor de una tarea."""
        raise NotImplementedError("Fase 3: implementar SandboxManager.cleanup()")

    async def stop(self) -> None:
        """Destruye todos los contenedores activos."""
        raise NotImplementedError("Fase 3: implementar SandboxManager.stop()")
