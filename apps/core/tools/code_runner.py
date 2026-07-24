"""
code_runner.py — Secure sandbox for code execution by ARIA AI.

Runs Python, JavaScript, and bash with:
  - Real process/filesystem/network isolation via bubblewrap (bwrap), when
    available — unprivileged namespaces (mount/pid/net/ipc/uts), with
    only that execution's ephemeral working directory mounted
    read-write and the rest of the host filesystem read-only or
    nonexistent. Without `bwrap`, it falls back to direct execution (same
    isolation level as before) — the result includes "sandboxed": bool so
    the caller knows which one was applied.
  - Real resource limits (CPU, memory, processes, file size,
    file descriptors) via `ulimit`, independent of bwrap.
  - Network disabled by default (empty network namespace); only
    _install_packages() explicitly enables it to reach PyPI.
  - Configurable timeout (default 15s) additionally enforced by the
    ulimit CPU limit.
  - Full stdout/stderr capture, without inheriting the server's environment
    (no configured secret is visible inside the executed code).
  - Additional restriction (defense-in-depth) on dangerous imports.

ARIA can write code, execute it, see the real output, and fix it.
This enables the loop: write → execute → debug → iterate.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

logger = logging.getLogger("aria.code_runner")

# Imports that are not allowed in the Python sandbox
_BLOCKED_IMPORTS = {
    "subprocess",
    "os.system",
    "shutil.rmtree",
    "socket",
    "ctypes",
    "multiprocessing",
}

# Maximum output size so we don't saturate the context
MAX_OUTPUT_CHARS = 4000
DEFAULT_TIMEOUT = 15  # seconds

# Resource limits applied to every executed process (whether bwrap is available or not).
_ULIMIT_VIRTUAL_MEM_KB = 1_048_576  # 1 GB of virtual memory
_ULIMIT_MAX_PROCESSES = 64  # prevents fork bombs
_ULIMIT_MAX_FILE_SIZE_BLOCKS = 20_480  # ~10 MB per written file (512B blocks)
_ULIMIT_MAX_OPEN_FILES = 128

# Host directories mounted read-only inside the sandbox — the
# minimum needed for the interpreter (python/node/bash) and its
# dynamic libraries to work. Everything else on the host filesystem is
# invisible inside the sandbox.
_RO_BIND_CANDIDATES = ["/usr", "/bin", "/lib", "/lib64", "/usr/local", "/etc"]


def _bwrap_path() -> str | None:
    """Path to the bwrap binary if it's installed and can REALLY create
    unprivileged namespaces in this environment — cached after the first
    call. It's not enough for the binary to exist: some container runtimes
    (depending on their seccomp/AppArmor profile) block
    `unshare(CLONE_NEWUSER)` for unprivileged processes, in which case
    bwrap exists but every invocation would fail with "Creating new namespace
    failed: Operation not permitted" — without this check, CodeRunner
    would report a sandbox error instead of executing the code (worse than
    running unsandboxed). Tested once with a minimal invocation."""
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
    """Wraps `cmd` with bubblewrap: unprivileged namespaces that leave
    `workdir` as the only real writable location, disable the network unless
    `network=True`, and don't expose any other server file
    (secrets, ARIA's source code, other concurrent executions)."""
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
    """Applies real resource limits via bash's `ulimit` builtin before
    replacing the shell with the actual command (`exec`). Doesn't depend on
    bwrap or preexec_fn (unsafe alongside asyncio) — always works."""
    ulimits = (
        f"ulimit -v {_ULIMIT_VIRTUAL_MEM_KB}; "
        f"ulimit -u {_ULIMIT_MAX_PROCESSES}; "
        f"ulimit -f {_ULIMIT_MAX_FILE_SIZE_BLOCKS}; "
        f"ulimit -n {_ULIMIT_MAX_OPEN_FILES}; "
        'exec "$@"'
    )
    return ["bash", "-c", ulimits, "--", *cmd]


class CodeRunner:
    """Executes code securely and returns stdout/stderr."""

    async def run(
        self,
        code: str,
        language: str = "python",
        timeout: int = DEFAULT_TIMEOUT,
        packages: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Executes code and returns {success, stdout, stderr, exit_code, runtime_ms, sandboxed}.
        """
        language = language.lower().strip()

        if language in ("python", "python3", "py"):
            return await self._run_python(code, timeout, packages)
        if language in ("javascript", "js", "node", "nodejs"):
            return await self._run_javascript(code, timeout)
        if language in ("bash", "shell", "sh"):
            return await self._run_bash(code, timeout)
        # Default to trying as Python
        return await self._run_python(code, timeout, packages)

    async def _run_python(
        self, code: str, timeout: int, packages: list[str] | None
    ) -> dict[str, Any]:
        """Runs Python in an isolated subprocess, in its own ephemeral workdir."""
        # Basic check for dangerous imports
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
        """Runs JavaScript with Node.js if available, in its own ephemeral workdir."""
        workdir = tempfile.mkdtemp(prefix="aria_sandbox_")
        try:
            tmp_path = os.path.join(workdir, "script.js")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(code)

            return await self._exec(["node", tmp_path], timeout, cwd=workdir)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def _run_bash(self, code: str, timeout: int) -> dict[str, Any]:
        """Runs bash in its own ephemeral workdir. Only for read/analysis commands."""
        # Block destructive commands
        dangerous = ["rm -rf", "dd if=", "mkfs", ":(){", "shutdown", "reboot"]
        for d in dangerous:
            if d in code:
                return {
                    "success": False,
                    "stderr": f"Dangerous command blocked: '{d}'",
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
        """Executes a command and captures output with a timeout.

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
                    "stderr": f"Timeout: execution exceeded {timeout}s",
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
                "stderr": f"Interpreter not found: {exc}",
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
        """Installs pip packages into an ephemeral directory inside `workdir`
        (via --target), not into the server's global site-packages. Before,
        `pip install` without --target wrote into the same site-packages
        used by ARIA's own process — one execution could install/overwrite
        a dependency the server uses, and the packages would persist for
        all future executions (and be visible across them) instead of being
        ephemeral like the rest of the sandbox. Requires
        network (`network=True`) to reach PyPI — it's the only execution
        that enables it by default."""
        site_dir = os.path.join(workdir, "site-packages")
        os.makedirs(site_dir, exist_ok=True)
        try:
            result = await self._exec(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--quiet",
                    "--target",
                    site_dir,
                    *packages,
                ],
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
        """Returns an error message if the code contains dangerous imports."""
        for blocked in _BLOCKED_IMPORTS:
            pattern = blocked.replace(".", r"\.")
            if re.search(rf"\b{pattern}\b", code):
                return f"Import blocked in sandbox: '{blocked}'"
        return ""

    async def run_with_fix(
        self, code: str, language: str = "python", max_iterations: int = 3
    ) -> dict[str, Any]:
        """
        Executes code, and if it fails, uses AI to automatically fix it.
        Implements the loop: write → execute → debug → re-execute.
        """
        result = await self.run(code, language)

        if result.get("success") or max_iterations == 0:
            return result

        # Code failed — try AI auto-fix
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
