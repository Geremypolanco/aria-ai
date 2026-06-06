"""
enhanced_dev_agent.py — Agente de Desarrollo Mejorado para ARIA.

Combina las capacidades de:
- Generación de código multi-lenguaje
- Ejecución en sandbox
- Depuración y testing
- Despliegue automático
- Análisis de repositorios
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from apps.core.agents.base_agent import BaseAgent
from apps.core.sandbox.universal_sandbox import SandboxManager
from apps.core.tools.ai_client import AIModel, get_ai_client
from apps.core.tools.aria_tools import tool_registry

logger = logging.getLogger("aria.dev_agent")


class EnhancedDevAgent(BaseAgent):
    """Agente de desarrollo con capacidades completas de Replit + Manus."""

    def __init__(self) -> None:
        super().__init__(
            name="enhanced_dev",
            description="Desarrollo de software completo — código, testing, despliegue",
            capabilities=[
                "code_generation",
                "code_execution",
                "testing",
                "debugging",
                "deployment",
                "repository_analysis",
                "architecture_design",
                "refactoring",
            ],
        )
        self.sandbox_manager = SandboxManager()

    async def _execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Punto de entrada principal."""
        task = context.get("task", "")
        task_type = context.get("task_type", "general")
        language = context.get("language", "python")

        logger.info(f"[DevAgent] Ejecutando tarea: {task[:80]} ({language})")

        if "generate" in task_type.lower():
            return await self._generate_code(task, language, context)
        elif "execute" in task_type.lower():
            return await self._execute_code(task, language, context)
        elif "test" in task_type.lower():
            return await self._test_code(task, language, context)
        elif "deploy" in task_type.lower():
            return await self._deploy(task, context)
        else:
            return await self._general_task(task, language, context)

    async def _generate_code(self, task: str, language: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Genera código completo para una tarea."""
        ai = get_ai_client()
        if not ai:
            return {"success": False, "error": "AI client no disponible"}

        system_prompt = f"""Eres un experto desarrollador de {language}. 
Genera código limpio, bien documentado y production-ready.
Incluye manejo de errores, logging y tests unitarios.
Responde SOLO con código válido."""

        user_prompt = f"""Genera código {language} para:

{task}

REQUISITOS:
- Código modular y reutilizable
- Documentación clara
- Manejo de errores
- Tests unitarios incluidos
- Sigue best practices de {language}"""

        try:
            response = await ai.complete(
                system=system_prompt,
                user=user_prompt,
                model=AIModel.CODE,
                max_tokens=4000,
            )

            # Extraer código del response
            code = self._extract_code(response)

            return {
                "success": True,
                "code": code,
                "language": language,
                "task": task,
            }

        except Exception as exc:
            logger.error(f"[DevAgent] Error generando código: {exc}")
            return {"success": False, "error": str(exc)}

    async def _execute_code(self, code: str, language: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta código en un sandbox aislado."""
        try:
            # Crear sesión de sandbox
            session = await self.sandbox_manager.create_session(language=language)
            if not session:
                return {"success": False, "error": "No se pudo crear sesión de sandbox"}

            # Instalar dependencias si es necesario
            dependencies = context.get("dependencies", [])
            for dep in dependencies:
                await session.install_package(dep)

            # Ejecutar código
            result = await session.execute_code(code, timeout=60)

            # Limpiar
            await self.sandbox_manager.cleanup_session(session.session_id)

            return {
                "success": result.get("success", False),
                "output": result.get("output", ""),
                "error": result.get("error", ""),
                "execution_time": result.get("execution_time", 0),
                "session_id": session.session_id,
            }

        except Exception as exc:
            logger.error(f"[DevAgent] Error ejecutando código: {exc}")
            return {"success": False, "error": str(exc)}

    async def _test_code(self, code: str, language: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta tests sobre código."""
        try:
            session = await self.sandbox_manager.create_session(language=language)
            if not session:
                return {"success": False, "error": "No se pudo crear sesión de sandbox"}

            # Instalar framework de testing
            if language == "python":
                await session.install_package("pytest")
                test_cmd = "pytest -v"
            elif language == "node":
                await session.install_package("jest")
                test_cmd = "npm test"
            else:
                test_cmd = "test"

            # Escribir código de test
            test_file = f"test_code.{self._get_extension(language)}"
            await session.write_file(test_file, code)

            # Ejecutar tests
            result = await session.execute_code(test_cmd, timeout=120)

            await self.sandbox_manager.cleanup_session(session.session_id)

            return {
                "success": result.get("success", False),
                "output": result.get("output", ""),
                "error": result.get("error", ""),
                "test_results": self._parse_test_results(result.get("output", "")),
            }

        except Exception as exc:
            logger.error(f"[DevAgent] Error ejecutando tests: {exc}")
            return {"success": False, "error": str(exc)}

    async def _deploy(self, project_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Despliega una aplicación."""
        deployment_target = context.get("deployment_target", "vercel")
        token = context.get("deployment_token", "")

        try:
            deployment_tool = tool_registry.get_tool("deployment")
            if not deployment_tool:
                return {"success": False, "error": "Deployment tool no disponible"}

            if deployment_target == "vercel":
                result = await deployment_tool.deploy_to_vercel(project_path, token)
            elif deployment_target == "fly":
                app_name = context.get("app_name", "aria-app")
                result = await deployment_tool.deploy_to_fly(project_path, app_name)
            else:
                return {"success": False, "error": f"Deployment target no soportado: {deployment_target}"}

            return {
                "success": result.get("success", False),
                "output": result.get("output", ""),
                "error": result.get("error", ""),
                "deployment_target": deployment_target,
            }

        except Exception as exc:
            logger.error(f"[DevAgent] Error desplegando: {exc}")
            return {"success": False, "error": str(exc)}

    async def _general_task(self, task: str, language: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Maneja tareas generales de desarrollo."""
        # Generar código primero
        code_result = await self._generate_code(task, language, context)
        if not code_result.get("success"):
            return code_result

        # Ejecutar el código generado
        code = code_result.get("code", "")
        exec_result = await self._execute_code(code, language, context)

        return {
            "success": exec_result.get("success", False),
            "code": code,
            "output": exec_result.get("output", ""),
            "error": exec_result.get("error", ""),
        }

    def _extract_code(self, response: str) -> str:
        """Extrae código de un response de IA."""
        # Buscar bloques de código markdown
        import re
        pattern = r"```(?:python|javascript|node|go|rust|java)?\n(.*?)```"
        matches = re.findall(pattern, response, re.DOTALL)
        if matches:
            return matches[0].strip()
        return response

    def _get_extension(self, language: str) -> str:
        """Obtiene la extensión de archivo para un lenguaje."""
        extensions = {
            "python": "py",
            "node": "js",
            "javascript": "js",
            "go": "go",
            "rust": "rs",
            "java": "java",
            "cpp": "cpp",
            "csharp": "cs",
        }
        return extensions.get(language, language)

    def _parse_test_results(self, output: str) -> Dict[str, Any]:
        """Parsea resultados de tests."""
        # Implementación simplificada
        return {
            "raw_output": output,
            "passed": "passed" in output.lower(),
        }

    async def cleanup(self) -> None:
        """Limpia recursos."""
        await self.sandbox_manager.cleanup_all()
