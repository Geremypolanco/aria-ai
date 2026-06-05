"""
self_improvement.py — Motor de auto-mejora de código de ARIA AI v2.

ARIA puede:
  1. Leer su propio código vía GitHub API
  2. Analizar calidad y detectar mejoras con Qwen2.5-Coder
  3. Generar código mejorado y validarlo sintácticamente
  4. Pushear mejoras a GitHub (triggea deploy automático en Fly.io)
  5. Rate limiting para no saturar el CI/CD
  6. Rollback si el código mejorado es inválido o demasiado corto
"""
from __future__ import annotations
import ast
import base64
import json
import logging
import random
import re
import time
from typing import Any, Optional
import httpx
from apps.core.config import settings

logger = logging.getLogger("aria.self_improvement")

GITHUB_API = "https://api.github.com"
REPO = settings.GITHUB_REPO or "Geremypolanco/aria-ai"
BRANCH = "main"


class SelfImprovementEngine:
    """Motor de auto-mejora: ARIA lee, analiza y mejora su propio código."""

    MODIFIABLE_FILES = [
        "apps/core/agents/pm_agent.py",
        "apps/core/agents/cfo_agent.py",
        "apps/core/agents/dev_agent.py",
        "apps/core/agents/marketing_agent.py",
        "apps/core/agents/support_agent.py",
        "apps/core/agents/evolution_agent.py",
        "apps/core/tools/google_suite.py",
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
    ]

    PROTECTED_FILES = [
        "apps/core/config.py",
        "apps/core/tools/telegram_bot.py",
        "apps/core/tools/ai_client.py",
        "apps/core/agents/orchestrator.py",
        "apps/core/main.py",
        "fly.toml",
        "apps/core/Dockerfile",
        "apps/core/requirements.txt",
    ]

    # Rate limit: máximo 1 push cada 30 min para no saturar el CI/CD
    _last_push_time: float = 0.0
    MIN_PUSH_INTERVAL_SECONDS: int = 1800

    def __init__(self) -> None:
        self._token = settings.GITHUB_TOKEN
        self._http = httpx.AsyncClient(timeout=60.0)
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }

    def _ok(self) -> bool:
        return bool(self._token)

    def _can_push(self) -> bool:
        """Rate limiter: evita pushes frecuentes que saturen el CI/CD."""
        now = time.time()
        elapsed = now - SelfImprovementEngine._last_push_time
        if elapsed < self.MIN_PUSH_INTERVAL_SECONDS:
            remaining = int(self.MIN_PUSH_INTERVAL_SECONDS - elapsed)
            logger.info("[SelfImprovement] Rate limit — próximo push en %ds", remaining)
            return False
        return True

    # ══════════════════════════════════════════════════════════════
    # 1. LECTURA DE CÓDIGO PROPIO
    # ══════════════════════════════════════════════════════════════

    async def read_file(self, file_path: str) -> dict[str, Any]:
        """Lee un archivo del repositorio de ARIA en GitHub."""
        if not self._ok():
            return {"success": False, "error": "GITHUB_TOKEN no configurado"}
        try:
            res = await self._http.get(
                f"{GITHUB_API}/repos/{REPO}/contents/{file_path}",
                headers=self._headers,
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
            return {"success": False, "error": f"HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            logger.error("[SelfImprovement] read_file %s: %s", file_path, exc)
            return {"success": False, "error": str(exc)}

    async def list_all_files(self, path: str = "apps/core") -> list[str]:
        """Lista recursivamente todos los archivos Python del proyecto."""
        if not self._ok():
            return []
        try:
            result = await self._http.get(
                f"{GITHUB_API}/repos/{REPO}/git/trees/HEAD?recursive=1",
                headers=self._headers,
            )
            if result.status_code == 200:
                tree = result.json().get("tree", [])
                return [
                    item["path"] for item in tree
                    if item["type"] == "blob"
                    and item["path"].startswith(path)
                    and item["path"].endswith(".py")
                ]
        except Exception as exc:
            logger.error("[SelfImprovement] list_files: %s", exc)
        return []

    async def read_multiple_files(self, file_paths: list[str]) -> dict[str, dict]:
        """Lee múltiples archivos en paralelo."""
        import asyncio
        tasks = [self.read_file(f) for f in file_paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            path: (r if isinstance(r, dict) else {"success": False, "error": str(r)})
            for path, r in zip(file_paths, results)
        }

    # ══════════════════════════════════════════════════════════════
    # 2. ANÁLISIS DE CALIDAD
    # ══════════════════════════════════════════════════════════════

    async def analyze_code_quality(self, file_path: str, code: str) -> dict[str, Any]:
        """Analiza la calidad del código con Qwen2.5-Coder."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = await get_ai_client()

            response = await ai.complete(
                system="Senior Python developer revisando código de IA autónoma. Responde SOLO con JSON válido.",
                user=(
                    f"Analiza {file_path} y devuelve un JSON con:\n"
                    f"{{\"quality_score\": 0-100, \"bugs\": [{{\"line\": N, \"issue\": str, \"fix\": str}}], "
                    f"\"inefficiencies\": [str], \"missing_features\": [str], "
                    f"\"improvement_priority\": \"alta/media/baja\", \"summary\": str}}\n\n"
                    f"CÓDIGO:\n{code[:4000]}"
                ),
                model=AIModel.CODE,
                json_mode=True,
            )

            if response and response.success:
                try:
                    if isinstance(response.content, dict):
                        analysis = response.content
                    else:
                        match = re.search(r"\{.*\}", response.content, re.DOTALL)
                        analysis = json.loads(match.group()) if match else {}
                    analysis["file"] = file_path
                    analysis["analyzed_lines"] = len(code.splitlines())
                    return {"success": True, "analysis": analysis}
                except (json.JSONDecodeError, AttributeError):
                    pass

            return {"success": False, "error": "No se pudo parsear el análisis"}
        except Exception as exc:
            logger.error("[SelfImprovement] analyze error %s: %s", file_path, exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 3. GENERACIÓN DE CÓDIGO MEJORADO
    # ══════════════════════════════════════════════════════════════

    async def generate_improved_code(
        self,
        file_path: str,
        original_code: str,
        analysis: dict,
        specific_improvement: str = "",
        lessons: Optional[dict] = None,
    ) -> dict[str, Any]:
        """Genera una versión mejorada del código usando Qwen2.5-Coder."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = await get_ai_client()

            instructions = []
            bugs = analysis.get("bugs", [])
            if bugs:
                instructions.append(f"CORRIGE bugs: {json.dumps(bugs[:3])}")
            for item in analysis.get("inefficiencies", [])[:3]:
                instructions.append(f"OPTIMIZA: {item}")
            for item in analysis.get("missing_features", [])[:3]:
                instructions.append(f"AGREGA: {item}")
            if specific_improvement:
                instructions.append(f"MEJORA ESPECÍFICA: {specific_improvement}")
            if lessons:
                for rec in lessons.get("recommendations", [])[:1]:
                    instructions.append(f"LECCIÓN: {rec}")

            if not instructions:
                return {"success": False, "error": "No hay mejoras identificadas"}

            response = await ai.complete(
                system=(
                    "Senior Python developer. Devuelve SOLO el código Python completo mejorado. "
                    "Sin explicaciones, sin markdown fences, solo el código."
                ),
                user=(
                    f"Mejora {file_path}.\n\nINSTRUCCIONES:\n"
                    + "\n".join(f"- {i}" for i in instructions)
                    + f"\n\nCÓDIGO ORIGINAL:\n{original_code[:6000]}\n\n"
                    "REGLAS: Mantén toda la funcionalidad. No elimines funciones existentes. "
                    "Manejo de errores en todas las funciones. Compatible 100% con el sistema."
                ),
                model=AIModel.CODE,
                max_tokens=8000,
            )

            if not response or not response.success:
                return {"success": False, "error": "Sin respuesta del modelo de IA"}

            improved = response.content.strip()
            # Limpiar markdown fences si el modelo los incluyó
            for fence in ["```python\n", "```\n", "```"]:
                if improved.startswith(fence):
                    improved = improved[len(fence):]
            if improved.endswith("```"):
                improved = improved[:-3]
            improved = improved.strip()

            # Validar sintaxis
            validation = self._validate_python_code(improved)
            if not validation["valid"]:
                return {"success": False, "error": f"Sintaxis inválida: {validation['error']}"}

            # Sanity check: no debe ser drásticamente más corto
            orig_lines = len(original_code.splitlines())
            impr_lines = len(improved.splitlines())
            if impr_lines < orig_lines * 0.5:
                return {
                    "success": False,
                    "error": f"Código sospechosamente corto ({impr_lines} vs {orig_lines} líneas)",
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

    def _validate_python_code(self, code: str) -> dict[str, Any]:
        """Valida que el código es Python sintácticamente correcto."""
        try:
            ast.parse(code)
            return {"valid": True}
        except SyntaxError as e:
            return {"valid": False, "error": f"SyntaxError línea {e.lineno}: {e.msg}"}
        except Exception as e:
            return {"valid": False, "error": str(e)}

    # ══════════════════════════════════════════════════════════════
    # 4. PUSH A GITHUB → DEPLOY AUTOMÁTICO
    # ══════════════════════════════════════════════════════════════

    async def push_improvement(
        self,
        file_path: str,
        improved_code: str,
        original_sha: str,
        improvements_applied: list[str],
    ) -> dict[str, Any]:
        """Pushea el código mejorado a GitHub triggea CI/CD."""
        if not self._ok():
            return {"success": False, "error": "GITHUB_TOKEN no configurado"}
        if not self._can_push():
            return {"success": False, "error": "Rate limit activo"}

        try:
            filename = file_path.split("/")[-1].replace(".py", "")
            main_imp = improvements_applied[0][:50] if improvements_applied else "auto-mejora"
            commit_msg = (
                f"feat({filename}): {main_imp}\n\n"
                f"Auto-mejora por ARIA Evolution Engine.\n"
                + "\n".join(f"- {imp}" for imp in improvements_applied[:5])
            )

            encoded = base64.b64encode(improved_code.encode("utf-8")).decode("ascii")
            res = await self._http.put(
                f"{GITHUB_API}/repos/{REPO}/contents/{file_path}",
                headers=self._headers,
                json={
                    "message": commit_msg,
                    "content": encoded,
                    "sha": original_sha,
                    "branch": BRANCH,
                },
            )

            if res.status_code in (200, 201):
                SelfImprovementEngine._last_push_time = time.time()
                new_sha = res.json()["content"]["sha"]
                logger.info("[SelfImprovement] Push exitoso: %s", file_path)
                return {
                    "success": True,
                    "file": file_path,
                    "new_sha": new_sha,
                    "commit_message": commit_msg[:100],
                }

            error_detail = res.json().get("message", res.text[:200])
            return {"success": False, "error": f"HTTP {res.status_code}: {error_detail}"}

        except Exception as exc:
            logger.error("[SelfImprovement] push error %s: %s", file_path, exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 5. CICLO COMPLETO DE MEJORA
    # ══════════════════════════════════════════════════════════════

    async def run_improvement_cycle(
        self,
        max_files: int = 2,
        lessons: Optional[dict] = None,
        target_files: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """
        Ciclo completo: lee código → analiza calidad → mejora → pushea.
        Selección aleatoria para variar qué archivos se mejoran cada ciclo.
        """
        results: dict[str, Any] = {
            "success": True,
            "analyzed": [],
            "improved_files": [],
            "skipped": [],
            "errors": [],
        }

        if not self._ok():
            results["success"] = False
            results["errors"].append("GITHUB_TOKEN no configurado")
            return results

        files_pool = target_files or self.MODIFIABLE_FILES
        # Shuffle para variar qué archivos se analizan cada ciclo
        shuffled = list(files_pool)
        random.shuffle(shuffled)
        candidates_to_read = shuffled[:max_files * 3]  # Leer más de los que mejoraremos

        files_data = await self.read_multiple_files(candidates_to_read)

        # Analizar en paralelo
        import asyncio
        analysis_tasks = []
        readable_files = []
        for path, data in files_data.items():
            if data.get("success") and data.get("content"):
                analysis_tasks.append(self.analyze_code_quality(path, data["content"]))
                readable_files.append(path)

        if not analysis_tasks:
            results["errors"].append("No se pudieron leer archivos para analizar")
            return results

        analyses = await asyncio.gather(*analysis_tasks, return_exceptions=True)

        # Construir lista ordenada por score (peor primero)
        file_analyses = []
        for path, analysis_result in zip(readable_files, analyses):
            if isinstance(analysis_result, dict) and analysis_result.get("success"):
                analysis = analysis_result["analysis"]
                score = analysis.get("quality_score", 100)
                file_analyses.append({
                    "path": path,
                    "analysis": analysis,
                    "score": score,
                    "sha": files_data[path].get("sha"),
                    "content": files_data[path].get("content"),
                })
                results["analyzed"].append({
                    "file": path,
                    "score": score,
                    "priority": analysis.get("improvement_priority", "media"),
                })

        file_analyses.sort(key=lambda x: x["score"])
        # Solo mejorar archivos con calidad < 80 o prioridad alta/media
        to_improve = [
            f for f in file_analyses
            if f["score"] < 80 or f["analysis"].get("improvement_priority") in ("alta", "media")
        ]

        if not to_improve:
            logger.info("[SelfImprovement] Todos los archivos tienen calidad aceptable")
            results["skipped"] = [f["path"] for f in file_analyses]
            return results

        improvements_done = 0
        for file_data in to_improve[:max_files]:
            if improvements_done >= max_files:
                break

            path = file_data["path"]
            logger.info("[SelfImprovement] Mejorando %s (score: %d)", path, file_data["score"])

            gen = await self.generate_improved_code(
                file_path=path,
                original_code=file_data["content"],
                analysis=file_data["analysis"],
                lessons=lessons,
            )

            if not gen.get("success"):
                logger.warning("[SelfImprovement] No se generó mejora para %s: %s", path, gen.get("error"))
                results["skipped"].append(path)
                continue

            push = await self.push_improvement(
                file_path=path,
                improved_code=gen["improved_code"],
                original_sha=file_data["sha"],
                improvements_applied=gen["improvements_applied"],
            )

            if push.get("success"):
                improvements_done += 1
                results["improved_files"].append({
                    "file": path,
                    "original_lines": gen["original_lines"],
                    "improved_lines": gen["improved_lines"],
                    "improvements_applied": gen["improvements_applied"],
                    "commit": push.get("commit_message", ""),
                })
            else:
                results["errors"].append(f"{path}: {push.get('error')}")

            if improvements_done < max_files:
                await asyncio.sleep(2)

        results["total_improved"] = len(results["improved_files"])
        results["success"] = len(results["improved_files"]) > 0 or len(results["errors"]) == 0
        return results

    # ══════════════════════════════════════════════════════════════
    # 6. HISTORIAL Y AUDITORÍA
    # ══════════════════════════════════════════════════════════════

    async def get_recent_commits(self, limit: int = 10) -> list[dict]:
        """Obtiene los commits más recientes para auditoría."""
        if not self._ok():
            return []
        try:
            res = await self._http.get(
                f"{GITHUB_API}/repos/{REPO}/commits?per_page={limit}",
                headers=self._headers,
            )
            if res.status_code == 200:
                return [
                    {
                        "sha": c["sha"][:8],
                        "message": c["commit"]["message"][:80],
                        "date": c["commit"]["author"]["date"],
                        "author": c["commit"]["author"]["name"],
                    }
                    for c in res.json()
                ]
        except Exception as exc:
            logger.error("[SelfImprovement] get_commits error: %s", exc)
        return []

    async def get_improvement_history(self) -> list[dict]:
        """Lista los commits de auto-mejora aplicados por ARIA."""
        commits = await self.get_recent_commits(limit=30)
        return [
            c for c in commits
            if "feat(" in c["message"] or "auto-mejora" in c["message"].lower()
        ]
