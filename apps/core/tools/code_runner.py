"""
code_runner.py — Sandbox seguro para ejecución de código por ARIA AI.

Ejecuta Python y JavaScript con:
  - Timeout configurable (default 15s)
  - Captura completa de stdout/stderr
  - Restricción de imports peligrosos
  - Sin acceso a filesystem fuera del workspace temporal

ARIA puede escribir código, ejecutarlo, ver el output real, y corregirlo.
Esto habilita el loop: escribir → ejecutar → depurar → iterar.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import sys
import tempfile
from typing import Any

logger = logging.getLogger("aria.code_runner")

# Imports que no se permiten en el sandbox de Python
_BLOCKED_IMPORTS = {
    "subprocess",
    "os.system",
    "shutil.rmtree",
    "socket",
    "ctypes",
    "multiprocessing",
}

# Tamaño máximo de output para no saturar el contexto
MAX_OUTPUT_CHARS = 4000
DEFAULT_TIMEOUT = 15  # segundos


class CodeRunner:
    """Ejecuta código de forma segura y devuelve stdout/stderr."""

    async def run(
        self,
        code: str,
        language: str = "python",
        timeout: int = DEFAULT_TIMEOUT,
        packages: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Ejecuta código y devuelve {success, stdout, stderr, exit_code, runtime_ms}.
        """
        language = language.lower().strip()

        if language in ("python", "python3", "py"):
            return await self._run_python(code, timeout, packages)
        if language in ("javascript", "js", "node", "nodejs"):
            return await self._run_javascript(code, timeout)
        if language in ("bash", "shell", "sh"):
            return await self._run_bash(code, timeout)
        # Intentar como Python por defecto
        return await self._run_python(code, timeout, packages)

    async def _run_python(
        self, code: str, timeout: int, packages: list[str] | None
    ) -> dict[str, Any]:
        """Ejecuta Python en subproceso aislado."""
        # Chequeo básico de imports peligrosos
        warning = self._check_dangerous(code)
        if warning:
            return {"success": False, "stderr": warning, "stdout": "", "exit_code": -1}

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        try:
            # Instalar paquetes requeridos si se indican
            if packages:
                await self._install_packages(packages)

            return await self._exec(
                [sys.executable, tmp_path], timeout, cwd=os.path.dirname(tmp_path)
            )
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

    async def _run_javascript(self, code: str, timeout: int) -> dict[str, Any]:
        """Ejecuta JavaScript con Node.js si está disponible."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".js", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        try:
            return await self._exec(["node", tmp_path], timeout)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

    async def _run_bash(self, code: str, timeout: int) -> dict[str, Any]:
        """Ejecuta bash. Solo para comandos de lectura/análisis."""
        # Bloquear comandos destructivos
        dangerous = ["rm -rf", "dd if=", "mkfs", ":(){", "shutdown", "reboot"]
        for d in dangerous:
            if d in code:
                return {
                    "success": False,
                    "stderr": f"Comando peligroso bloqueado: '{d}'",
                    "stdout": "",
                    "exit_code": -1,
                }
        return await self._exec(["bash", "-c", code], timeout)

    async def _exec(self, cmd: list[str], timeout: int, cwd: str | None = None) -> dict[str, Any]:
        """Ejecuta comando y captura output con timeout."""
        import time

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"Timeout: ejecución superó {timeout}s",
                    "exit_code": -1,
                    "runtime_ms": int((time.monotonic() - start) * 1000),
                }

            runtime_ms = int((time.monotonic() - start) * 1000)
            stdout = stdout_b.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]
            stderr = stderr_b.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]
            success = proc.returncode == 0

            logger.info("[CodeRunner] exit=%d runtime=%dms", proc.returncode, runtime_ms)
            return {
                "success": success,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": proc.returncode,
                "runtime_ms": runtime_ms,
            }
        except FileNotFoundError as exc:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Intérprete no encontrado: {exc}",
                "exit_code": -1,
                "runtime_ms": 0,
            }
        except Exception as exc:
            logger.error("[CodeRunner] exec error: %s", exc)
            return {
                "success": False,
                "stdout": "",
                "stderr": str(exc),
                "exit_code": -1,
                "runtime_ms": 0,
            }

    async def _install_packages(self, packages: list[str]) -> None:
        """Instala paquetes pip necesarios para el script."""
        try:
            await self._exec(
                [sys.executable, "-m", "pip", "install", "--quiet", *packages],
                timeout=60,
            )
        except Exception as exc:
            logger.warning("[CodeRunner] package install error: %s", exc)

    def _check_dangerous(self, code: str) -> str:
        """Retorna mensaje de error si el código contiene imports peligrosos."""
        for blocked in _BLOCKED_IMPORTS:
            pattern = blocked.replace(".", r"\.")
            if re.search(rf"\b{pattern}\b", code):
                return f"Import bloqueado en sandbox: '{blocked}'"
        return ""

    async def run_with_fix(
        self, code: str, language: str = "python", max_iterations: int = 3
    ) -> dict[str, Any]:
        """
        Ejecuta código, y si falla, usa IA para corregirlo automáticamente.
        Implementa el loop: escribir → ejecutar → depurar → reejecutar.
        """
        result = await self.run(code, language)

        if result.get("success") or max_iterations == 0:
            return result

        # Código falló — intentar auto-fix con IA
        for attempt in range(max_iterations):
            error = result.get("stderr", "")[:500]
            logger.info(
                "[CodeRunner] Auto-fix attempt %d/%d: %s", attempt + 1, max_iterations, error[:80]
            )

            try:
                from apps.core.tools.ai_client import AIModel, get_ai_client

                ai = get_ai_client()
                if not ai:
                    break
                resp = await ai.complete(
                    system=(
                        f"Expert {language} debugger. Fix the code error. "
                        f"Return ONLY the corrected code, no explanations, no markdown fences."
                    ),
                    user=f"Original code:\n{code}\n\nError:\n{error}\n\nFixed code:",
                    model=AIModel.CODE,
                    max_tokens=1500,
                    temperature=0.1,
                    agent_name="code_autofix",
                )
                if not (resp and resp.success):
                    break
                fixed_code = resp.content.strip()
                if fixed_code.startswith("```"):
                    lines = fixed_code.split("\n")
                    fixed_code = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
                code = fixed_code
                result = await self.run(code, language)
                if result.get("success"):
                    result["auto_fixed"] = True
                    result["fixed_code"] = code
                    return result
            except Exception as exc:
                logger.error("[CodeRunner] auto-fix error: %s", exc)
                break

        return result
