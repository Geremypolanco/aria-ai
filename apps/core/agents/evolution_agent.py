"""
evolution_agent.py — ARIA AI Self-Evolution Engine v3.

ARIA puede:
  1. Leer y analizar su propio código completo
  2. Generar versiones mejoradas con Qwen2.5-Coder
  3. Pushear mejoras a GitHub → deploy automático en Fly.io
  4. Descubrir e integrar nuevas APIs autónomamente
  5. Aprender de sus propios logs y optimizar su ciclo
  6. Proponer mejoras a archivos protegidos (requiere aprobación)
  7. Mantener un score de calidad del sistema en tiempo real
  8. Detectar y corregir errores de producción automáticamente
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
                "bug_detection", "bug_fixing", "feature_addition", "system_learning",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mode      = context.get("mode", "full")
        max_files = context.get("max_files", 2)
        max_apis  = context.get("max_apis", 1)
        mission   = context.get("mission", "maximize autonomous digital revenue")
        notify    = context.get("notify_telegram", True)

        results: dict[str, Any] = {
            "success": True,
            "agent": "evolution_agent",
            "mode": mode,
            "improvements": [],
            "new_apis": [],
            "system_score": 0,
        }

        try:
            # 1. Calcular score actual del sistema
            system_score = await self._calculate_system_score()
            results["system_score"] = system_score
            logger.info("[EvolutionAgent] System score: %s/100", system_score)

            # 2. Aprender de logs recientes
            lessons = await self._learn_from_logs()
            results["lessons_learned"] = lessons

            # 3. Auto-mejora de código
            if mode in ("full", "improve_only"):
                logger.info("[EvolutionAgent] Iniciando auto-mejora de código...")
                improvement_results = await self._run_code_improvement(max_files, lessons)
                results["improvements"] = improvement_results

            # 4. Descubrimiento e integración de APIs
            if mode in ("full", "discover_only"):
                logger.info("[EvolutionAgent] Descubriendo nuevas APIs...")
                api_results = await self._run_api_discovery(mission, max_apis)
                results["new_apis"] = api_results

            # 5. Análisis de arquitectura
            if mode in ("full", "analyze_only"):
                arch_analysis = await self._analyze_architecture()
                results["architecture_insights"] = arch_analysis

            # 6. Score post-evolución
            results["new_system_score"] = await self._calculate_system_score(
                post_improvement=True, improvements=results["improvements"]
            )
            results["score_delta"] = results["new_system_score"] - results["system_score"]

            # 7. Guardar y notificar
            await self._save_evolution_results(results)
            if notify:
                await self._notify_evolution_complete(results)

            await self._log(
                "evolution_complete",
                f"Mejoras: {len(results['improvements'])} | APIs: {len(results['new_apis'])} | Score: {results['system_score']}→{results['new_system_score']}",
            )

        except Exception as exc:
            logger.error("[EvolutionAgent] Error en ciclo de evolución: %s", exc)
            results["success"] = False
            results["error"] = str(exc)

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

            agents = ["pm_agent", "cfo_agent", "dev_agent", "marketing_agent", "support_agent"]
            alive_results = await asyncio.gather(
                *[cache.is_agent_alive(a) for a in agents], return_exceptions=True
            )
            alive_count = sum(1 for r in alive_results if r is True)
            score += alive_count * 5

            try:
                revenue = await db.get_total_revenue()
                if revenue > 100:  score += 10
                if revenue > 1000: score += 10
            except Exception:
                pass

            cycles = int(await cache.get("aria:cycle_count") or "0")
            score += min(cycles * 2, 10)

            improvements_total = int(await cache.get("aria:improvements_total") or "0")
            score += min(improvements_total * 3, 15)

            apis_raw = await cache.get("aria:integrated_apis")
            apis_count = len(json.loads(apis_raw)) if apis_raw else 0
            score += min(apis_count * 2, 10)

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

            errors = [l for l in logs if l.get("level") == "ERROR"]
            if not errors:
                return {"patterns": [], "recommendations": ["Sistema sin errores recientes"]}

            error_messages = [e.get("message", "") for e in errors[:10]]

            response = await self.think(
                system="Analiza estos errores de un sistema de IA autónoma y extrae patrones + recomendaciones concretas. Responde SOLO con JSON válido.",
                user=(
                    "Errores recientes del sistema ARIA:\n" + "\n".join(error_messages) +
                    "\n\nResponde: {\"patterns\": [str], \"file_fixes\": [{\"file\": str, \"fix\": str}], \"recommendations\": [str]}"
                ),
                model=AIModel.STRATEGY,
                json_mode=True,
            )

            if response and isinstance(response, dict):
                return response
            if response and isinstance(response, str):
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
            result = await engine.run_improvement_cycle(max_files=max_files, lessons=lessons)
            improved = result.get("improved_files", [])
            logger.info("[EvolutionAgent] Mejorados %d archivos", len(improved))
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
            result = await engine.run_discovery_cycle(mission=mission, max_new_apis=max_apis)
            integrated = result.get("integrated", [])
            logger.info("[EvolutionAgent] Integradas %d nuevas APIs", len(integrated))
            return integrated
        except Exception as exc:
            logger.error("[EvolutionAgent] api discovery error: %s", exc)
            return []

    # ══════════════════════════════════════════════════════════════
    # 5. ANÁLISIS DE ARQUITECTURA
    # ══════════════════════════════════════════════════════════════

    async def _analyze_architecture(self) -> dict[str, Any]:
        """Analiza la arquitectura completa y propone mejoras grandes."""
        try:
            from apps.core.tools.self_improvement import SelfImprovementEngine
            engine = SelfImprovementEngine()

            files_data = await engine.read_multiple_files([
                "apps/core/agents/orchestrator.py",
                "apps/core/main.py",
            ])

            combined_code = ""
            for path, data in files_data.items():
                if data.get("success"):
                    combined_code += f"\n\n# === {path} ===\n{data['content'][:2000]}"

            if not combined_code:
                return {"error": "No se pudieron leer los archivos de arquitectura"}

            analysis = await self.think(
                system="Arquitecto de software senior analizando un sistema de IA autónoma de negocios digitales.",
                user=(
                    f"Analiza esta arquitectura y propón las 3 mejoras más impactantes:\n{combined_code[:5000]}\n\n"
                    "Responde en JSON: {\"bottlenecks\": [str], \"big_improvements\": [{\"description\": str, \"impact\": str, \"file\": str}], \"missing_systems\": [str]}"
                ),
                model=AIModel.STRATEGY,
                json_mode=True,
            )

            arch_data = analysis if isinstance(analysis, dict) else {}

            # Crear approval requests para mejoras de archivos protegidos
            for improvement in arch_data.get("big_improvements", [])[:2]:
                if improvement.get("file"):
                    try:
                        from apps.core.memory.supabase_client import get_db
                        await get_db().create_approval_request(
                            agent="evolution_agent",
                            action_type="architecture_improvement",
                            description=improvement["description"],
                            data=improvement,
                        )
                    except Exception:
                        pass

            return arch_data

        except Exception as exc:
            logger.error("[EvolutionAgent] architecture analysis error: %s", exc)
        return {"bottlenecks": [], "big_improvements": [], "missing_systems": []}

    # ══════════════════════════════════════════════════════════════
    # 6. GUARDAR Y NOTIFICAR
    # ══════════════════════════════════════════════════════════════

    async def _save_evolution_results(self, results: dict) -> None:
        """Guarda resultados en Supabase + Redis."""
        try:
            from apps.core.memory.supabase_client import get_db
            from apps.core.memory.redis_client import get_cache
            db = get_db()
            cache = get_cache()

            # Actualizar contador de mejoras en Redis
            if results.get("improvements"):
                current = int(await cache.get("aria:improvements_total") or "0")
                await cache.set("aria:improvements_total", str(current + len(results["improvements"])))

            # Guardar en Supabase
            await db.log_system_event(
                agent="evolution_agent",
                event_type="evolution_cycle",
                data={
                    "mode": results.get("mode"),
                    "improvements_count": len(results.get("improvements", [])),
                    "new_apis_count": len(results.get("new_apis", [])),
                    "system_score": results.get("system_score"),
                    "new_system_score": results.get("new_system_score"),
                    "score_delta": results.get("score_delta", 0),
                },
            )
        except Exception as exc:
            logger.warning("[EvolutionAgent] save results error: %s", exc)

    async def _notify_evolution_complete(self, results: dict) -> None:
        """Notifica al supervisor via Telegram sobre la evolución."""
        try:
            improvements = results.get("improvements", [])
            new_apis = results.get("new_apis", [])
            score_old = results.get("system_score", 0)
            score_new = results.get("new_system_score", 0)
            delta = results.get("score_delta", 0)
            delta_emoji = "📈" if delta > 0 else ("📉" if delta < 0 else "➡️")

            lines = [
                f"🧬 <b>ARIA — Ciclo de Auto-Evolución Completo</b>",
                f"",
                f"📊 Score del sistema: {score_old}→{score_new} {delta_emoji} ({delta:+d} pts)",
            ]

            if improvements:
                lines.append(f"\n🔧 <b>Archivos mejorados ({len(improvements)}):</b>")
                for imp in improvements[:3]:
                    fname = imp.get("file", "?").split("/")[-1]
                    lines.append(f"  • <code>{fname}</code>")

            if new_apis:
                lines.append(f"\n🔌 <b>Nuevas APIs integradas ({len(new_apis)}):</b>")
                for api in new_apis[:2]:
                    lines.append(f"  • {api.get('name', '?')}")

            lessons = results.get("lessons_learned", {})
            recs = lessons.get("recommendations", [])
            if recs:
                lines.append(f"\n💡 <b>Insight:</b> {recs[0]}")

            await self._send_telegram("\n".join(lines))

        except Exception as exc:
            logger.warning("[EvolutionAgent] notify error: %s", exc)

    async def _send_telegram(self, message: str) -> None:
        """Envía mensaje de Telegram."""
        try:
            import httpx
            from apps.core.config import settings
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"https://api.telegram.org/bot{settings.TELEGRAM_TOKEN}/sendMessage",
                    json={
                        "chat_id": settings.TELEGRAM_CHAT_ID,
                        "text": message,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
        except Exception as exc:
            logger.warning("[EvolutionAgent] telegram error: %s", exc)
