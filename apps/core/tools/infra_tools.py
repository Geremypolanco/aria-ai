import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger("aria.infra")


class InfraTools:
    """
    Infrastructure tools for ARIA to manage its own environment.
    """

    async def manage_files(self, action: str, path: str, content: str = None) -> dict[str, Any]:
        """Advanced file management (read, write, append, delete, list)."""
        try:
            if action == "read":
                with open(path) as f:
                    return {"success": True, "content": f.read()}
            elif action == "write":
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(content)
                return {"success": True, "message": f"File {path} written"}
            elif action == "list":
                return {"success": True, "files": os.listdir(path)}
            return {"success": False, "error": f"Action {action} not supported"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def execute_system_command(self, command: str) -> dict[str, Any]:
        """Executes system commands to install dependencies or configure the environment."""
        try:
            # List of commands forbidden for security reasons
            forbidden = ["rm -rf /", "mkfs", "shutdown"]
            if any(f in command for f in forbidden):
                return {"success": False, "error": "Command forbidden for security reasons"}

            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def monitor_api_health(self, endpoints: list[str]) -> dict[str, Any]:
        """Checks whether critical APIs are responding."""
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
