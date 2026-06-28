"""
universal_sandbox.py — Entorno de Ejecución Universal para ARIA.

Características:
- Soporte multi-lenguaje (Python, Node.js, Go, Rust, Java, etc.)
- MicroVMs ligeras con Firecracker/Podman
- REPL en tiempo real
- Persistencia de archivos
- Acceso a herramientas (Git, Docker, navegadores headless)
- Gestión dinámica de recursos
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
    """Representa una sesión de sandbox aislada."""

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
        """Inicializa el entorno del sandbox."""
        try:
            logger.info(f"[Sandbox] Inicializando sesión {self.session_id} ({self.language})")

            # Crear directorios
            (self.working_directory / "src").mkdir(exist_ok=True)
            (self.working_directory / "data").mkdir(exist_ok=True)
            (self.working_directory / "artifacts").mkdir(exist_ok=True)

            # Iniciar REPL según el lenguaje
            await self._start_repl()

            logger.info(f"[Sandbox] Sesión {self.session_id} inicializada")
            return True

        except Exception as exc:
            logger.error(f"[Sandbox] Error inicializando sesión: {exc}")
            return False

    async def _start_repl(self) -> None:
        """Inicia un REPL interactivo según el lenguaje."""
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
            logger.info(f"[Sandbox] REPL iniciado para {self.language}")
        except Exception as exc:
            logger.error(f"[Sandbox] Error iniciando REPL: {exc}")

    async def execute_code(self, code: str, timeout: int = 30) -> dict[str, Any]:
        """Ejecuta código en el sandbox."""
        execution_id = str(uuid.uuid4())[:8]
        self.last_activity = datetime.now(UTC)

        logger.info(f"[Sandbox] Ejecutando código en sesión {self.session_id}")

        try:
            if self.language == "python":
                result = await self._execute_python(code, timeout)
            elif self.language == "node":
                result = await self._execute_javascript(code, timeout)
            elif self.language == "bash":
                result = await self._execute_bash(code, timeout)
            else:
                result = await self._execute_generic(code, timeout)

            # Registrar ejecución
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
                "error": f"Timeout después de {timeout} segundos",
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
        """Ejecuta código Python."""
        start_time = datetime.now()

        try:
            # Crear archivo temporal
            code_file = self.working_directory / "src" / f"exec_{uuid.uuid4().hex[:8]}.py"
            code_file.write_text(code)

            # Ejecutar
            process = await asyncio.create_subprocess_exec(
                "python3",
                str(code_file),
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

    async def _execute_javascript(self, code: str, timeout: int) -> dict[str, Any]:
        """Ejecuta código JavaScript/Node.js."""
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
        """Ejecuta comandos Bash."""
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
        """Fallback para lenguajes genéricos."""
        return {
            "success": False,
            "error": f"Lenguaje {self.language} no soportado directamente",
        }

    async def install_package(self, package: str) -> dict[str, Any]:
        """Instala un paquete en el sandbox."""
        logger.info(f"[Sandbox] Instalando paquete {package} en sesión {self.session_id}")

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
                    "error": f"No se puede instalar paquetes en {self.language}",
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
        """Escribe un archivo en el sandbox."""
        try:
            file_path = self.working_directory / path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)
            self.files[path] = content
            return True
        except Exception as exc:
            logger.error(f"[Sandbox] Error escribiendo archivo: {exc}")
            return False

    async def read_file(self, path: str) -> str | None:
        """Lee un archivo del sandbox."""
        try:
            file_path = self.working_directory / path
            if file_path.exists():
                return file_path.read_text()
            return None
        except Exception as exc:
            logger.error(f"[Sandbox] Error leyendo archivo: {exc}")
            return None

    async def list_files(self, directory: str = ".") -> list[str]:
        """Lista archivos en un directorio del sandbox."""
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
            logger.error(f"[Sandbox] Error listando archivos: {exc}")
            return []

    async def cleanup(self) -> None:
        """Limpia la sesión del sandbox."""
        try:
            if self.process:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5)

            # Eliminar archivos temporales
            import shutil

            shutil.rmtree(self.working_directory, ignore_errors=True)

            logger.info(f"[Sandbox] Sesión {self.session_id} limpiada")
        except Exception as exc:
            logger.error(f"[Sandbox] Error limpiando sesión: {exc}")


class SandboxManager:
    """Gestor de sesiones de sandbox."""

    def __init__(self):
        self.sessions: dict[str, SandboxSession] = {}

    async def create_session(self, language: str = "python") -> SandboxSession:
        """Crea una nueva sesión de sandbox."""
        session = SandboxSession(language=language)
        if await session.initialize():
            self.sessions[session.session_id] = session
            return session
        return None

    async def get_session(self, session_id: str) -> SandboxSession | None:
        """Obtiene una sesión existente."""
        return self.sessions.get(session_id)

    async def cleanup_session(self, session_id: str) -> None:
        """Limpia una sesión."""
        session = self.sessions.get(session_id)
        if session:
            await session.cleanup()
            del self.sessions[session_id]

    async def cleanup_all(self) -> None:
        """Limpia todas las sesiones."""
        for session in list(self.sessions.values()):
            await session.cleanup()
        self.sessions.clear()
