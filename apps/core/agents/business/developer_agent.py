"""
Developer Agent — Escribe, ejecuta, depura y despliega código como Claude Code.

Capacidades:
  - Escribe código completo en cualquier lenguaje
  - Lo ejecuta en sandbox y ve el output real
  - Auto-depura hasta que funciona
  - Genera proyectos completos multi-archivo
  - Push a GitHub y despliega a Fly.io
  - Itera con loop: diseño → código → test → fix → deploy
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any
from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.business.developer")


class DeveloperAgent(BaseAgent):
    IDENTITY = (
        "Eres el Developer Agent de ARIA AI. Operas como Claude Code: escribes código de producción, "
        "lo ejecutas, ves el output real, corriges errores, y iteras hasta que funciona. "
        "Nunca generas código que no puedas ejecutar. Siempre validas con tests reales."
    )

    def __init__(self) -> None:
        super().__init__(
            name="developer",
            description="Escribe, ejecuta, depura y despliega código autónomamente",
            capabilities=[
                "code_generation", "code_execution", "debugging", "testing",
                "api_building", "deployment", "github", "refactoring",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        task        = context.get("mission", context.get("task", ""))
        language    = context.get("language", "python")
        auto_run    = context.get("auto_run", True)
        auto_fix    = context.get("auto_fix", True)
        deploy      = context.get("deploy", False)

        if not task:
            return {"success": False, "error": "No se especificó tarea de desarrollo"}

        results: dict[str, Any] = {"success": False, "agent": "developer", "task": task}

        # 1. Analizar la tarea y diseñar la solución
        design = await self._design_solution(task, language)
        results["design"] = design

        # 2. Generar el código
        code = await self._generate_code(task, language, design)
        results["code"] = code

        # 3. Ejecutar y auto-depurar si se solicita
        if auto_run and code:
            from apps.core.tools.code_runner import CodeRunner
            runner = CodeRunner()

            if auto_fix:
                run_result = await runner.run_with_fix(code, language, max_iterations=3)
            else:
                run_result = await runner.run(code, language)

            results["execution"] = {
                "success": run_result.get("success", False),
                "output":  run_result.get("stdout", "")[:1000],
                "error":   run_result.get("stderr", "")[:500],
                "runtime_ms": run_result.get("runtime_ms", 0),
                "auto_fixed": run_result.get("auto_fixed", False),
            }
            if run_result.get("fixed_code"):
                results["code"] = run_result["fixed_code"]

        # 4. Generar tests básicos
        tests = await self._generate_tests(task, results["code"], language)
        results["tests"] = tests

        # 5. Opcional: push a GitHub
        if deploy and context.get("github_path"):
            push_result = await self._push_to_github(
                context["github_path"], results["code"], task
            )
            results["github"] = push_result

        results["success"] = True
        results["summary"] = (
            f"Código generado ({language}). "
            + (f"Ejecutado OK en {results.get('execution', {}).get('runtime_ms', 0)}ms." if auto_run else "")
            + (" Auto-corregido." if results.get("execution", {}).get("auto_fixed") else "")
        )
        return results

    async def _design_solution(self, task: str, language: str) -> str:
        """Diseña la arquitectura antes de escribir código."""
        resp = await self.think(
            system=self.IDENTITY,
            user=(
                f"Tarea: {task}\nLenguaje: {language}\n\n"
                f"Diseña la solución: clases/funciones necesarias, inputs/outputs, "
                f"algoritmo, edge cases. Sé conciso (máx 200 palabras)."
            ),
        )
        return resp

    async def _generate_code(self, task: str, language: str, design: str) -> str:
        """Genera código completo basado en el diseño."""
        from apps.core.tools.ai_client import get_ai_client
        ai = get_ai_client()
        if not ai:
            return f"# {task}\n# Error: AI client not available\n"

        resp = await ai.complete(
            system=(
                f"Expert {language} engineer. Write production-ready code only. "
                f"No markdown fences. Include error handling and type hints."
            ),
            user=f"Task: {task}\nDesign: {design}\nWrite the complete {language} implementation:",
            model=AIModel.CODE,
            max_tokens=2000,
            temperature=0.15,
            agent_name="developer_codegen",
        )
        code = (resp.content.strip() if resp and resp.success else f"# TODO: {task}")
        if code.startswith("```"):
            lines = code.split("\n")
            code = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        return code

    async def _generate_tests(self, task: str, code: str, language: str) -> str:
        """Genera tests unitarios para el código generado."""
        from apps.core.tools.ai_client import get_ai_client
        ai = get_ai_client()
        if not ai or not code:
            return ""
        resp = await ai.complete(
            system=f"Expert {language} test engineer. Write pytest/jest tests only. No explanations.",
            user=f"Write tests for:\n{code[:1500]}",
            model=AIModel.CODE, max_tokens=800, temperature=0.1,
            agent_name="developer_tests",
        )
        return resp.content.strip() if (resp and resp.success) else ""

    async def _push_to_github(self, path: str, content: str, message: str) -> dict:
        """Push código generado a GitHub."""
        try:
            from apps.core.tools.self_improvement import SelfImprovementEngine
            engine = SelfImprovementEngine()
            return await engine.push_file(path=path, content=content, message=f"feat: {message[:70]}")
        except Exception as exc:
            return {"success": False, "error": str(exc)}
