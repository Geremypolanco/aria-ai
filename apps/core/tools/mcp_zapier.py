import logging
import json
import subprocess
from typing import Any, Dict, List, Optional
from apps.core.config import settings

logger = logging.getLogger("aria.tools.mcp_zapier")

class MCPZapierTool:
    """
    Herramienta para que ARIA ejecute acciones de Zapier directamente vía MCP CLI.
    Esto permite usar Gmail, Shopify, etc., sin necesidad de configurar Zaps manuales.
    """
    
    def __init__(self):
        self.server_name = "zapier"

    def _run_mcp(self, command: str, args: List[str]) -> Dict[str, Any]:
        full_cmd = ["manus-mcp-cli", "tool", command] + args + ["--server", self.server_name]
        try:
            result = subprocess.run(full_cmd, capture_output=True, text=True, check=True)
            # El resultado suele guardarse en un archivo o imprimirse en stdout
            # Intentamos parsear la salida JSON si existe
            try:
                return json.loads(result.stdout)
            except:
                return {"raw_output": result.stdout, "success": True}
        except subprocess.CalledProcessError as e:
            logger.error(f"MCP Error: {e.stderr}")
            return {"success": False, "error": e.stderr}

    async def list_actions(self) -> List[Dict[str, Any]]:
        """Lista todas las acciones habilitadas en Zapier MCP."""
        res = self._run_mcp("call", ["list_enabled_zapier_actions", "--input", "{}"])
        return res.get("apps", [])

    async def execute_action(self, action_key: str, selected_api: str, params: Dict[str, Any], is_write: bool = True) -> Dict[str, Any]:
        """Ejecuta una acción de Zapier (lectura o escritura)."""
        tool = "execute_zapier_write_action" if is_write else "execute_zapier_read_action"
        input_data = {
            "action": action_key,
            "selected_api": selected_api,
            "params": params,
            "instructions": f"Ejecutar {action_key} con los parámetros proporcionados.",
            "output": "json"
        }
        
        res = self._run_mcp("call", [tool, "--input", json.dumps(input_data)])
        return res
