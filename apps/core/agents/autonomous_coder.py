"""
autonomous_coder.py — Codificación Autónoma para ARIA AI.

Integra Aider y SWE-agent para que ARIA pueda:
  - Modificar su propio código de forma autónoma (Aider)
  - Crear Pull Requests con cambios documentados
  - Resolver issues de GitHub automáticamente (SWE-agent)
  - Hacer refactors y mejoras de código
  - Añadir nuevas capacidades sin intervención humana

Extiende el EvolutionAgent existente con herramientas de codificación real.

Referencia:
  - Aider: https://github.com/Aider-AI/aider
  - SWE-agent: https://github.com/SWE-agent/SWE-agent
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("aria.autonomous_coder")

# ── Aider Import con fallback ────────────────────────────────────────────────
try:
    from aider.coders import Coder
    from aider.models import Model
    from aider.io import InputOutput
    AIDER_AVAILABLE = True
    logger.info("[Aider] Librería cargada correctamente.")
except ImportError:
    AIDER_AVAILABLE = False
    logger.warning(
        "[Aider] aider-chat no instalado. "
        "Usando subprocess como fallback. "
        "Instala con: pip install aider-chat"
    )
    Coder = None  # type: ignore[assignment,misc]
    Model = None  # type: ignore[assignment,misc]
    InputOutput = None  # type: ignore[assignment,misc]

# ── SWE-agent Import con fallback ────────────────────────────────────────────
try:
    import sweagent
    SWEAGENT_AVAILABLE = True
    logger.info("[SWE-agent] Librería cargada correctamente.")
except ImportError:
    SWEAGENT_AVAILABLE = False
    logger.warning(
        "[SWE-agent] sweagent no instalado. "
        "Usando GitHub API como fallback. "
        "Instala con: pip install sweagent"
    )


# ── Motor de Aider ───────────────────────────────────────────────────────────

class AriaAiderEngine:
    """
    Motor de codificación autónoma con Aider para ARIA AI.

    Permite a ARIA modificar su propio código, crear features,
    corregir bugs y hacer refactors de forma autónoma.

    Integra con el EvolutionAgent existente para el ciclo de auto-mejora.

    Uso:
        engine = AriaAiderEngine()

        # Modificar un archivo específico
        result = await engine.modify_file(
            file_path="apps/core/agents/marketing_agent.py",
            instruction="Añade soporte para PostHog analytics en el método _execute",
        )

        # Crear una nueva feature
        result = await engine.create_feature(
            description="Añadir integración con Stripe webhooks",
            target_files=["apps/core/tools/sales_engine.py"],
        )
    """

    def __init__(
        self,
        repo_path: str = ".",
        model: str = "gpt-4o-mini",
        openai_api_key: str = "",
    ) -> None:
        self._repo_path = Path(repo_path).resolve()
        self._model = model
        self._openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY", "")
        self._history: list[dict[str, Any]] = []

    async def modify_file(
        self,
        file_path: str,
        instruction: str,
        auto_commit: bool = True,
        commit_message: str = "",
    ) -> dict[str, Any]:
        """
        Modifica un archivo específico según una instrucción en lenguaje natural.

        Args:
            file_path: Ruta relativa al archivo a modificar
            instruction: Instrucción en lenguaje natural
            auto_commit: Si hacer commit automático
            commit_message: Mensaje del commit (auto-generado si vacío)

        Returns:
            Dict con el resultado de la modificación
        """
        full_path = self._repo_path / file_path

        if not full_path.exists():
            return {
                "success": False,
                "error": f"Archivo no encontrado: {file_path}",
                "file": file_path,
            }

        if AIDER_AVAILABLE and Coder is not None:
            return await self._modify_with_aider(
                file_path=str(full_path),
                instruction=instruction,
                auto_commit=auto_commit,
                commit_message=commit_message,
            )
        else:
            return await self._modify_with_subprocess(
                file_path=str(full_path),
                instruction=instruction,
                auto_commit=auto_commit,
                commit_message=commit_message,
            )

    async def _modify_with_aider(
        self,
        file_path: str,
        instruction: str,
        auto_commit: bool,
        commit_message: str,
    ) -> dict[str, Any]:
        """Modifica un archivo usando la API de Aider."""
        try:
            io = InputOutput(
                yes=True,  # Auto-confirmar cambios
                chat_history_file=None,
            )

            model = Model(self._model)
            coder = Coder.create(
                main_model=model,
                fnames=[file_path],
                io=io,
                auto_commits=auto_commit,
                git=auto_commit,
            )

            # Ejecutar en thread para no bloquear el event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: coder.run(instruction),
            )

            result = {
                "success": True,
                "file": file_path,
                "instruction": instruction,
                "auto_committed": auto_commit,
                "source": "aider",
            }

            self._history.append(result)
            logger.info("[Aider] Archivo modificado: %s", file_path)
            return result

        except Exception as exc:
            logger.error("[Aider] Error modificando %s: %s", file_path, exc)
            return {
                "success": False,
                "error": str(exc),
                "file": file_path,
                "source": "aider",
            }

    async def _modify_with_subprocess(
        self,
        file_path: str,
        instruction: str,
        auto_commit: bool,
        commit_message: str,
    ) -> dict[str, Any]:
        """Fallback: usa aider como subprocess."""
        if not self._openai_api_key:
            return {
                "success": False,
                "error": "OPENAI_API_KEY no configurado para Aider",
                "file": file_path,
                "source": "subprocess_fallback",
            }

        try:
            cmd = [
                "aider",
                "--model", self._model,
                "--yes",
                "--no-pretty",
                "--message", instruction,
                file_path,
            ]

            if not auto_commit:
                cmd.append("--no-auto-commits")

            env = {**os.environ, "OPENAI_API_KEY": self._openai_api_key}

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=str(self._repo_path),
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=120.0,
            )

            success = process.returncode == 0
            result = {
                "success": success,
                "file": file_path,
                "instruction": instruction,
                "stdout": stdout.decode()[:2000] if stdout else "",
                "stderr": stderr.decode()[:500] if stderr else "",
                "source": "aider_subprocess",
            }

            if success:
                logger.info("[Aider] Modificación exitosa vía subprocess: %s", file_path)
            else:
                logger.warning("[Aider] Error en subprocess: %s", result["stderr"])

            self._history.append(result)
            return result

        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Timeout en Aider (120s)",
                "file": file_path,
                "source": "aider_subprocess",
            }
        except FileNotFoundError:
            return {
                "success": False,
                "error": "Aider no encontrado. Instala con: pip install aider-chat",
                "file": file_path,
                "source": "aider_subprocess",
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "file": file_path,
                "source": "aider_subprocess",
            }

    async def create_feature(
        self,
        description: str,
        target_files: list[str],
        create_tests: bool = True,
    ) -> dict[str, Any]:
        """
        Crea una nueva feature en los archivos especificados.

        Args:
            description: Descripción de la feature a crear
            target_files: Archivos a modificar
            create_tests: Si crear tests automáticamente

        Returns:
            Dict con el resultado de la creación
        """
        instruction = description
        if create_tests:
            instruction += "\n\nTambién añade tests unitarios para la nueva funcionalidad."

        results = []
        for file_path in target_files:
            result = await self.modify_file(
                file_path=file_path,
                instruction=instruction,
            )
            results.append(result)

        success = all(r.get("success") for r in results)
        return {
            "success": success,
            "description": description,
            "files_modified": target_files,
            "results": results,
            "tests_created": create_tests,
        }

    async def create_pull_request(
        self,
        title: str,
        description: str,
        branch_name: str = "",
        files_to_modify: list[str] | None = None,
        instruction: str = "",
    ) -> dict[str, Any]:
        """
        Crea un Pull Request con cambios de código.

        Args:
            title: Título del PR
            description: Descripción del PR
            branch_name: Nombre de la rama (auto-generado si vacío)
            files_to_modify: Archivos a modificar antes del PR
            instruction: Instrucción para Aider

        Returns:
            Dict con la URL del PR creado
        """
        import re
        branch = branch_name or f"aria/auto-{re.sub(r'[^a-z0-9-]', '-', title.lower())[:40]}"

        try:
            # Crear rama
            await asyncio.create_subprocess_exec(
                "git", "checkout", "-b", branch,
                cwd=str(self._repo_path),
            )

            # Modificar archivos si se especificaron
            if files_to_modify and instruction:
                for file_path in files_to_modify:
                    await self.modify_file(file_path, instruction)

            # Crear PR con GitHub CLI
            process = await asyncio.create_subprocess_exec(
                "gh", "pr", "create",
                "--title", title,
                "--body", description,
                "--head", branch,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._repo_path),
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                pr_url = stdout.decode().strip()
                logger.info("[Aider] PR creado: %s", pr_url)
                return {
                    "success": True,
                    "pr_url": pr_url,
                    "branch": branch,
                    "title": title,
                }
            else:
                return {
                    "success": False,
                    "error": stderr.decode()[:500],
                    "branch": branch,
                }

        except Exception as exc:
            logger.error("[Aider] Error creando PR: %s", exc)
            return {"success": False, "error": str(exc)}

    def get_history(self) -> list[dict[str, Any]]:
        """Retorna el historial de modificaciones."""
        return self._history.copy()


# ── Motor de SWE-agent ───────────────────────────────────────────────────────

class AriaSWEAgentEngine:
    """
    Motor de resolución de issues con SWE-agent para ARIA AI.

    SWE-agent puede resolver issues de GitHub automáticamente,
    generando patches y PRs con soluciones completas.

    Integra con el EvolutionAgent para el ciclo de auto-mejora.

    Uso:
        engine = AriaSWEAgentEngine()

        # Resolver un issue de GitHub
        result = await engine.resolve_github_issue(
            repo="Geremypolanco/aria-ai",
            issue_number=42,
        )
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        openai_api_key: str = "",
    ) -> None:
        self._model = model
        self._openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY", "")
        self._history: list[dict[str, Any]] = []

    async def resolve_github_issue(
        self,
        repo: str,
        issue_number: int,
        create_pr: bool = True,
    ) -> dict[str, Any]:
        """
        Resuelve un issue de GitHub automáticamente.

        Args:
            repo: Repositorio en formato "owner/repo"
            issue_number: Número del issue
            create_pr: Si crear un PR con la solución

        Returns:
            Dict con el resultado y URL del PR si se creó
        """
        if SWEAGENT_AVAILABLE:
            return await self._resolve_with_sweagent(repo, issue_number, create_pr)
        else:
            return await self._resolve_with_github_api(repo, issue_number, create_pr)

    async def _resolve_with_sweagent(
        self,
        repo: str,
        issue_number: int,
        create_pr: bool,
    ) -> dict[str, Any]:
        """Resuelve issue usando SWE-agent nativo."""
        try:
            cmd = [
                "python", "-m", "sweagent.run",
                "--model_name", self._model,
                "--data.type", "github",
                f"--data.repo_name", repo,
                f"--data.issue_number", str(issue_number),
            ]

            if create_pr:
                cmd.extend(["--actions.open_pr", "true"])

            env = {**os.environ, "OPENAI_API_KEY": self._openai_api_key}

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=300.0,  # 5 minutos para issues complejos
            )

            success = process.returncode == 0
            result = {
                "success": success,
                "repo": repo,
                "issue_number": issue_number,
                "stdout": stdout.decode()[:3000] if stdout else "",
                "source": "sweagent",
            }

            self._history.append(result)
            return result

        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Timeout en SWE-agent (300s)",
                "repo": repo,
                "issue_number": issue_number,
            }
        except Exception as exc:
            logger.error("[SWE-agent] Error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def _resolve_with_github_api(
        self,
        repo: str,
        issue_number: int,
        create_pr: bool,
    ) -> dict[str, Any]:
        """
        Fallback: analiza el issue con IA y propone solución.
        Usa la API de GitHub para obtener el issue y el ai_client de Aria.
        """
        try:
            import httpx
            github_token = os.getenv("GITHUB_TOKEN", "")
            headers = {"Authorization": f"token {github_token}"} if github_token else {}

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.github.com/repos/{repo}/issues/{issue_number}",
                    headers=headers,
                )
                issue_data = response.json()

            issue_title = issue_data.get("title", "")
            issue_body = issue_data.get("body", "")

            # Analizar con IA
            try:
                from apps.core.tools.ai_client import get_ai_client, AIModel
                ai = get_ai_client()
                analysis = await ai.think(
                    system=(
                        "Eres un experto en ingeniería de software. "
                        "Analiza el issue de GitHub y propone una solución detallada."
                    ),
                    user=f"Issue #{issue_number}: {issue_title}\n\n{issue_body}",
                    model=AIModel.STRATEGY,
                )
            except Exception:
                analysis = f"Issue analizado: {issue_title}"

            result = {
                "success": True,
                "repo": repo,
                "issue_number": issue_number,
                "issue_title": issue_title,
                "proposed_solution": analysis,
                "source": "github_api_fallback",
                "note": "SWE-agent no disponible. Instala con: pip install sweagent",
            }

            self._history.append(result)
            return result

        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "repo": repo,
                "issue_number": issue_number,
                "source": "github_api_fallback",
            }

    async def analyze_codebase(
        self,
        repo_path: str,
        focus: str = "performance and bugs",
    ) -> dict[str, Any]:
        """
        Analiza el codebase completo en busca de mejoras.
        Integra con el EvolutionAgent de Aria.

        Args:
            repo_path: Ruta al repositorio
            focus: Área de enfoque del análisis

        Returns:
            Reporte de análisis con mejoras sugeridas
        """
        try:
            # Obtener lista de archivos Python
            python_files = list(Path(repo_path).rglob("*.py"))
            python_files = [f for f in python_files if "__pycache__" not in str(f)][:20]

            file_list = "\n".join(str(f.relative_to(repo_path)) for f in python_files)

            try:
                from apps.core.tools.ai_client import get_ai_client, AIModel
                ai = get_ai_client()
                analysis = await ai.think(
                    system=(
                        "Eres un experto en arquitectura de software y Python. "
                        "Analiza la estructura del proyecto y sugiere mejoras concretas."
                    ),
                    user=(
                        f"Proyecto: ARIA AI (sistema autónomo de ingresos digitales)\n"
                        f"Foco: {focus}\n\n"
                        f"Archivos principales:\n{file_list}\n\n"
                        "Sugiere las 5 mejoras más impactantes."
                    ),
                    model=AIModel.STRATEGY,
                )
            except Exception:
                analysis = "Análisis no disponible (ai_client no configurado)"

            return {
                "success": True,
                "repo_path": repo_path,
                "files_analyzed": len(python_files),
                "focus": focus,
                "analysis": analysis,
                "source": "swe_agent_analysis",
            }

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def get_history(self) -> list[dict[str, Any]]:
        """Retorna el historial de resoluciones."""
        return self._history.copy()


# ── Motor Unificado de Codificación Autónoma ────────────────────────────────

class AriaAutonomousCoderEngine:
    """
    Motor unificado de Codificación Autónoma para ARIA AI.

    Combina Aider (modificación de archivos) y SWE-agent (resolución de issues)
    para dar a ARIA capacidades completas de auto-evolución de código.

    Integra con:
    - EvolutionAgent (ciclo de auto-mejora)
    - DevAgent (desarrollo de features)
    - GitHub (PRs y issues)
    - ExecutionPipeline (auditoría de cambios)
    """

    def __init__(
        self,
        repo_path: str = ".",
        model: str = "gpt-4o-mini",
    ) -> None:
        self.aider = AriaAiderEngine(
            repo_path=repo_path,
            model=model,
        )
        self.swe_agent = AriaSWEAgentEngine(model=model)
        self._repo_path = repo_path

    async def auto_improve(
        self,
        target: str,
        improvement_type: str = "feature",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Mejora automática del código de ARIA.

        Args:
            target: Archivo o descripción del target
            improvement_type: 'feature', 'bug_fix', 'refactor', 'test', 'issue'
            context: Contexto adicional

        Returns:
            Resultado de la mejora
        """
        ctx = context or {}

        if improvement_type == "issue" and ctx.get("issue_number"):
            return await self.swe_agent.resolve_github_issue(
                repo=ctx.get("repo", "Geremypolanco/aria-ai"),
                issue_number=ctx["issue_number"],
            )

        elif improvement_type in ("feature", "bug_fix", "refactor"):
            instruction = ctx.get("instruction", f"Improve {target}: {improvement_type}")
            return await self.aider.modify_file(
                file_path=target,
                instruction=instruction,
            )

        elif improvement_type == "test":
            instruction = f"Add comprehensive unit tests for {target}"
            test_file = target.replace(".py", "_test.py").replace("apps/", "tests/")
            return await self.aider.create_feature(
                description=instruction,
                target_files=[target, test_file],
                create_tests=True,
            )

        return {
            "success": False,
            "error": f"Tipo de mejora no reconocido: {improvement_type}",
        }

    def get_capabilities(self) -> dict[str, Any]:
        """Retorna las capacidades disponibles."""
        return {
            "aider": {
                "available": AIDER_AVAILABLE,
                "capabilities": ["modify_file", "create_feature", "create_pr"],
            },
            "swe_agent": {
                "available": SWEAGENT_AVAILABLE,
                "capabilities": ["resolve_github_issue", "analyze_codebase"],
            },
        }


# ── Singleton ────────────────────────────────────────────────────────────────
_coder_instance: AriaAutonomousCoderEngine | None = None


def get_autonomous_coder() -> AriaAutonomousCoderEngine:
    """Retorna el singleton del motor de Codificación Autónoma."""
    global _coder_instance
    if _coder_instance is None:
        _coder_instance = AriaAutonomousCoderEngine(
            repo_path=os.getenv("ARIA_REPO_PATH", "."),
            model=os.getenv("AIDER_MODEL", "gpt-4o-mini"),
        )
    return _coder_instance
