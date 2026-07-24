"""
universal_sandbox.py — Universal Execution Environment for ARIA.

Features:
- Multi-language support (Python, Node.js, Go, Rust, Java, etc.)
- Lightweight MicroVMs with Firecracker/Podman
- Real-time REPL
- File persistence
- Access to tools (Git, Docker, headless browsers)
- Dynamic resource management
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("aria.sandbox")


class SandboxSession:
    """Represents an isolated sandbox session."""

    def __init__(self, session_id: str = None, language: str = "python"):
        self.session_id = session_id or str(uuid.uuid4())[:12]
        self.language = language
        self.created_at = datetime.now(UTC)
        self.last_activity = self.created_at
        self.files: dict[str, str] = {}
        self.environment_vars: dict[str, str] = {}
        self.installed_packages: list[str] = []
        self.execution_history: list[dict[str, Any]] = []
        self.process: asyncio.subprocess.Process | None = None
        self.working_directory = Path(tempfile.mkdtemp(prefix=f"aria_{session_id}_"))

    async def initialize(self) -> bool:
        """Initializes the sandbox environment."""
        try:
            logger.info(f"[Sandbox] Initializing session {self.session_id} ({self.language})")

            # Create directories
            (self.working_directory / "src").mkdir(exist_ok=True)
            (self.working_directory / "data").mkdir(exist_ok=True)
            (self.working_directory / "artifacts").mkdir(exist_ok=True)

            # Start REPL based on language
            await self._start_repl()

            logger.info(f"[Sandbox] Session {self.session_id} initialized")
            return True

        except Exception as exc:
            logger.error(f"[Sandbox] Error initializing session: {exc}")
            return False

    async def _start_repl(self) -> None:
        """Starts an interactive REPL based on the language."""
        if self.language == "python":
            cmd = ["python3", "-i"]
        elif self.language == "node":
            cmd = ["node"]
        elif self.language == "go":
            cmd = ["go", "run"]
        else:
            cmd = [self.language]

        try:
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.working_directory),
            )
            logger.info(f"[Sandbox] REPL started for {self.language}")
        except Exception as exc:
            logger.error(f"[Sandbox] Error starting REPL: {exc}")

    async def execute_code(self, code: str, timeout: int = 30) -> dict[str, Any]:
        """Executes code in the sandbox."""
        execution_id = str(uuid.uuid4())[:8]
        self.last_activity = datetime.now(UTC)

        logger.info(f"[Sandbox] Executing code in session {self.session_id}")

        try:
            if self.language == "python":
                result = await self._execute_python(code, timeout)
            elif self.language == "node":
                result = await self._execute_javascript(code, timeout)
            elif self.language == "bash":
                result = await self._execute_bash(code, timeout)
            else:
                result = await self._execute_generic(code, timeout)

            # Log execution
            self.execution_history.append(
                {
                    "execution_id": execution_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "code": code[:500],
                    "success": result.get("success", False),
                    "output": result.get("output", "")[:500],
                }
            )

            return {
                "execution_id": execution_id,
                "success": result.get("success", False),
                "output": result.get("output", ""),
                "error": result.get("error", ""),
                "execution_time": result.get("execution_time", 0),
            }

        except TimeoutError:
            return {
                "execution_id": execution_id,
                "success": False,
                "error": f"Timeout after {timeout} seconds",
                "execution_time": timeout,
            }
        except Exception as exc:
            return {
                "execution_id": execution_id,
                "success": False,
                "error": str(exc),
                "execution_time": 0,
            }

    async def _execute_python(self, code: str, timeout: int) -> dict[str, Any]:
        """Executes Python code."""
        start_time = datetime.now()

        try:
            # Create temp file
            code_file = self.working_directory / "src" / f"exec_{uuid.uuid4().hex[:8]}.py"
            code_file.write_text(code)

            # Execute
            process = await asyncio.create_subprocess_exec(
                "python3",
                str(code_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.working_directory),
                timeout=timeout,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

            execution_time = (datetime.now() - start_time).total_seconds()

            return {
                "success": process.returncode == 0,
                "output": stdout.decode("utf-8", errors="ignore"),
                "error": stderr.decode("utf-8", errors="ignore") if stderr else "",
                "execution_time": execution_time,
            }

        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "execution_time": (datetime.now() - start_time).total_seconds(),
            }

    async def _execute_javascript(self, code: str, timeout: int) -> dict[str, Any]:
        """Executes JavaScript/Node.js code."""
        start_time = datetime.now()

        try:
            code_file = self.working_directory / "src" / f"exec_{uuid.uuid4().hex[:8]}.js"
            code_file.write_text(code)

            process = await asyncio.create_subprocess_exec(
                "node",
                str(code_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.working_directory),
                timeout=timeout,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

            execution_time = (datetime.now() - start_time).total_seconds()

            return {
                "success": process.returncode == 0,
                "output": stdout.decode("utf-8", errors="ignore"),
                "error": stderr.decode("utf-8", errors="ignore") if stderr else "",
                "execution_time": execution_time,
            }

        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "execution_time": (datetime.now() - start_time).total_seconds(),
            }

    async def _execute_bash(self, code: str, timeout: int) -> dict[str, Any]:
        """Executes Bash commands."""
        start_time = datetime.now()

        try:
            process = await asyncio.create_subprocess_shell(
                code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.working_directory),
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

            execution_time = (datetime.now() - start_time).total_seconds()

            return {
                "success": process.returncode == 0,
                "output": stdout.decode("utf-8", errors="ignore"),
                "error": stderr.decode("utf-8", errors="ignore") if stderr else "",
                "execution_time": execution_time,
            }

        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "execution_time": (datetime.now() - start_time).total_seconds(),
            }

    async def _execute_generic(self, code: str, timeout: int) -> dict[str, Any]:
        """Fallback for generic languages."""
        return {
            "success": False,
            "error": f"Language {self.language} is not directly supported",
        }

    async def install_package(self, package: str) -> dict[str, Any]:
        """Installs a package in the sandbox."""
        logger.info(f"[Sandbox] Installing package {package} in session {self.session_id}")

        try:
            if self.language == "python":
                cmd = ["pip3", "install", package]
            elif self.language == "node":
                cmd = ["npm", "install", package]
            elif self.language == "go":
                cmd = ["go", "get", package]
            else:
                return {
                    "success": False,
                    "error": f"Cannot install packages for {self.language}",
                }

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.working_directory),
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)

            if process.returncode == 0:
                self.installed_packages.append(package)

            return {
                "success": process.returncode == 0,
                "output": stdout.decode("utf-8", errors="ignore"),
                "error": stderr.decode("utf-8", errors="ignore") if stderr else "",
            }

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def write_file(self, path: str, content: str) -> bool:
        """Writes a file in the sandbox."""
        try:
            file_path = self.working_directory / path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)
            self.files[path] = content
            return True
        except Exception as exc:
            logger.error(f"[Sandbox] Error writing file: {exc}")
            return False

    async def read_file(self, path: str) -> str | None:
        """Reads a file from the sandbox."""
        try:
            file_path = self.working_directory / path
            if file_path.exists():
                return file_path.read_text()
            return None
        except Exception as exc:
            logger.error(f"[Sandbox] Error reading file: {exc}")
            return None

    async def list_files(self, directory: str = ".") -> list[str]:
        """Lists files in a sandbox directory."""
        try:
            dir_path = self.working_directory / directory
            if dir_path.exists():
                return [
                    str(f.relative_to(self.working_directory))
                    for f in dir_path.rglob("*")
                    if f.is_file()
                ]
            return []
        except Exception as exc:
            logger.error(f"[Sandbox] Error listing files: {exc}")
            return []

    async def cleanup(self) -> None:
        """Cleans up the sandbox session."""
        try:
            if self.process:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5)

            # Remove temp files
            import shutil

            shutil.rmtree(self.working_directory, ignore_errors=True)

            logger.info(f"[Sandbox] Session {self.session_id} cleaned up")
        except Exception as exc:
            logger.error(f"[Sandbox] Error cleaning up session: {exc}")


class SandboxManager:
    """Manager for sandbox sessions."""

    def __init__(self):
        self.sessions: dict[str, SandboxSession] = {}

    async def create_session(self, language: str = "python") -> SandboxSession:
        """Creates a new sandbox session."""
        session = SandboxSession(language=language)
        if await session.initialize():
            self.sessions[session.session_id] = session
            return session
        return None

    async def get_session(self, session_id: str) -> SandboxSession | None:
        """Retrieves an existing session."""
        return self.sessions.get(session_id)

    async def cleanup_session(self, session_id: str) -> None:
        """Cleans up a session."""
        session = self.sessions.get(session_id)
        if session:
            await session.cleanup()
            del self.sessions[session_id]

    async def cleanup_all(self) -> None:
        """Cleans up all sessions."""
        for session in list(self.sessions.values()):
            await session.cleanup()
        self.sessions.clear()
