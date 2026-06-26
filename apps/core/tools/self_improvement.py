"""
self_improvement.py — Motor de auto-mejora de codigo de ARIA AI v3.

ARIA puede:
  1. Leer su propio codigo via GitHub API (sin simulaciones)
  2. Analizar calidad y detectar mejoras con Qwen2.5-Coder
  3. Generar codigo mejorado y validarlo sintacticamente
  4. Pushear mejoras a GitHub (triggea deploy automatico en Fly.io)
  5. Leer logs de produccion de Fly.io para aprender de errores reales
  6. Detectar y corregir bugs de produccion automaticamente
  7. Rate limiting para no saturar el CI/CD

Principio: NINGUNA funcion retorna datos simulados. Si algo falla, lo dice.
"""

from __future__ import annotations

import ast
import base64
import json
import logging
import re
import time
from typing import Any

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.self_improvement")

GITHUB_API = "https://api.github.com"
FLY_API = "https://api.fly.io"
REPO = getattr(settings, "GITHUB_REPO", None) or "Geremypolanco/aria-ai"
BRANCH = "main"


class SelfImprovementEngine:
    """
    Motor de auto-mejora: ARIA lee, analiza y mejora su propio codigo.
    Todo es real — GitHub API, Fly.io logs, Qwen2.5-Coder para generacion.
    """

    MODIFIABLE_FILES = [
        "apps/core/agents/pm_agent.py",
        "apps/core/agents/cfo_agent.py",
        "apps/core/agents/dev_agent.py",
        "apps/core/agents/marketing_agent.py",
        "apps/core/agents/support_agent.py",
        "apps/core/agents/evolution_agent.py",
        "apps/core/tools/huggingface_suite.py",
        "apps/core/tools/buffer_tools.py",
        "apps/core/tools/mailchimp_tools.py",
        "apps/core/tools/commerce_tools.py",
        "apps/core/tools/content_tools.py",
        "apps/core/tools/market_tools.py",
        "apps/core/tools/canva_tools.py",
        "apps/core/tools/airtable_tools.py",
        "apps/core/tools/social_media.py",
        "apps/core/tools/affiliate_tools.py",
        "apps/core/tools/publishing_tools.py",
        "apps/core/tools/content_pipeline.py",
        "apps/core/tools/api_discovery.py",
        "apps/core/tools/google_tools.py",
        "apps/core/tools/google_suite.py",
    ]

    PROTECTED_FILES = [
        "apps/core/config.py",
        "apps/core/tools/telegram_bot.py",
        "apps/core/tools/ai_client.py",
        "apps/core/agents/orchestrator.py",
        "apps/core/agents/base_agent.py",
        "apps/core/tools/self_improvement.py",
        "apps/core/main.py",
        "fly.toml",
        "apps/core/Dockerfile",
        "apps/core/requirements.txt",
    ]

    # Rate limit: 1 push cada 20 min para no saturar CI/CD
    _last_push_time: float = 0.0
    MIN_PUSH_INTERVAL_SECONDS: int = 1200

    def __init__(self) -> None:
        self._token = getattr(settings, "GITHUB_TOKEN", None)
        self._fly_token = getattr(settings, "FLY_API_TOKEN", None)
        self._http = httpx.AsyncClient(timeout=60.0)
        self._gh_headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }

    def is_available(self) -> dict[str, bool]:
        """Reporta que capacidades estan disponibles realmente."""
        return {
            "github_read": bool(self._token),
            "github_push": bool(self._token),
            "fly_logs": bool(self._fly_token),
            "ai_analysis": True,  # usa el ai_client que tiene su propio fallover
        }

    def _can_github(self) -> bool:
        if not self._token:
            logger.error(
                "[SelfImprovement] GITHUB_TOKEN no configurado — no puedo leer ni escribir codigo"
            )
            return False
        return True

    def _can_push(self) -> bool:
        """Rate limiter: evita pushes frecuentes que saturen el CI/CD."""
        if not self._can_github():
            return False
        now = time.time()
        elapsed = now - SelfImprovementEngine._last_push_time
        if elapsed < self.MIN_PUSH_INTERVAL_SECONDS:
            remaining = int(self.MIN_PUSH_INTERVAL_SECONDS - elapsed)
            logger.info("[SelfImprovement] Rate limit — proximo push en %ds", remaining)
            return False
        return True

    # ══════════════════════════════════════════════════════════════
    # 1. LECTURA DE CODIGO PROPIO (GitHub API real)
    # ══════════════════════════════════════════════════════════════

    async def read_file(self, file_path: str) -> dict[str, Any]:
        """Lee un archivo del repositorio de ARIA en GitHub."""
        if not self._can_github():
            return {"success": False, "error": "GITHUB_TOKEN no configurado"}
        try:
            res = await self._http.get(
                f"{GITHUB_API}/repos/{REPO}/contents/{file_path}",
                headers=self._gh_headers,
            )
            if res.status_code == 200:
                data = res.json()
                content = base64.b64decode(data["content"]).decode("utf-8")
                return {
                    "success": True,
                    "file": file_path,
                    "content": content,
                    "sha": data["sha"],
                    "size": data["size"],
                    "lines": len(content.splitlines()),
                }
            return {"success": False, "error": f"GitHub HTTP {res.status_code}: {res.text[:300]}"}
        except Exception as exc:
            logger.error("[SelfImprovement] read_file %s: %s", file_path, exc)
            return {"success": False, "error": str(exc)}

    async def list_all_python_files(self, path: str = "apps/core") -> list[str]:
        """Lista recursivamente todos los archivos Python del proyecto via GitHub API."""
        if not self._can_github():
            return []
        try:
            res = await self._http.get(
                f"{GITHUB_API}/repos/{REPO}/git/trees/HEAD?recursive=1",
                headers=self._gh_headers,
            )
            if res.status_code == 200:
                tree = res.json().get("tree", [])
                return [
                    item["path"]
                    for item in tree
                    if item["type"] == "blob"
                    and item["path"].startswith(path)
                    and item["path"].endswith(".py")
                    and item["path"] not in self.PROTECTED_FILES
                ]
            logger.error("[SelfImprovement] list_files GitHub HTTP %d", res.status_code)
        except Exception as exc:
            logger.error("[SelfImprovement] list_files error: %s", exc)
        return []

    async def read_multiple_files(self, file_paths: list[str]) -> dict[str, dict]:
        """Lee multiples archivos en paralelo."""
        import asyncio

        tasks = [self.read_file(f) for f in file_paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            path: (r if isinstance(r, dict) else {"success": False, "error": str(r)})
            for path, r in zip(file_paths, results, strict=False)
        }

    # ══════════════════════════════════════════════════════════════
    # 2. LOGS DE PRODUCCION (Fly.io API real)
    # ══════════════════════════════════════════════════════════════

    async def read_production_logs(self, lines: int = 200) -> dict[str, Any]:
        """
        Lee los logs reales de produccion de Fly.io.
        Requiere FLY_API_TOKEN en secrets.
        """
        if not self._fly_token:
            return {
                "success": False,
                "error": "FLY_API_TOKEN no configurado — no puedo leer logs de produccion",
                "available": False,
            }
        try:
            app_name = getattr(settings, "FLY_APP_NAME", "aria-ai")
            res = await self._http.get(
                f"https://api.machines.dev/v1/apps/{app_name}/logs",
                headers={
                    "Authorization": (
                        self._fly_token
                        if self._fly_token.startswith("FlyV1")
                        else f"Bearer {self._fly_token}"
                    ),
                    "Accept": "application/json",
                },
                params={"limit": lines},
            )
            if res.status_code == 200:
                logs = res.json()
                log_text = "\n".join(
                    f"[{entry.get('timestamp', '')}] {entry.get('message', '')}"
                    for entry in (logs if isinstance(logs, list) else logs.get("data", []))
                )
                return {"success": True, "logs": log_text, "lines": lines}
            return {
                "success": False,
                "error": f"Fly.io API HTTP {res.status_code}: {res.text[:300]}",
            }
        except Exception as exc:
            logger.error("[SelfImprovement] read_production_logs error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def analyze_logs_for_errors(self, log_text: str) -> dict[str, Any]:
        """Analiza logs de produccion con IA para detectar errores y patrones."""
        if not log_text:
            return {"success": False, "error": "No hay logs para analizar"}
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()
            response = await ai.complete(
                system="Analista de sistemas Python. Responde SOLO con JSON valido.",
                user=(
                    "Analiza estos logs de produccion y devuelve JSON con:\n"
                    '{"errors": [{"pattern": str, "frequency": int, "severity": "alta/media/baja", '
                    '"likely_cause": str, "fix_suggestion": str}], '
                    '"warnings": [str], "performance_issues": [str], '
                    '"recommendations": [str], "critical_errors": [str]}\n\n'
                    f"LOGS:\n{log_text[-4000:]}"
                ),
                model=AIModel.FAST,
                json_mode=True,
            )
            if response and response.success:
                try:
                    content = response.content
                    if isinstance(content, str):
                        match = re.search(r"\{.*\}", content, re.DOTALL)
                        content = json.loads(match.group()) if match else {}
                    return {"success": True, "analysis": content}
                except Exception:
                    pass
            return {"success": False, "error": "No se pudo parsear el analisis de logs"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 3. ANALISIS DE CALIDAD DE CODIGO (Qwen2.5-Coder real)
    # ══════════════════════════════════════════════════════════════

    async def analyze_code_quality(self, file_path: str, code: str) -> dict[str, Any]:
        """Analiza la calidad del codigo con Qwen2.5-Coder. Sin simulaciones."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()
            response = await ai.complete(
                system="Senior Python developer revisando codigo de IA autonoma. Responde SOLO con JSON valido.",
                user=(
                    f"Analiza {file_path} y devuelve JSON con:\n"
                    '{"quality_score": 0-100, '
                    '"bugs": [{"description": str, "severity": "alta/media/baja", "fix": str}], '
                    '"inefficiencies": [str], '
                    '"missing_error_handling": [str], '
                    '"simulations_found": [str], '
                    '"improvement_priority": "alta/media/baja", '
                    '"summary": str}\n\n'
                    "BUSCA especialmente: datos hardcodeados, fallbacks que simulan respuestas reales, "
                    "funciones que retornan datos falsos cuando la API no esta disponible.\n\n"
                    f"CODIGO:\n{code[:4500]}"
                ),
                model=AIModel.CODE,
                json_mode=True,
            )
            if response and response.success:
                try:
                    content = response.content
                    if isinstance(content, str):
                        match = re.search(r"\{.*\}", content, re.DOTALL)
                        content = json.loads(match.group()) if match else {}
                    if isinstance(content, dict):
                        content["file"] = file_path
                        content["analyzed_lines"] = len(code.splitlines())
                        return {"success": True, "analysis": content}
                except Exception:
                    pass
            return {"success": False, "error": "No se pudo parsear el analisis — IA no disponible"}
        except Exception as exc:
            logger.error("[SelfImprovement] analyze error %s: %s", file_path, exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 4. GENERACION DE CODIGO MEJORADO (Qwen2.5-Coder real)
    # ══════════════════════════════════════════════════════════════

    async def generate_improved_code(
        self,
        file_path: str,
        original_code: str,
        analysis: dict,
        specific_improvement: str = "",
        log_lessons: dict | None = None,
    ) -> dict[str, Any]:
        """Genera una version mejorada del codigo con Qwen2.5-Coder."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()

            instructions = []
            for bug in analysis.get("bugs", [])[:3]:
                desc = bug.get("description", bug) if isinstance(bug, dict) else str(bug)
                fix = bug.get("fix", "") if isinstance(bug, dict) else ""
                instructions.append(f"CORRIGE: {desc}" + (f" → {fix}" if fix else ""))
            for item in analysis.get("inefficiencies", [])[:2]:
                instructions.append(f"OPTIMIZA: {item}")
            for item in analysis.get("missing_error_handling", [])[:2]:
                instructions.append(f"AGREGA manejo de error: {item}")
            for sim in analysis.get("simulations_found", [])[:2]:
                instructions.append(
                    f"ELIMINA simulacion — retorna error explicito si API no disponible: {sim}"
                )
            if specific_improvement:
                instructions.append(f"MEJORA ESPECIFICA: {specific_improvement}")
            if log_lessons:
                for rec in log_lessons.get("recommendations", [])[:1]:
                    instructions.append(f"APRENDIDO DE LOGS: {rec}")

            if not instructions:
                return {"success": False, "error": "Sin mejoras identificadas para este archivo"}

            response = await ai.complete(
                system=(
                    "Senior Python developer. Devuelve SOLO el codigo Python completo mejorado. "
                    "Sin explicaciones, sin markdown fences, solo el codigo. "
                    "NUNCA simules datos — si una API no esta disponible, retorna error explicito."
                ),
                user=(
                    f"Mejora {file_path}.\n\nINSTRUCCIONES OBLIGATORIAS:\n"
                    + "\n".join(f"- {i}" for i in instructions)
                    + f"\n\nCODIGO ORIGINAL:\n{original_code[:6000]}\n\n"
                    "REGLAS ABSOLUTAS:\n"
                    "1. Mantener TODA la funcionalidad existente\n"
                    "2. Manejo de errores explicito en TODAS las funciones\n"
                    "3. Si falta API key, retornar {'success': False, 'error': 'X_KEY no configurado'}\n"
                    "4. JAMAS retornar datos hardcodeados como si fueran datos reales\n"
                    "5. Compatible 100% con el resto del sistema"
                ),
                model=AIModel.CODE,
                max_tokens=8000,
            )

            if not response or not response.success:
                return {"success": False, "error": "IA no disponible para generar codigo mejorado"}

            improved = response.content.strip()
            # Limpiar markdown fences si el modelo los incluyo
            for fence in ["```python\n", "```python", "```\n", "```"]:
                if improved.startswith(fence):
                    improved = improved[len(fence) :]
            if improved.endswith("```"):
                improved = improved[:-3]
            improved = improved.strip()

            # Validar sintaxis Python
            validation = self._validate_python(improved)
            if not validation["valid"]:
                return {"success": False, "error": f"Sintaxis invalida: {validation['error']}"}

            # Sanity check: no debe ser drasticamente mas corto (posible truncado)
            orig_lines = len(original_code.splitlines())
            impr_lines = len(improved.splitlines())
            if impr_lines < orig_lines * 0.45:
                return {
                    "success": False,
                    "error": f"Codigo sospechosamente corto ({impr_lines} vs {orig_lines} lineas) — descartado",
                }

            return {
                "success": True,
                "file": file_path,
                "improved_code": improved,
                "original_lines": orig_lines,
                "improved_lines": impr_lines,
                "lines_delta": impr_lines - orig_lines,
                "improvements_applied": instructions,
            }
        except Exception as exc:
            logger.error("[SelfImprovement] generate error %s: %s", file_path, exc)
            return {"success": False, "error": str(exc)}

    def _validate_python(self, code: str) -> dict[str, Any]:
        """Valida sintaxis Python real con ast.parse."""
        try:
            ast.parse(code)
            return {"valid": True}
        except SyntaxError as e:
            return {"valid": False, "error": f"SyntaxError linea {e.lineno}: {e.msg}"}
        except Exception as e:
            return {"valid": False, "error": str(e)}

    # ══════════════════════════════════════════════════════════════
    # 5. PUSH A GITHUB → DEPLOY AUTOMATICO EN FLY.IO
    # ══════════════════════════════════════════════════════════════

    async def push_improvement(
        self,
        file_path: str,
        improved_code: str,
        original_sha: str,
        improvements_applied: list[str],
    ) -> dict[str, Any]:
        """Pushea codigo mejorado a GitHub — triggea CI/CD → deploy en Fly.io."""
        if not self._can_push():
            return {
                "success": False,
                "error": f"Rate limit o GITHUB_TOKEN no disponible. "
                f"Proximo push disponible en {self.MIN_PUSH_INTERVAL_SECONDS}s",
            }
        if file_path in self.PROTECTED_FILES:
            return {
                "success": False,
                "error": f"{file_path} es archivo protegido — no se puede modificar automaticamente",
            }

        try:
            filename = file_path.split("/")[-1].replace(".py", "")
            main_imp = improvements_applied[0][:60] if improvements_applied else "auto-mejora"
            commit_msg = (
                f"feat({filename}): {main_imp}\n\n"
                f"Auto-mejora por ARIA Evolution Engine v3.\n"
                + "\n".join(f"- {imp[:80]}" for imp in improvements_applied[:5])
            )
            encoded = base64.b64encode(improved_code.encode("utf-8")).decode("ascii")
            res = await self._http.put(
                f"{GITHUB_API}/repos/{REPO}/contents/{file_path}",
                headers=self._gh_headers,
                json={
                    "message": commit_msg,
                    "content": encoded,
                    "sha": original_sha,
                    "branch": BRANCH,
                },
            )
            if res.status_code in (200, 201):
                SelfImprovementEngine._last_push_time = time.time()
                commit = res.json().get("commit", {})
                logger.info(
                    "[SelfImprovement] Push exitoso: %s → %s", file_path, commit.get("sha", "")[:8]
                )
                return {
                    "success": True,
                    "file": file_path,
                    "commit_sha": commit.get("sha", "")[:8],
                    "commit_message": commit_msg[:100],
                    "improvements": improvements_applied,
                }
            return {
                "success": False,
                "error": f"GitHub HTTP {res.status_code}: {res.text[:300]}",
            }
        except Exception as exc:
            logger.error("[SelfImprovement] push_improvement %s: %s", file_path, exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 6. FLUJO COMPLETO: ANALIZAR → MEJORAR → PUSHEAR
    # ══════════════════════════════════════════════════════════════

    async def improve_file(
        self,
        file_path: str,
        specific_improvement: str = "",
        log_lessons: dict | None = None,
    ) -> dict[str, Any]:
        """
        Flujo completo de auto-mejora de un archivo:
        1. Leer codigo actual de GitHub
        2. Analizar calidad con IA
        3. Generar version mejorada con Qwen2.5-Coder
        4. Validar sintaxis
        5. Pushear a GitHub → deploy automatico
        """
        logger.info("[SelfImprovement] Iniciando mejora de %s", file_path)

        # Paso 1: Leer
        file_data = await self.read_file(file_path)
        if not file_data["success"]:
            return {
                "success": False,
                "file": file_path,
                "error": f"No se pudo leer: {file_data['error']}",
            }

        original_code = file_data["content"]
        original_sha = file_data["sha"]
        logger.info("[SelfImprovement] Leido %s (%d lineas)", file_path, file_data["lines"])

        # Paso 2: Analizar
        analysis_result = await self.analyze_code_quality(file_path, original_code)
        if not analysis_result["success"]:
            logger.warning(
                "[SelfImprovement] Analisis fallido para %s: %s",
                file_path,
                analysis_result["error"],
            )
            analysis = {"bugs": [], "inefficiencies": [], "quality_score": 50}
        else:
            analysis = analysis_result["analysis"]
            score = analysis.get("quality_score", 50)
            logger.info("[SelfImprovement] Score actual de %s: %d/100", file_path, score)
            if score >= 92 and not specific_improvement and not analysis.get("simulations_found"):
                return {
                    "success": True,
                    "file": file_path,
                    "skipped": True,
                    "reason": f"Calidad ya optima ({score}/100) — sin mejoras necesarias",
                    "quality_score": score,
                }

        # Paso 3: Generar codigo mejorado
        gen_result = await self.generate_improved_code(
            file_path, original_code, analysis, specific_improvement, log_lessons
        )
        if not gen_result["success"]:
            return {"success": False, "file": file_path, "error": gen_result["error"]}

        # Paso 4: Push a GitHub
        push_result = await self.push_improvement(
            file_path,
            gen_result["improved_code"],
            original_sha,
            gen_result["improvements_applied"],
        )

        return {
            "success": push_result["success"],
            "file": file_path,
            "quality_score_before": analysis.get("quality_score", 0),
            "improvements_applied": gen_result["improvements_applied"],
            "lines_delta": gen_result["lines_delta"],
            "commit_sha": push_result.get("commit_sha"),
            "error": push_result.get("error"),
        }

    async def improve_multiple_files(
        self,
        file_paths: list[str],
        log_lessons: dict | None = None,
        max_concurrent: int = 2,
    ) -> list[dict[str, Any]]:
        """
        Mejora multiples archivos secuencialmente (respeta el rate limit del CI/CD).
        max_concurrent=2 para no saturar GitHub Actions.
        """
        results = []
        import asyncio

        for i in range(0, len(file_paths), max_concurrent):
            batch = file_paths[i : i + max_concurrent]
            batch_results = await asyncio.gather(
                *[self.improve_file(fp, log_lessons=log_lessons) for fp in batch],
                return_exceptions=True,
            )
            for fp, r in zip(batch, batch_results, strict=False):
                if isinstance(r, Exception):
                    results.append({"success": False, "file": fp, "error": str(r)})
                else:
                    results.append(r)
            # Esperar entre batches para no saturar el rate limit
            if i + max_concurrent < len(file_paths):
                await asyncio.sleep(self.MIN_PUSH_INTERVAL_SECONDS)
        return results

    async def calculate_system_score(self) -> dict[str, Any]:
        """
        Calcula el score de salud del sistema leyendo logs reales y contando errores.
        Sin simulaciones — usa datos reales de produccion.
        """
        score = 100
        details: list[str] = []

        # Intentar leer logs de produccion
        logs_result = await self.read_production_logs(lines=100)
        if logs_result["success"]:
            log_text = logs_result["logs"]
            error_count = log_text.lower().count("error")
            warning_count = log_text.lower().count("warning")
            critical_count = log_text.lower().count("critical")
            score -= min(30, critical_count * 10 + error_count * 2 + warning_count)
            details.append(
                f"Logs: {critical_count} criticos, {error_count} errores, {warning_count} warnings"
            )
        else:
            details.append(f"Logs no disponibles: {logs_result['error']}")
            score -= 10  # penalizacion por no poder monitorear

        # Verificar disponibilidad de APIs criticas
        critical_vars = ["SUPABASE_URL", "SUPABASE_KEY", "TELEGRAM_TOKEN", "GITHUB_TOKEN"]
        for var in critical_vars:
            if not getattr(settings, var, None):
                score -= 15
                details.append(f"CRITICO: {var} no configurado")

        ai_vars = ["HF_TOKEN", "GROQ_API_KEY"]
        if not any(getattr(settings, v, None) for v in ai_vars):
            score -= 20
            details.append("CRITICO: Sin proveedores de IA configurados (HF_TOKEN o GROQ_API_KEY)")

        score = max(0, score)
        return {
            "success": True,
            "score": score,
            "grade": "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D",
            "details": details,
        }
