"""
self_improvement.py — Motor de auto-mejora de código de ARIA AI.

ARIA puede:
  1. Leer su propio código vía GitHub API
  2. Analizar calidad y detectar mejoras
  3. Generar código mejorado con Qwen2.5-Coder
  4. Pushear las mejoras a GitHub (triggea deploy automático en Fly.io)
  5. Mantener historial de cambios y métricas de mejora
"""
from __future__ import annotations
import base64
import json
import logging
import re
from typing import Any, Optional
import httpx
from apps.core.config import settings

logger = logging.getLogger("aria.self_improvement")

GITHUB_API = "https://api.github.com"
REPO = settings.GITHUB_REPO or "Geremypolanco/aria-ai"
BRANCH = "main"


class SelfImprovementEngine:
    """Motor de auto-mejora: ARIA lee, analiza y mejora su propio código."""

    # Archivos que ARIA puede modificar autónomamente
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
    ]

    # Archivos CRÍTICOS — requieren aprobación humana antes de modificar
    PROTECTED_FILES = [
        "apps/core/config.py",
        "apps/core/tools/telegram_bot.py",
        "apps/core/agents/orchestrator.py",
        "apps/core/main.py",
        "fly.toml",
        "apps/core/Dockerfile",
    ]

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

    # ══════════════════════════════════════════════════════════════
    # 1. LECTURA DE CÓDIGO PROPIO
    # ══════════════════════════════════════════════════════════════

    async def read_file(self, file_path: str) -> dict[str, Any]:
        """Lee un archivo de su propio repositorio en GitHub."""
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
    # 2. ANÁLISIS DE CALIDAD DE CÓDIGO
    # ══════════════════════════════════════════════════════════════

    async def analyze_code_quality(self, file_path: str, code: str) -> dict[str, Any]:
        """
        Analiza la calidad del código con Qwen2.5-Coder.
        Detecta: bugs, ineficiencias, código duplicado, falta de manejo de errores,
        oportunidades de optimización, patrones mejorados.
        """
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = await get_ai_client()

            analysis_prompt = (
                f"Analiza este archivo Python de ARIA AI ({file_path}) y detecta:\n"
                "1. Bugs o errores potenciales\n"
                "2. Ineficiencias de rendimiento\n"
                "3. Código duplicado o redundante\n"
                "4. Falta de manejo de errores\n"
                "5. Oportunidades de optimización\n"
                "6. Funciones que debería tener pero no tiene\n"
                "7. APIs externas útiles que podría agregar\n\n"
                f"CÓDIGO (máx 4000 chars):\n{code[:4000]}\n\n"
                "Responde en JSON con esta estructura:\n"
                "{"
                " \'quality_score\': 0-100,"
                " \'bugs\': [{\'line\': N, \'issue\': str, \'fix\': str}],"
                " \'inefficiencies\': [str],"
                " \'missing_features\': [str],"
                " \'recommended_apis\': [{\'name\': str, \'url\': str, \'benefit\': str}],"
                " \'improvement_priority\': \'alta/media/baja\',"
                " \'summary\': str"
                "}"
            )

            response = await ai.complete(
                system="Eres un senior Python developer revisando código de un sistema de IA autónomo. Sé específico y accionable. Responde SOLO con JSON válido.",
                user=analysis_prompt,
                model=AIModel.CODE,
            )

            if response and response.success:
                try:
                    match = re.search(r"\{.*\}", response.content, re.DOTALL)
                    if match:
                        analysis = json.loads(match.group())
                        analysis["file"] = file_path
                        analysis["analyzed_lines"] = len(code.splitlines())
                        return {"success": True, "analysis": analysis}
                except json.JSONDecodeError:
                    pass

            return {"success": False, "error": "No se pudo parsear el análisis"}
        except Exception as exc:
            logger.error("[SelfImprovement] analyze error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def analyze_all_agents(self) -> list[dict]:
        """Analiza todos los agentes y prioriza cuáles mejorar."""
        import asyncio
        agent_files = [f for f in self.MODIFIABLE_FILES if "/agents/" in f]
        files_data = await self.read_multiple_files(agent_files)

        analysis_tasks = []
        for path, data in files_data.items():
            if data.get("success") and data.get("content"):
                analysis_tasks.append(self.analyze_code_quality(path, data["content"]))

        results = await asyncio.gather(*analysis_tasks, return_exceptions=True)

        analyses = []
        for r in results:
            if isinstance(r, dict) and r.get("success"):
                analyses.append(r["analysis"])

        # Ordenar por calidad (los de menor score primero — más urgentes)
        analyses.sort(key=lambda x: x.get("quality_score", 100))
        return analyses

    # ══════════════════════════════════════════════════════════════
    # 3. GENERACIÓN DE CÓDIGO MEJORADO
    # ══════════════════════════════════════════════════════════════

    async def generate_improved_code(
        self,
        file_path: str,
        original_code: str,
        analysis: dict,
        specific_improvement: str = "",
    ) -> dict[str, Any]:
        """
        Genera una versión mejorada del código usando Qwen2.5-Coder.
        Aplica las mejoras identificadas en el análisis.
        """
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = await get_ai_client()

            bugs = analysis.get("bugs", [])
            inefficiencies = analysis.get("inefficiencies", [])
            missing = analysis.get("missing_features", [])

            improvement_instructions = []
            if bugs:
                improvement_instructions.append(f"CORRIGE estos bugs: {json.dumps(bugs[:3])}")
            if inefficiencies:
                improvement_instructions.append(f"OPTIMIZA: {'; '.join(inefficiencies[:3])}")
            if missing:
                improvement_instructions.append(f"AGREGA: {'; '.join(missing[:3])}")
            if specific_improvement:
                improvement_instructions.append(f"MEJORA ESPECÍFICA: {specific_improvement}")

            prompt = (
                f"Eres Qwen2.5-Coder mejorando el código de ARIA AI.\n"
                f"Archivo: {file_path}\n\n"
                f"INSTRUCCIONES DE MEJORA:\n"
                + "\n".join(f"- {i}" for i in improvement_instructions)
                + f"\n\nCÓDIGO ORIGINAL:\n{original_code[:6000]}\n\n"
                "REGLAS ESTRICTAS:\n"
                "1. Devuelve SOLO el código Python completo mejorado\n"
                "2. Mantén toda la funcionalidad existente\n"
                "3. No elimines ninguna función existente — solo mejora y agrega\n"
                "4. Aplica TODAS las mejoras identificadas\n"
                "5. Añade docstrings donde falten\n"
                "6. Manejo de errores robusto en todas las funciones\n"
                "7. El código debe ser 100% compatible con el sistema existente\n"
                "8. NO incluyas explicaciones — solo el código Python"
            )

            response = await ai.complete(
                system="Senior Python developer. Return ONLY clean, complete, production-ready Python code. No explanations, no markdown fences, just the code.",
                user=prompt,
                model=AIModel.CODE,
                max_tokens=8000,
            )

            if not response or not response.success:
                return {"success": False, "error": "Sin respuesta del modelo"}

            improved_code = response.content.strip()

            # Limpiar si el modelo puso markdown fences
            if improved_code.startswith("```python"):
                improved_code = improved_code[9:]
            if improved_code.startswith("```"):
                improved_code = improved_code[3:]
            if improved_code.endswith("```"):
                improved_code = improved_code[:-3]
            improved_code = improved_code.strip()

            # Validar que es código Python válido
            validation = await self._validate_python_code(improved_code)
            if not validation["valid"]:
                return {
                    "success": False,
                    "error": f"Código inválido: {validation['error']}",
                    "raw_code": improved_code[:500],
                }

            # Calcular métricas de mejora
            original_lines = len(original_code.splitlines())
            improved_lines = len(improved_code.splitlines())

            return {
                "success": True,
                "file": file_path,
                "improved_code": improved_code,
                "original_lines": original_lines,
                "improved_lines": improved_lines,
                "lines_delta": improved_lines - original_lines,
                "improvements_applied": improvement_instructions,
            }
        except Exception as exc:
            logger.error("[SelfImprovement] generate_improved error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def _validate_python_code(self, code: str) -> dict[str, Any]:
        """Valida que el código es Python sintácticamente correcto."""
        try:
            import ast
            ast.parse(code)
            return {"valid": True}
        except SyntaxError as e:
            return {"valid": False, "error": f"SyntaxError línea {e.lineno}: {e.msg}"}
        except Exception as e:
            return {"valid": False, "error": str(e)}

    # ══════════════════════════════════════════════════════════════
    # 4. PUSH DE MEJORAS A GITHUB → DEPLOY AUTOMÁTICO
    # ══════════════════════════════════════════════════════════════

    async def push_improvement(
        self,
        file_path: str,
        improved_code: str,
        commit_message: str,
        require_approval: bool = False,
    ) -> dict[str, Any]:
        """
        Pushea código mejorado a GitHub.
        → GitHub Actions detecta el push → Deploy automático a Fly.io.
        Si require_approval=True, crea una approval request en Supabase.
        """
        if not self._ok():
            return {"success": False, "error": "GITHUB_TOKEN no configurado"}

        # Archivos protegidos requieren aprobación
        is_protected = any(p in file_path for p in self.PROTECTED_FILES)
        if is_protected or require_approval:
            return await self._request_human_approval(file_path, improved_code, commit_message)

        try:
            # Obtener SHA actual del archivo
            file_data = await self.read_file(file_path)
            if not file_data.get("success"):
                return {"success": False, "error": f"No se pudo leer {file_path}"}

            sha = file_data.get("sha", "")
            body = {
                "message": commit_message,
                "content": base64.b64encode(improved_code.encode()).decode(),
                "branch": BRANCH,
                "sha": sha,
            }

            res = await self._http.put(
                f"{GITHUB_API}/repos/{REPO}/contents/{file_path}",
                headers=self._headers,
                json=body,
            )

            if res.status_code in (200, 201):
                commit_sha = res.json().get("commit", {}).get("sha", "")
                logger.info("[SelfImprovement] ✅ Pushed %s — SHA: %s", file_path, commit_sha[:7])

                # Guardar en memoria de ARIA
                await self._save_improvement_log(file_path, commit_message, commit_sha)

                return {
                    "success": True,
                    "file": file_path,
                    "commit_sha": commit_sha,
                    "message": commit_message,
                    "deploy_triggered": True,
                    "note": "GitHub Actions deploying to Fly.io automatically",
                }
            return {"success": False, "error": f"GitHub API HTTP {res.status_code}: {res.text[:300]}"}
        except Exception as exc:
            logger.error("[SelfImprovement] push error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def _request_human_approval(self, file_path: str, code: str, message: str) -> dict[str, Any]:
        """Crea una solicitud de aprobación para archivos protegidos."""
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            await db.create_approval_request(
                agent="evolution_agent",
                action_type="code_modification",
                description=f"ARIA quiere modificar {file_path}: {message}",
                data={"file": file_path, "commit_message": message, "code_preview": code[:1000]},
            )
            return {
                "success": True,
                "status": "awaiting_approval",
                "file": file_path,
                "message": "Solicitud enviada a Telegram para aprobación humana",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _save_improvement_log(self, file_path: str, message: str, sha: str) -> None:
        """Guarda el historial de mejoras en Supabase + Redis."""
        try:
            from apps.core.memory.supabase_client import get_db
            from apps.core.memory.redis_client import get_cache
            db = get_db()
            cache = get_cache()

            # Log en Supabase
            await db.log_event(
                level="SUCCESS",
                agent="evolution_agent",
                message=f"Code improved: {file_path} — {message}",
                metadata={"sha": sha},
            )

            # Contador de mejoras en Redis
            count_key = "aria:improvements_total"
            count = int(await cache.get(count_key) or "0") + 1
            await cache.set(count_key, str(count))

            # Historial de archivos mejorados
            history_key = "aria:improvement_history"
            history_raw = await cache.get(history_key)
            history = json.loads(history_raw) if history_raw else []
            history.insert(0, {"file": file_path, "message": message, "sha": sha[:7]})
            await cache.set(history_key, json.dumps(history[:50]))

        except Exception as exc:
            logger.warning("[SelfImprovement] log error: %s", exc)

    # ══════════════════════════════════════════════════════════════
    # 5. CICLO COMPLETO DE AUTO-MEJORA
    # ══════════════════════════════════════════════════════════════

    async def run_improvement_cycle(self, max_files: int = 3) -> dict[str, Any]:
        """
        Ejecuta un ciclo completo de auto-mejora:
        1. Analiza todos los agentes y herramientas
        2. Identifica los N archivos con más oportunidades de mejora
        3. Genera código mejorado para cada uno
        4. Pushea las mejoras a GitHub (deploy automático)
        """
        logger.info("[SelfImprovement] Iniciando ciclo de auto-mejora...")
        results = {"success": True, "improved_files": [], "failed": [], "total_analyzed": 0}

        try:
            # Analizar todos los agentes
            analyses = await self.analyze_all_agents()
            results["total_analyzed"] = len(analyses)

            # Tomar los N con mayor prioridad de mejora (menor score)
            candidates = [a for a in analyses if a.get("improvement_priority") in ("alta", "media")][:max_files]

            if not candidates:
                # Si no hay candidatos obvios, tomar los de menor score
                candidates = analyses[:max_files]

            for analysis in candidates:
                file_path = analysis.get("file", "")
                if not file_path:
                    continue

                logger.info("[SelfImprovement] Mejorando: %s (score: %s)", file_path, analysis.get("quality_score"))

                # Leer código original
                file_data = await self.read_file(file_path)
                if not file_data.get("success"):
                    results["failed"].append({"file": file_path, "error": "No se pudo leer"})
                    continue

                original_code = file_data["content"]

                # Generar código mejorado
                improvement = await self.generate_improved_code(file_path, original_code, analysis)
                if not improvement.get("success"):
                    results["failed"].append({"file": file_path, "error": improvement.get("error", "")})
                    continue

                # Pushear a GitHub
                commit_msg = (
                    f"feat(evolution): Auto-improve {file_path.split('/')[-1]} "
                    f"[score: {analysis.get('quality_score',0)}→estimated +10] "
                    f"— {', '.join(improvement.get('improvements_applied',['optimized'])[:2])}"
                )[:200]

                push_result = await self.push_improvement(
                    file_path,
                    improvement["improved_code"],
                    commit_msg,
                )

                if push_result.get("success"):
                    results["improved_files"].append({
                        "file": file_path,
                        "old_score": analysis.get("quality_score", 0),
                        "lines_delta": improvement.get("lines_delta", 0),
                        "commit": push_result.get("commit_sha", "")[:7],
                        "improvements": improvement.get("improvements_applied", []),
                    })
                else:
                    results["failed"].append({"file": file_path, "error": push_result.get("error", "")})

        except Exception as exc:
            logger.error("[SelfImprovement] Cycle error: %s", exc)
            results["error"] = str(exc)

        return results

    async def get_improvement_stats(self) -> dict[str, Any]:
        """Estadísticas de mejoras realizadas."""
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            total = await cache.get("aria:improvements_total") or "0"
            history_raw = await cache.get("aria:improvement_history")
            history = json.loads(history_raw) if history_raw else []
            return {
                "total_improvements": int(total),
                "recent_improvements": history[:10],
            }
        except Exception:
            return {"total_improvements": 0, "recent_improvements": []}
