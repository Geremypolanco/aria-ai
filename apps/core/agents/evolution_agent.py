"""
evolution_agent.py — ARIA AI Self-Evolution Engine v2.

ARIA puede:
  1. Leer y analizar su propio código completo
  2. Generar versiones mejoradas con Qwen2.5-Coder
  3. Pushear mejoras a GitHub → deploy automático en Fly.io
  4. Descubrir e integrar nuevas APIs autónomamente
  5. Aprender de sus propios logs y optimizar su ciclo
  6. Proponer mejoras a archivos protegidos (requiere aprobación)
  7. Mantener un score de calidad del sistema en tiempo real
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Any
from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.evolution_agent")


class EvolutionAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="evolution_agent",
            description="Auto-evolución: analiza código, genera mejoras, integra APIs — ciclo infinito de mejora",
            capabilities=[
                "code_analysis", "code_improvement", "self_modification",
                "api_discovery", "api_integration", "performance_optimization",
                "bug_detection", "feature_addition", "system_learning",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mode       = context.get("mode", "full")          # full | improve_only | discover_only | analyze_only
        max_files  = context.get("max_files", 2)
        max_apis   = context.get("max_apis", 1)
        mission    = context.get("mission", "maximize autonomous digital revenue")
        notify     = context.get("notify_telegram", True)

        results: dict[str, Any] = {
            "success": True,
            "agent": "evolution_agent",
            "mode": mode,
            "improvements": [],
            "new_apis": [],
            "system_score": 0,
        }

        # ── 1. Calcular score actual del sistema
        system_score = await self._calculate_system_score()
        results["system_score"] = system_score
        logger.info("[EvolutionAgent] System score: %s/100", system_score)

        # ── 2. Aprender de logs recientes
        lessons = await self._learn_from_logs()
        results["lessons_learned"] = lessons

        # ── 3. Auto-mejora de código
        if mode in ("full", "improve_only"):
            logger.info("[EvolutionAgent] Iniciando auto-mejora de código...")
            improvement_results = await self._run_code_improvement(max_files, lessons)
            results["improvements"] = improvement_results

        # ── 4. Descubrimiento e integración de APIs
        if mode in ("full", "discover_only"):
            logger.info("[EvolutionAgent] Descubriendo nuevas APIs...")
            api_results = await self._run_api_discovery(mission, max_apis)
            results["new_apis"] = api_results

        # ── 5. Análisis de arquitectura (proponer mejoras grandes)
        if mode in ("full", "analyze_only"):
            arch_analysis = await self._analyze_architecture()
            results["architecture_insights"] = arch_analysis

        # ── 6. Calcular score post-evolución
        results["new_system_score"] = await self._calculate_system_score(post_improvement=True, improvements=results["improvements"])
        results["score_delta"] = results["new_system_score"] - results["system_score"]

        # ── 7. Guardar resultados y notificar
        await self._save_evolution_results(results)
        if notify:
            await self._notify_evolution_complete(results)

        await self._log(
            "evolution_complete",
            f"Mejoras: {len(results['improvements'])} | APIs: {len(results['new_apis'])} | Score: {results['system_score']}→{results['new_system_score']}",
        )
        return results

    # ══════════════════════════════════════════════════════════════
    # 1. SCORE DEL SISTEMA
    # ══════════════════════════════════════════════════════════════

    async def _calculate_system_score(self, post_improvement: bool = False, improvements: list | None = None) -> int:
        """Calcula el score de salud del sistema (0-100)."""
        score = 50  # Base

        try:
            from apps.core.memory.redis_client import get_cache
            from apps.core.memory.supabase_client import get_db
            cache = get_cache()
            db = get_db()

            # Agentes activos
            agents = ["pm_agent", "cfo_agent", "dev_agent", "marketing_agent", "support_agent"]
            alive_count = sum(1 for a in agents if await cache.is_agent_alive(a))
            score += alive_count * 5  # +5 por agente activo

            # Revenue generado
            try:
                revenue = await db.get_total_revenue()
                if revenue > 100:   score += 10
                if revenue > 1000:  score += 10
            except Exception:
                pass

            # Ciclos completados
            cycles = int(await cache.get("aria:cycle_count") or "0")
            score += min(cycles * 2, 10)

            # Mejoras aplicadas
            improvements_total = int(await cache.get("aria:improvements_total") or "0")
            score += min(improvements_total * 3, 15)

            # APIs integradas
            apis_raw = await cache.get("aria:integrated_apis")
            apis_count = len(json.loads(apis_raw)) if apis_raw else 0
            score += min(apis_count * 2, 10)

            # Post-improvement bonus
            if post_improvement and improvements:
                score += len(improvements) * 3

        except Exception as exc:
            logger.warning("[EvolutionAgent] score calc error: %s", exc)

        return min(score, 100)

    # ══════════════════════════════════════════════════════════════
    # 2. APRENDIZAJE DE LOGS
    # ══════════════════════════════════════════════════════════════

    async def _learn_from_logs(self) -> dict[str, Any]:
        """Analiza logs recientes para aprender qué mejorar."""
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            logs = await db.get_recent_logs(limit=50)
            if not logs:
                return {"patterns": [], "recommendations": []}

            # Agrupar errores
            errors = [l for l in logs if l.get("level") == "ERROR"]
            warnings = [l for l in logs if l.get("level") == "WARNING"]

            # Análisis con IA
            error_messages = [e.get("message", "") for e in errors[:10]]
            if not error_messages:
                return {"patterns": [], "recommendations": ["Sistema sin errores recientes"]}

            response = await self.think(
                system="Analiza estos errores de un sistema de IA autónoma y extrae patrones + recomendaciones concretas de mejora de código. Responde en JSON.",
                user=f"Errores recientes:\n" + "\n".join(error_messages) +
                     f"\n\nResponde: {{\"patterns\": [str], \"file_fixes\": [{{\"file\": str, \"fix\": str}}], \"recommendations\": [str]}}",
                model=AIModel.ANALYTICAL,
            )

            if response:
                import re
                match = re.search(r"\{.*\}", response, re.DOTALL)
                if match:
                    return json.loads(match.group())

        except Exception as exc:
            logger.error("[EvolutionAgent] learn_from_logs error: %s", exc)

        return {"patterns": [], "recommendations": []}

    # ══════════════════════════════════════════════════════════════
    # 3. AUTO-MEJORA DE CÓDIGO
    # ══════════════════════════════════════════════════════════════

    async def _run_code_improvement(self, max_files: int, lessons: dict) -> list[dict]:
        """Ejecuta el ciclo de mejora de código."""
        try:
            from apps.core.tools.self_improvement import SelfImprovementEngine
            engine = SelfImprovementEngine()

            # Incorporar lecciones aprendidas como mejoras adicionales
            specific_improvements = []
            for fix in lessons.get("file_fixes", [])[:3]:
                specific_improvements.append(fix.get("fix", ""))

            result = await engine.run_improvement_cycle(max_files=max_files)

            improved = result.get("improved_files", [])
            logger.info("[EvolutionAgent] Improved %d files", len(improved))
            return improved

        except Exception as exc:
            logger.error("[EvolutionAgent] code improvement error: %s", exc)
            return []

    # ══════════════════════════════════════════════════════════════
    # 4. DESCUBRIMIENTO E INTEGRACIÓN DE APIs
    # ══════════════════════════════════════════════════════════════

    async def _run_api_discovery(self, mission: str, max_apis: int) -> list[dict]:
        """Descubre e integra nuevas APIs autónomamente."""
        try:
            from apps.core.tools.api_discovery import APIDiscoveryEngine
            engine = APIDiscoveryEngine()

            result = await engine.run_discovery_cycle(
                mission=mission,
                max_new_apis=max_apis,
            )

            integrated = result.get("integrated", [])
            logger.info("[EvolutionAgent] Integrated %d new APIs", len(integrated))
            return integrated

        except Exception as exc:
            logger.error("[EvolutionAgent] api discovery error: %s", exc)
            return []

    # ══════════════════════════════════════════════════════════════
    # 5. ANÁLISIS DE ARQUITECTURA
    # ══════════════════════════════════════════════════════════════

    async def _analyze_architecture(self) -> dict[str, Any]:
        """
        Analiza la arquitectura completa del sistema y propone mejoras grandes.
        Para archivos protegidos, crea una solicitud de aprobación.
        """
        try:
            from apps.core.tools.self_improvement import SelfImprovementEngine
            engine = SelfImprovementEngine()

            # Leer el orquestador y main para análisis arquitectural
            files_to_read = [
                "apps/core/agents/orchestrator.py",
                "apps/core/main.py",
            ]
            files_data = await engine.read_multiple_files(files_to_read)

            combined_code = ""
            for path, data in files_data.items():
                if data.get("success"):
                    combined_code += f"\n\n# === {path} ===\n{data['content'][:2000]}"

            if not combined_code:
                return {"error": "No se pudieron leer los archivos de arquitectura"}

            analysis = await self.think(
                system="Eres un arquitecto de software senior analizando el core de un sistema de IA autónoma de negocios digitales.",
                user=(
                    f"Analiza esta arquitectura y propón las 3 mejoras más impactantes:\n{combined_code[:5000]}\n\n"
                    "Responde en JSON: {\"bottlenecks\": [str], \"big_improvements\": [{\"description\": str, \"impact\": str, \"file\": str}], \"missing_systems\": [str]}"
                ),
                model=AIModel.STRATEGY,
            )

            if analysis:
                import re
                match = re.search(r"\{.*\}", analysis, re.DOTALL)
                if match:
                    arch_data = json.loads(match.group())

                    # Crear approval requests para mejoras de archivos protegidos
                    for improvement in arch_data.get("big_improvements", [])[:2]:
                        if improvement.get("file"):
                            from apps.core.memory.supabase_client import get_db
                            await get_db().create_approval_request(
                                agent="evolution_agent",
                                action_type="architecture_improvement",
                                description=improvement["description"],
                                data=improvement,
                            )

                    return arch_data

        except Exception as exc:
            logger.error("[EvolutionAgent] architecture analysis error: %s", exc)

        return {"bottlenecks": [], "big_improvements": [], "missing_systems": []}

    # ══════════════════════════════════════════════════════════════
    # 6. GUARDAR Y NOTIFICAR
    # ══════════════════════════════════════════════════════════════

    async def _save_evolution_results(self, results: dict) -> None:
        """Guarda resultados en Supabase + Redis para memoria persistente."""
        try:
            from apps.core.memory.supabase_client import get_db
            from apps.core.memory.redis_client import get_cache
            db = get_db()
            cache = get_cache()

            # Guardar en Redis
            await cache.set(
                "aria:last_evolution",
                json.dumps({
                    "improvements": len(results.get("improvements", [])),
                    "new_apis": len(results.get("new_apis", [])),
                    "score_before": results.get("system_score", 0),
                    "score_after": results.get("new_system_score", 0),
                }),
                ttl_seconds=86400 * 30,
            )

            # Incrementar contador de evoluciones
            evo_count = int(await cache.get("aria:evolution_count") or "0") + 1
            await cache.set("aria:evolution_count", str(evo_count))

        except Exception as exc:
            logger.warning("[EvolutionAgent] save results error: %s", exc)

    async def _notify_evolution_complete(self, results: dict) -> None:
        """Notifica al propietario via Telegram sobre la evolución."""
        try:
            from apps.core.tools.telegram_bot import get_bot
            bot = get_bot()

            improvements = results.get("improvements", [])
            new_apis = results.get("new_apis", [])
            score_delta = results.get("score_delta", 0)

            msg_parts = [
                "🧬 <b>ARIA — Auto-Evolución Completada</b>\n",
                f"📈 Score del sistema: {results.get('system_score',0)} → {results.get('new_system_score',0)} "
                f"({'+'if score_delta>=0 else ''}{score_delta})",
            ]

            if improvements:
                msg_parts.append(f"\n\n<b>💻 Código mejorado ({len(improvements)} archivos):</b>")
                for imp in improvements[:3]:
                    f = imp.get("file", "").split("/")[-1]
                    delta = imp.get("lines_delta", 0)
                    msg_parts.append(f"  • {f} ({'+' if delta>=0 else ''}{delta} líneas)")

            if new_apis:
                msg_parts.append(f"\n\n<b>🔌 Nuevas APIs integradas ({len(new_apis)}):</b>")
                for api in new_apis[:3]:
                    msg_parts.append(f"  • {api.get('api','?')} → {api.get('file','').split('/')[-1]}")
                    if api.get("env_var"):
                        msg_parts.append(f"    ⚙️ Configurar: <code>{api['env_var']}</code> en Fly.io Secrets")

            lessons = results.get("lessons_learned", {})
            if lessons.get("recommendations"):
                msg_parts.append("\n\n<b>📚 Lecciones aprendidas:</b>")
                for r in lessons["recommendations"][:2]:
                    msg_parts.append(f"  • {r[:100]}")

            arch = results.get("architecture_insights", {})
            if arch.get("missing_systems"):
                msg_parts.append("\n\n<b>🏗 Sistemas faltantes detectados:</b>")
                for s in arch["missing_systems"][:2]:
                    msg_parts.append(f"  • {s[:80]}")

            msg_parts.append("\n\n🚀 Cambios deploying a Fly.io automáticamente.")

            await bot.send_to_owner("\n".join(msg_parts))

        except Exception as exc:
            logger.warning("[EvolutionAgent] notify error: %s", exc)
