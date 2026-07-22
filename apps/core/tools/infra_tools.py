import logging
import os
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

    async def execute_system_command(self, command: str) -> dict[str, Any]:
        """Ejecuta comandos de sistema para instalar dependencias o configurar el entorno."""
        try:
            # Lista de comandos prohibidos por seguridad
            forbidden = ["rm -rf /", "mkfs", "shutdown"]
            if any(f in command for f in forbidden):
                return {"success": False, "error": "Comando prohibido por seguridad"}

            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
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

        from apps.core.tools.web_tools import _assert_public_url

        results = {}
        async with httpx.AsyncClient() as client:
            for url in endpoints:
                try:
                    await _assert_public_url(url)
                    resp = await client.get(url, timeout=5, follow_redirects=False)
                    results[url] = {"status": resp.status_code, "up": resp.status_code < 400}
                except Exception as e:
                    results[url] = {"status": "error", "up": False, "error": str(e)}
        return {"success": all(r.get("up") for r in results.values()), "health": results}
