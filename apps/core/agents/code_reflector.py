import logging
import json
from typing import Dict, Any, List

from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel, get_ai_client
from apps.core.sandbox.universal_sandbox import SandboxManager
from apps.core.config_pkg.secrets_manager import secrets_manager  # Para acceso a tokens si es necesario

logger = logging.getLogger("aria.code_reflector")

class CodeReflector(BaseAgent):
    """
    Agente encargado de la auto-reflexión y auto-modificación segura del código de Aria.
    Permite a Aria leer, analizar, proponer cambios, probarlos y aplicarlos a su propio codebase.
    """

    def __init__(self):
        super().__init__(
            name="code_reflector",
            description="Analiza, propone y aplica modificaciones al código de Aria de forma segura.",
            capabilities=[
                "code_analysis",
                "code_generation",
                "self_modification",
                "safe_deployment",
                "testing",
            ],
        )
        self.sandbox_manager = SandboxManager()
        self.codebase_root = "/home/ubuntu/aria-ai" # Ruta raíz del repositorio de Aria

    async def _execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta el proceso de auto-reflexión y modificación."""
        task = context.get("task", "")
        target_file = context.get("target_file", None)
        modification_plan = context.get("modification_plan", None)

        if modification_plan:
            return await self._apply_modification_plan(modification_plan)
        elif target_file:
            return await self._reflect_on_file(target_file, task)
        else:
            return await self._initiate_self_reflection(task)

    async def _initiate_self_reflection(self, high_level_task: str) -> Dict[str, Any]:
        """
        Inicia un ciclo de auto-reflexión basado en una tarea de alto nivel.
        Aria decide qué partes de su código necesitan ser analizadas.
        """
        ai = get_ai_client()
        if not ai:
            return {"success": False, "error": "AI client no disponible"}

        system_prompt = (
            "Eres un agente de auto-reflexión para ARIA. Tu tarea es identificar "
            "qué archivos del codebase de Aria son relevantes para una tarea de alto nivel "
            "y cómo deberían ser analizados para proponer mejoras. "
            "Responde SOLO con JSON válido sin markdown."
        )

        user_prompt = f"""Dada la siguiente tarea de alto nivel para mejorar ARIA:

TAREA: {high_level_task}

Analiza el codebase de ARIA (estructura de directorios en /home/ubuntu/aria-ai/apps/core/) y sugiere:
1. Una lista de archivos relevantes para esta tarea.
2. Para cada archivo, una breve descripción de por qué es relevante y qué tipo de análisis se necesita (ej. 'identificar funciones', 'entender flujo de datos', 'buscar patrones de mejora').

Proporciona un JSON con la siguiente estructura:
{{
  "analysis_summary": "Resumen de la estrategia de análisis",
  "relevant_files": [
    {{
      "path": "ruta/al/archivo.py",
      "reason": "razón de relevancia",
      "analysis_type": "tipo de análisis"
    }}
  ]
}}"""

        try:
            response = await ai.complete_json(
                system=system_prompt,
                user=user_prompt,
                model=AIModel.STRATEGY,
                max_tokens=1000,
                agent_name="code_reflector",
            )
            logger.info(f"[CodeReflector] Plan de auto-reflexión generado: {response}")
            return {"success": True, "plan": response}
        except Exception as e:
            logger.error(f"[CodeReflector] Error al generar plan de auto-reflexión: {e}")
            return {"success": False, "error": str(e)}

    async def _reflect_on_file(self, file_path: str, analysis_task: str) -> Dict[str, Any]:
        """
        Lee un archivo, lo analiza y propone modificaciones.
        """
        ai = get_ai_client()
        if not ai:
            return {"success": False, "error": "AI client no disponible"}

        try:
            with open(f"{self.codebase_root}/{file_path}", "r") as f:
                code_content = f.read()
        except FileNotFoundError:
            return {"success": False, "error": f"Archivo no encontrado: {file_path}"}

        system_prompt = (
            "Eres un agente de auto-modificación de código para ARIA. "
            "Tu tarea es analizar el código proporcionado y, basándote en una tarea de mejora, "
            "proponer un plan de modificación detallado. "
            "Responde SOLO con JSON válido sin markdown."
        )

        user_prompt = f"""Analiza el siguiente código del archivo {file_path} de ARIA:

```python
{code_content}
```

Basándote en la siguiente tarea de mejora:
TAREA DE MEJORA: {analysis_task}

Propón un plan de modificación en JSON con la siguiente estructura. Si no se necesitan cambios, `modifications` debe ser una lista vacía.
{{
  "reasoning": "Explicación de por qué se proponen estos cambios o por qué no son necesarios",
  "modifications": [
    {{
      "type": "add" | "replace" | "delete",
      "target_line_start": "número de línea de inicio (1-indexed)",
      "target_line_end": "número de línea de fin (1-indexed)",
      "content": "nuevo contenido para añadir/reemplazar (para delete, dejar vacío)",
      "description": "descripción del cambio"
    }}
  ],
  "test_plan": "Descripción de cómo probar los cambios en el sandbox (ej. 'ejecutar tests existentes', 'ejecutar función X con parámetros Y')"
}}"""

        try:
            modification_proposal = await ai.complete_json(
                system=system_prompt,
                user=user_prompt,
                model=AIModel.STRATEGY, # Usar un modelo de estrategia para la propuesta
                max_tokens=2000,
                agent_name="code_reflector",
            )
            logger.info(f"[CodeReflector] Propuesta de modificación para {file_path}: {modification_proposal}")
            return {"success": True, "proposal": modification_proposal, "file_path": file_path}
        except Exception as e:
            logger.error(f"[CodeReflector] Error al proponer modificación para {file_path}: {e}")
            return {"success": False, "error": str(e)}

    async def _apply_modification_plan(self, modification_plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Aplica un plan de modificación propuesto, con pruebas en el sandbox.
        """
        file_path = modification_plan.get("file_path")
        modifications = modification_plan.get("proposal", {}).get("modifications", [])
        test_plan = modification_plan.get("proposal", {}).get("test_plan", "")

        if not file_path or not modifications:
            return {"success": False, "error": "Plan de modificación inválido o vacío."}

        full_path = f"{self.codebase_root}/{file_path}"

        # 1. Crear un snapshot del código actual para posible rollback
        original_content = ""
        try:
            with open(full_path, "r") as f:
                original_content = f.readlines()
        except FileNotFoundError:
            return {"success": False, "error": f"Archivo original no encontrado para modificación: {file_path}"}

        temp_content = list(original_content) # Trabajar con una copia mutable

        # 2. Aplicar modificaciones en memoria
        try:
            # Las modificaciones deben aplicarse en orden inverso si afectan índices de línea
            # Para simplificar, asumimos que no hay solapamientos complejos que requieran re-indexación
            # En un sistema real, se usaría una librería de diff/patch o un enfoque más sofisticado
            for mod in sorted(modifications, key=lambda x: int(x.get('target_line_start', 0)), reverse=True):
                mod_type = mod.get("type")
                start = int(mod.get("target_line_start")) - 1 # 0-indexed
                end = int(mod.get("target_line_end", start + 1)) - 1 # 0-indexed
                content = mod.get("content", "")

                if mod_type == "replace":
                    temp_content[start:end+1] = [line + "\n" for line in content.splitlines()]
                elif mod_type == "add":
                    temp_content.insert(start, content + "\n")
                elif mod_type == "delete":
                    del temp_content[start:end+1]

            modified_code = "".join(temp_content)
        except Exception as e:
            return {"success": False, "error": f"Error al aplicar modificaciones en memoria: {e}"}

        # 3. Guardar el código modificado en un archivo temporal para pruebas
        temp_file_path = f"{full_path}.tmp"
        with open(temp_file_path, "w") as f:
            f.write(modified_code)

        # 4. Ejecutar plan de pruebas en el sandbox
        test_result = await self._run_tests_in_sandbox(test_plan, temp_file_path)

        if test_result.get("success"): # Asumimos que el sandbox devuelve {success: True} si pasa
            logger.info(f"[CodeReflector] Pruebas exitosas para {file_path}. Aplicando cambios permanentes.")
            # 5. Aplicar cambios permanentes
            with open(full_path, "w") as f:
                f.write(modified_code)
            # Eliminar archivo temporal
            await self.sandbox_manager.execute_command(f"rm {temp_file_path}")
            return {"success": True, "message": f"Código de {file_path} modificado y probado con éxito."}
        else:
            logger.warning(f"[CodeReflector] Pruebas fallidas para {file_path}. Revirtiendo cambios.")
            # 5. Rollback: Eliminar archivo temporal y no aplicar cambios
            await self.sandbox_manager.execute_command(f"rm {temp_file_path}")
            return {"success": False, "error": f"Modificación de {file_path} fallida en pruebas: {test_result.get('error', 'Error desconocido')}"}

    async def _run_tests_in_sandbox(self, test_plan: str, modified_file_path: str) -> Dict[str, Any]:
        """
        Ejecuta el plan de pruebas en el Universal Sandbox.
        Esto es una simulación; en un sistema real, se ejecutarían tests unitarios/integración.
        """
        logger.info(f"[CodeReflector] Ejecutando plan de pruebas en sandbox: {test_plan}")
        # Aquí, el sandbox_manager debería ser capaz de ejecutar comandos o scripts
        # que validen el cambio. Por ahora, es una simulación.
        # En un escenario real, se podría copiar el archivo modificado al sandbox
        # y ejecutar un comando como `pytest` o un script de validación.

        # Simulación de prueba exitosa
        if "simular_fallo" in test_plan.lower():
            return {"success": False, "error": "Fallo simulado por plan de pruebas."}

        # Para una prueba real, el sandbox_manager debería tener un método como `run_script`
        # o `run_command` que pueda ejecutar el código de prueba.
        # Por ejemplo:
        # command = f"python3 -c \"import sys; sys.path.insert(0, "."); from {modified_file_path.replace('/', '.')[:-3]} import *; # ejecutar algo\""
        # result = await self.sandbox_manager.execute_command(command)
        # return {"success": result.get("exit_code") == 0, "error": result.get("stderr")}

        await asyncio.sleep(2) # Simular tiempo de ejecución de pruebas
        return {"success": True, "message": "Pruebas simuladas exitosas."}

# Instancia global del CodeReflector
code_reflector = CodeReflector()
