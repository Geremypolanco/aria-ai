"""
ARIA Agent System — Tool: terminal_run.
Ejecuta comandos en el sandbox Docker aislado.

Sintaxis:
    tool: terminal_run
    params:
        command: string - Comando a ejecutar
        timeout: int (opcional) - Timeout en segundos
        workdir: string (opcional) - Directorio de trabajo

Retorna:
    {
        "stdout": string,
        "stderr": string,
        "exit_code": int,
        "duration_ms": int,
        "output_text": string,
        "truncated": bool
    }
"""
from __future__ import annotations

import logging
from typing import Any

from sandbox.manager import SandboxManager

logger = logging.getLogger("aria.tools.terminal")


async def execute(
    sandbox: SandboxManager,
    task_id: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """
    Ejecuta un comando en el sandbox.
    """
    command = params.get("command", "")
    timeout = params.get("timeout", 60)

    if not command:
        return {
            "success": False,
            "error": "No se especificó comando",
            "stdout": "",
            "stderr": "command parameter is required",
            "exit_code": -1,
        }

    try:
        result = await sandbox.run_command(
            task_id=task_id,
            command=command,
            timeout=timeout,
        )

        return {
            "success": result["exit_code"] == 0,
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "exit_code": result["exit_code"],
            "duration_ms": result["duration_ms"],
            "output_text": result["output_text"],
            "truncated": result.get("truncated", False),
            "error": result["stderr"][:500] if result["exit_code"] != 0 else None,
        }

    except Exception as e:
        logger.error("terminal_run error: %s", e)
        return {
            "success": False,
            "error": str(e)[:500],
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1,
        }
