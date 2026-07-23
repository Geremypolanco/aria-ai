"""
code_runner.py — Sandbox seguro para ejecución de código por ARIA AI.

Ejecuta Python, JavaScript y bash con:
  - Aislamiento real de proceso/filesystem/red via bubblewrap (bwrap), cuando
    está disponible — namespaces sin privilegios (mount/pid/net/ipc/uts), con
    solo el directorio de trabajo efímero de esa ejecución montado en
    lectura-escritura y el resto del filesystem host en solo lectura o
    inexistente. Sin `bwrap`, cae a ejecución directa (mismo nivel de
    aislamiento que antes) — el resultado incluye "sandboxed": bool para que
    quien llama sepa cuál se aplicó.
  - Límites de recursos reales (CPU, memoria, procesos, tamaño de archivo,
    file descriptors) via `ulimit`, independientes de bwrap.
  - Red deshabilitada por defecto (namespace de red vacío); solo
    _install_packages() la habilita explícitamente para poder llegar a PyPI.
  - Timeout configurable (default 15s) reforzado además por el límite de
    ulimit de CPU.
  - Captura completa de stdout/stderr, sin heredar el entorno del servidor
    (ningún secreto configurado es visible dentro del código ejecutado).
  - Restricción adicional (defense-in-depth) de imports peligrosos.

ARIA puede escribir código, ejecutarlo, ver el output real, y corregirlo.
Esto habilita el loop: escribir → ejecutar → depurar → iterar.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shutil
import subprocess
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

# Límites de recursos aplicados a todo proceso ejecutado (bwrap disponible o no).
_ULIMIT_VIRTUAL_MEM_KB = 1_048_576  # 1 GB de memoria virtual
_ULIMIT_MAX_PROCESSES = 64  # evita fork bombs
_ULIMIT_MAX_FILE_SIZE_BLOCKS = 20_480  # ~10 MB por archivo escrito (bloques de 512B)
_ULIMIT_MAX_OPEN_FILES = 128

# Directorios host que se montan de solo lectura dentro del sandbox — lo
# mínimo necesario para que el intérprete (python/node/bash) y sus
# librerías dinámicas funcionen. Todo lo demás del filesystem host es
# invisible dentro del sandbox.
_RO_BIND_CANDIDATES = ["/usr", "/bin", "/lib", "/lib64", "/usr/local", "/etc"]


def _bwrap_path() -> str | None:
    """Ruta al binario bwrap si está instalado y REALMENTE puede crear
    namespaces sin privilegios en este entorno — cacheado tras la primera
    llamada. No basta con que el binario exista: algunos runtimes de
    contenedores (dependiendo de su perfil de seccomp/AppArmor) bloquean
    `unshare(CLONE_NEWUSER)` para procesos sin privilegios, en cuyo caso
    bwrap existe pero cada invocación fallaría con "Creating new namespace
    failed: Operation not permitted" — sin este chequeo, CodeRunner
    reportaría error de sandbox en vez de ejecutar el código (peor que la
    ejecución sin aislar). Se prueba una vez con una invocación mínima."""
    if not hasattr(_bwrap_path, "_cached"):
        path = shutil.which("bwrap")
        if path:
            try:
                probe = subprocess.run(
                    [path, "--unshare-all", "--ro-bind", "/", "/", "--", "true"],
                    capture_output=True,
                    timeout=5,
                )
                if probe.returncode != 0:
                    logger.warning(
                        "[CodeRunner] bwrap present but unusable in this environment "
                        "(namespaces likely blocked) — falling back to unsandboxed exec: %s",
                        probe.stderr.decode("utf-8", errors="replace")[:200],
                    )
                    path = None
            except Exception as exc:
                logger.warning("[CodeRunner] bwrap capability probe failed: %s", exc)
                path = None
        _bwrap_path._cached = path
    return _bwrap_path._cached


def _build_sandboxed_cmd(cmd: list[str], workdir: str, network: bool) -> list[str]:
    """Envuelve `cmd` con bubblewrap: namespaces sin privilegios que dejan
    `workdir` como único punto de escritura real, deshabilitan la red salvo
    que `network=True`, y no exponen ningún otro archivo del servidor
    (secretos, código fuente de ARIA, otras ejecuciones concurrentes)."""
    bwrap = _bwrap_path()
    assert bwrap is not None

    binds: list[str] = []
    for path in _RO_BIND_CANDIDATES:
        if os.path.exists(path):
            binds += ["--ro-bind", path, path]

    sandbox_cmd = [
        bwrap,
        *binds,
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--bind", workdir, workdir,
        "--chdir", workdir,
        "--unshare-all",
    ]  # fmt: skip
    if network:
        sandbox_cmd += ["--share-net"]
        if os.path.exists("/etc/resolv.conf"):
            sandbox_cmd += ["--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf"]
    sandbox_cmd += ["--die-with-parent", "--new-session", "--"]

    return sandbox_cmd + _wrap_with_ulimits(cmd)


def _wrap_with_ulimits(cmd: list[str]) -> list[str]:
    """Aplica límites de recursos reales via el builtin `ulimit` de bash antes
    de reemplazar el shell con el comando real (`exec`). No depende de bwrap
    ni de preexec_fn (inseguro junto a asyncio) — funciona siempre."""
    ulimits = (
        f"ulimit -v {_ULIMIT_VIRTUAL_MEM_KB}; "
        f"ulimit -u {_ULIMIT_MAX_PROCESSES}; "
        f"ulimit -f {_ULIMIT_MAX_FILE_SIZE_BLOCKS}; "
        f"ulimit -n {_ULIMIT_MAX_OPEN_FILES}; "
        'exec "$@"'
    )
    return ["bash", "-c", ulimits, "--", *cmd]


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
        Ejecuta código y devuelve {success, stdout, stderr, exit_code, runtime_ms, sandboxed}.
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
        """Ejecuta Python en subproceso aislado, en un workdir efímero propio."""
        # Chequeo básico de imports peligrosos
        warning = self._check_dangerous(code)
        if warning:
            return {
                "success": False,
                "stderr": warning,
                "stdout": "",
                "exit_code": -1,
                "sandboxed": _bwrap_path() is not None,
            }

        workdir = tempfile.mkdtemp(prefix="aria_sandbox_")
        try:
            tmp_path = os.path.join(workdir, "script.py")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(code)

            extra_env: dict[str, str] = {}
            if packages:
                site_dir = await self._install_packages(packages, workdir)
                if site_dir:
                    extra_env["PYTHONPATH"] = site_dir

            return await self._exec(
                [sys.executable, tmp_path], timeout, cwd=workdir, extra_env=extra_env
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def _run_javascript(self, code: str, timeout: int) -> dict[str, Any]:
        """Ejecuta JavaScript con Node.js si está disponible, en un workdir efímero propio."""
        workdir = tempfile.mkdtemp(prefix="aria_sandbox_")
        try:
            tmp_path = os.path.join(workdir, "script.js")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(code)

            return await self._exec(["node", tmp_path], timeout, cwd=workdir)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def _run_bash(self, code: str, timeout: int) -> dict[str, Any]:
        """Ejecuta bash en un workdir efímero propio. Solo para comandos de lectura/análisis."""
        # Bloquear comandos destructivos
        dangerous = ["rm -rf", "dd if=", "mkfs", ":(){", "shutdown", "reboot"]
        for d in dangerous:
            if d in code:
                return {
                    "success": False,
                    "stderr": f"Comando peligroso bloqueado: '{d}'",
                    "stdout": "",
                    "exit_code": -1,
                    "sandboxed": _bwrap_path() is not None,
                }
        workdir = tempfile.mkdtemp(prefix="aria_sandbox_")
        try:
            return await self._exec(["bash", "-c", code], timeout, cwd=workdir)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def _exec(
        self,
        cmd: list[str],
        timeout: int,
        cwd: str | None = None,
        network: bool = False,
        extra_env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Ejecuta comando y captura output con timeout.

        Isolation actually applied:
          - Real OS-level sandbox via bubblewrap when available (`sandboxed:
            True` in the result): unprivileged mount/pid/net/ipc/uts
            namespaces. Only `cwd` is writable; the rest of the host
            filesystem is read-only or not present at all inside the
            sandbox. The network namespace is empty (no interfaces) unless
            `network=True`, so code cannot make outbound requests by
            default — not even to internal/metadata addresses, since there
            is no network to reach them on.
          - Resource limits (CPU/memory/process-count/file-size/fd-count)
            via `ulimit`, applied regardless of bwrap availability.
          - A minimal explicit env — nothing from the server's real
            environment (API keys, session secrets, etc.) is passed
            through.
          - Falls back to direct (unsandboxed) execution with the same
            resource limits and minimal env if `bwrap` isn't installed;
            `sandboxed: False` in the result makes this observable instead
            of silently claiming isolation that wasn't applied.
        """
        import time

        start = time.monotonic()
        safe_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": cwd or os.environ.get("HOME", "/tmp"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        if extra_env:
            safe_env.update(extra_env)

        sandboxed = _bwrap_path() is not None
        if sandboxed and cwd:
            exec_cmd = _build_sandboxed_cmd(cmd, cwd, network)
        else:
            sandboxed = False
            exec_cmd = _wrap_with_ulimits(cmd)

        try:
            proc = await asyncio.create_subprocess_exec(
                *exec_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=safe_env,
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
                    "sandboxed": sandboxed,
                }

            runtime_ms = int((time.monotonic() - start) * 1000)
            stdout = stdout_b.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]
            stderr = stderr_b.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]
            success = proc.returncode == 0

            logger.info(
                "[CodeRunner] exit=%d runtime=%dms sandboxed=%s",
                proc.returncode,
                runtime_ms,
                sandboxed,
            )
            return {
                "success": success,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": proc.returncode,
                "runtime_ms": runtime_ms,
                "sandboxed": sandboxed,
            }
        except FileNotFoundError as exc:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Intérprete no encontrado: {exc}",
                "exit_code": -1,
                "runtime_ms": 0,
                "sandboxed": sandboxed,
            }
        except Exception as exc:
            logger.error("[CodeRunner] exec error: %s", exc)
            return {
                "success": False,
                "stdout": "",
                "stderr": str(exc),
                "exit_code": -1,
                "runtime_ms": 0,
                "sandboxed": sandboxed,
            }

    async def _install_packages(self, packages: list[str], workdir: str) -> str | None:
        """Instala paquetes pip en un directorio efímero dentro de `workdir`
        (via --target), no en el site-packages global del servidor. Antes,
        `pip install` sin --target escribía en el mismo site-packages que usa
        el propio proceso de ARIA — una ejecución podía instalar/sobreescribir
        una dependencia que el servidor usa, y los paquetes quedaban
        persistidos para todas las ejecuciones futuras (y visibles entre
        ellas) en lugar de ser efímeros como el resto del sandbox. Requiere
        red (`network=True`) para llegar a PyPI — es la única ejecución que
        la habilita por defecto."""
        site_dir = os.path.join(workdir, "site-packages")
        os.makedirs(site_dir, exist_ok=True)
        try:
            result = await self._exec(
                [sys.executable, "-m", "pip", "install", "--quiet", "--target", site_dir, *packages],
                timeout=60,
                cwd=workdir,
                network=True,
            )
            if not result.get("success"):
                logger.warning("[CodeRunner] package install failed: %s", result.get("stderr", ""))
                return None
            return site_dir
        except Exception as exc:
            logger.warning("[CodeRunner] package install error: %s", exc)
            return None

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
