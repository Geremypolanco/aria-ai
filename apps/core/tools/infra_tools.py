import logging
import os
import shlex
import subprocess
from typing import Any

logger = logging.getLogger("aria.infra")


class InfraTools:
    """
    Herramientas de infraestructura para que ARIA gestione su propio entorno.
    """

    async def manage_files(self, action: str, path: str, content: str = None) -> dict[str, Any]:
        """Gestión avanzada de archivos (read, write, append, delete, list)."""
        try:
            if action == "read":
                with open(path) as f:
                    return {"success": True, "content": f.read()}
            elif action == "write":
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(content)
                return {"success": True, "message": f"Archivo {path} escrito"}
            elif action == "list":
                return {"success": True, "files": os.listdir(path)}
            return {"success": False, "error": f"Acción {action} no soportada"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # Only these leading binaries may run — this tool installs dependencies /
    # sets up the environment, it is NOT a general shell.
    _ALLOWED_BINARIES = {
        "pip",
        "pip3",
        "python",
        "python3",
        "npm",
        "npx",
        "yarn",
        "pnpm",
        "node",
        "apt",
        "apt-get",
        "playwright",
        "git",
        "mkdir",
        "ls",
        "cat",
        "echo",
        "which",
        "poetry",
        "uv",
    }
    # Tokens enabling chaining / destructive ops — reject outright.
    _DANGEROUS_TOKENS = (
        "&&",
        "||",
        ";",
        "|",
        "`",
        "$(",
        ">",
        "<",
        "rm ",
        "mkfs",
        "shutdown",
        "reboot",
        "dd ",
        "sudo",
        ":(){",
        "curl",
        "wget",
    )

    async def execute_system_command(self, command: str) -> dict[str, Any]:
        """Run a vetted setup/dependency command (allowlisted binary, no shell chaining)."""
        try:
            cmd = (command or "").strip()
            if not cmd:
                return {"success": False, "error": "Empty command"}
            if any(tok in cmd for tok in self._DANGEROUS_TOKENS):
                return {"success": False, "error": "Command contains a forbidden token"}
            try:
                argv = shlex.split(cmd)
            except ValueError as exc:
                return {"success": False, "error": f"Unparseable command: {exc}"}
            if not argv or argv[0] not in self._ALLOWED_BINARIES:
                return {
                    "success": False,
                    "error": "Binary not allowed for execute_system_command",
                }

            # shell=False — run the parsed argv directly (no shell-injection surface).
            result = subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=60)
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def monitor_api_health(self, endpoints: list[str]) -> dict[str, Any]:
        """Verifica si las APIs críticas están respondiendo."""
        import httpx

        results = {}
        async with httpx.AsyncClient() as client:
            for url in endpoints:
                try:
                    resp = await client.get(url, timeout=5)
                    results[url] = {"status": resp.status_code, "up": resp.status_code < 400}
                except Exception as e:
                    results[url] = {"status": "error", "up": False, "error": str(e)}
        return {"success": True, "health": results}
