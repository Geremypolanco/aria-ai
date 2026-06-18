
import logging
import subprocess
import os
import tempfile
from typing import Any, Dict

logger = logging.getLogger("aria.executor")

class CodeExecutor:
    """
    Ejecutor de Código (inspirado en OpenHands).
    
    Permite a Aria ejecutar código Python, scripts y comandos de forma segura.
    """

    def __init__(self):
        self.execution_history = []
        self.sandbox_dir = tempfile.mkdtemp()

    async def execute_python(self, code: str, timeout: int = 30) -> Dict[str, Any]:
        """Ejecuta código Python de forma segura."""
        try:
            # Crear archivo temporal
            script_file = os.path.join(self.sandbox_dir, "script.py")
            with open(script_file, "w") as f:
                f.write(code)
            
            # Ejecutar
            result = subprocess.run(
                ["python3", script_file],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            execution = {
                "code": code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "success": result.returncode == 0
            }
            
            self.execution_history.append(execution)
            logger.info(f"[CodeExecutor] Código ejecutado. Éxito: {execution['success']}")
            return execution
            
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Timeout en ejecución"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def execute_shell_command(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """Ejecuta un comando de shell."""
        # Lista de comandos prohibidos
        forbidden = ["rm -rf /", "mkfs", "shutdown", "reboot"]
        if any(f in command for f in forbidden):
            return {"success": False, "error": "Comando prohibido"}
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.sandbox_dir
            )
            
            return {
                "command": command,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "success": result.returncode == 0
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def analyze_repository(self, repo_path: str) -> Dict[str, Any]:
        """Analiza la estructura de un repositorio."""
        try:
            analysis = {
                "path": repo_path,
                "files": [],
                "structure": {}
            }
            
            for root, dirs, files in os.walk(repo_path):
                for file in files:
                    if not file.startswith("."):
                        analysis["files"].append(os.path.join(root, file))
            
            return {"success": True, "analysis": analysis}
        except Exception as e:
            return {"success": False, "error": str(e)}
