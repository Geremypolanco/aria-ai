"""
Orchestrator — Director central de todos los agentes de Aria AI.

Responsabilidades:
- Recopila inteligencia de mercado
- Genera plan de acción con IA
- Ejecuta misiones en paralelo por grupos de prioridad
- Lazy loading de agentes para optimizar RAM
- Reporta resultados por Telegram
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.orchestrator")

TELEGRAM_API = "https://api.telegram.org/bot"


class Orchestrator(BaseAgent):
    """
    Director central del sistema Aria AI.
    Coordina todos los agentes especializados.
    """

    def __init__(self) -> None:
        super().__init__(
            name="orchestrator",
            description="Director central — coordina todos los agentes",
            capabilities=["market_analysis", "planning", "coordination", "reporting"],
        )
        self._agents: dict[str, BaseAgent] = {}
        self._cycle_count = 0

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Ciclo autónomo principal."""
        return await self.run_cycle()

    # ── CICLO PRINCIPAL ───────────────────────────────────

    async def _inject_content_mission(self, plan: dict) -> dict:
        """Asegura que siempre haya una misión de contenido en el plan."""
        missions = plan.get("missions", [])
        has_content = any(m.get("agent") == "content" for m in missions)
        if not has_content:
            missions.insert(0, {
                "agent": "content",
                "task": "full_pipeline",
                "priority": 1,
                "description": "Generar y publicar contenido monetizable",
            })
            plan["missions"] = missions
        return plan

    async def run_cycle(self) -> dict[str, Any]:
        """
        Ciclo autónomo completo:
        1. Inteligencia de mercado
        2. Plan de acción con IA
        3. Ejecución en paralelo por prioridad
        4. Reporte por Telegram
        """
        self._cycle_count += 1
        cycle_id = f"cycle_{self._cycle_count}_{int(time.time())}"
        logger.info("[Orchestrator] === INICIO CICLO %d ===", self._cycle_count)

        results: dict[str, Any] = {
            "cycle_id": cycle_id,
            "cycle_number": self._cycle_count,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "success": False,
        }

        try:
            # 1. Inteligencia de mercado
            intelligence = await self._gather_market_intelligence()

            # 2. Plan con IA
            plan = await self._generate_action_plan(intelligence)
            plan = await self._inject_content_mission(plan) if plan else None
            if not plan:
                logger.warning("[Orchestrator] Plan de IA vacío — abortando ciclo")
                return results

            # 3. Ejecutar misiones en paralelo
            mission_results = await self._execute_missions(plan)
            results["missions"] = mission_results
            results["success"] = True
            results["completed_at"] = datetime.now(timezone.utc).isoformat()

            # 4. Reporte Telegram
            await self._send_cycle_report(results, intelligence, plan)

            # 5. Guardar en Supabase
            await self._save_cycle(results)

            logger.info("[Orchestrator] === FIN CICLO %d — OK ===", self._cycle_count)
            return results

        except Exception as exc:
            logger.error("[Orchestrator] Error en ciclo: %s", exc)
            results["error"] = str(exc)
            await self._send_telegram(
                f"❌ <b>ARIA — ERROR EN CICLO {self._cycle_count}</b>\n<code>{str(exc)[:300]}</code>"
            )
            return results

    # ── INTELIGENCIA DE MERCADO ───────────────────────────

    async def _gather_market_intelligence(self) -> dict[str, Any]:
        """Recopila tendencias de mercado desde NewsAPI y SerpAPI."""
        intelligence: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trends": [],
            "news": [],
        }

        tasks = []
        if settings.NEWS_API_KEY:
            tasks.append(self._fetch_news_trends())
        if settings.SERP_API_KEY:
            tasks.append(self._fetch_serp_trends())

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, dict):
                    intelligence.update(r)

        # Siempre ejecutar content agent para monetización continua
        intelligence["_force_content_mission"] = True
        logger.info(
            "[Orchestrator] Inteligencia recopilada: %d noticias, %d tendencias",
            len(intelligence.get("news", [])),
            len(intelligence.get("trends", [])),
        )
        return intelligence

    async def _fetch_news_trends(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(
                    "https://newsapi.org/v2/top-headlines",
                    params={
                        "apiKey": settings.NEWS_API_KEY,
                        "language": "en",
                        "category": "technology",
                        "pageSize": 10,
                    },
                )
                if res.status_code == 200:
                    articles = res.json().get("articles", [])
                    return {
                        "news": [
                            {"title": a["title"], "source": a["source"]["name"]}
                            for a in articles
                            if a.get("title")
                        ]
                    }
        except Exception as exc:
            logger.warning("[Orchestrator] NewsAPI error: %s", exc)
        return {"news": []}

    async def _fetch_serp_trends(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(
                    "https://serpapi.com/search",
                    params={
                        "api_key": settings.SERP_API_KEY,
                        "engine": "google_trends",
                        "q": "digital products,online business,passive income",
                        "data_type": "TIMESERIES",
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    trends = data.get("interest_over_time", {}).get("timeline_data", [])
                    return {"trends": trends[:5]}
        except Exception as exc:
            logger.warning("[Orchestrator] SerpAPI error: %s", exc)
        return {"trends": []}

    # ── PLAN DE ACCIÓN ────────────────────────────────────

    async def _generate_action_plan(
        self, intelligence: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Genera un plan de acción priorizado con IA."""
        news_summary = "; ".join(
            [n["title"] for n in intelligence.get("news", [])[:5]]
        ) or "Sin noticias disponibles"

        plan = await self.think(
            system=(
                "Eres el sistema central de Aria AI. Tu misión es generar el máximo ROI "
                "de forma autónoma en mercados digitales globales. Piensa como un emprendedor "
                "experto con capital limitado y tiempo de ejecución ajustado. "
                "Prioriza acciones de ingreso inmediato."
            ),
            user=(
                f"Noticias actuales: {news_summary}\n\n"
                "Genera un plan de acción en JSON con esta estructura exacta:\n"
                "{\n"
                '  "market_focus": "nicho específico",\n'
                '  "opportunity_score": 1-10,\n'
                '  "primary_language": "es|en|pt",\n'
                '  "missions": [\n'
                '    {"agent": "pm", "priority": 1, "task": "descripción"},\n'
                '    {"agent": "cfo", "priority": 2, "task": "descripción"},\n'
                '    {"agent": "dev", "priority": 2, "task": "descripción"},\n'
                '    {"agent": "marketing", "priority": 3, "task": "descripción"}\n'
                "  ],\n"
                '  "expected_revenue_usd": 0.0,\n'
                '  "rationale": "explicación breve"\n'
                "}"
            ),
            model=AIModel.STRATEGY,
            json_mode=True,
        )
        return plan

    # ── EJECUCIÓN EN PARALELO ─────────────────────────────

    async def _execute_missions(
        self, plan: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Ejecuta misiones del plan en grupos de prioridad."""
        missions = plan.get("missions", [])
        if not missions:
            return []

        # Agrupar por prioridad
        by_priority: dict[int, list[dict]] = {}
        for m in missions:
            p = m.get("priority", 99)
            by_priority.setdefault(p, []).append(m)

        all_results = []
        for priority in sorted(by_priority.keys()):
            group = by_priority[priority]
            logger.info(
                "[Orchestrator] Ejecutando prioridad %d — %d misiones",
                priority, len(group)
            )
            tasks = [
                self._run_agent_mission(m["agent"], m["task"], plan)
                for m in group
            ]
            group_results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in group_results:
                if isinstance(result, Exception):
                    all_results.append({"success": False, "error": str(result)})
                else:
                    all_results.append(result)

        return all_results

    async def _run_agent_mission(
        self, agent_key: str, task: str, plan: dict[str, Any]
    ) -> dict[str, Any]:
        """Carga un agente lazily y ejecuta su misión."""
        agent = await self._get_agent(agent_key)
        if not agent:
            return {"success": False, "error": f"Agente '{agent_key}' no disponible"}
        context = {
            "task": task,
            "market_focus": plan.get("market_focus", ""),
            "primary_language": plan.get("primary_language", "en"),
        }
        return await agent.run(context)

    async def _get_agent(self, key: str) -> Optional[BaseAgent]:
        """Lazy loading de agentes — solo instancia cuando se necesita."""
        if key in self._agents:
            return self._agents[key]
        try:
            agent: Optional[BaseAgent] = None
            if key == "pm":
                from apps.core.agents.pm_agent import PMAgent
                agent = PMAgent()
            elif key == "cfo":
                from apps.core.agents.cfo_agent import CFOAgent
                agent = CFOAgent()
            elif key == "dev":
                from apps.core.agents.dev_agent import DevAgent
                agent = DevAgent()
            elif key == "marketing":
                from apps.core.agents.marketing_agent import MarketingAgent
                agent = MarketingAgent()
            elif key == "support":
                from apps.core.agents.support_agent import SupportAgent
                agent = SupportAgent()
            elif key == "content":
                from apps.core.agents.content_agent import ContentAgent
                agent = ContentAgent()
            if agent:
                await agent.start()
                self._agents[key] = agent
            return agent
        except Exception as exc:
            logger.warning("[Orchestrator] No se pudo cargar agente '%s': %s", key, exc)
            return None

    # ── REPORTES ──────────────────────────────────────────

    async def send_daily_report(self) -> None:
        """Reporte diario de ingresos y rendimiento."""
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            total_revenue = await db.get_total_revenue()
            by_platform = await db.get_revenue_by_platform()
            platform_lines = "\n".join(
                [f"  • {k}: ${v:.2f}" for k, v in by_platform.items()]
            ) or "  Sin ingresos registrados"

            agent_statuses = "\n".join(
                [f"  • {k}: {'🟢' if v._is_circuit_available() else '🔴'}" for k, v in self._agents.items()]
            ) or "  Sin agentes activos"

            message = (
                f"📊 <b>REPORTE DIARIO — ARIA AI</b>\n\n"
                f"💰 <b>Ingresos totales:</b> ${total_revenue:.2f} USD\n\n"
                f"<b>Por plataforma:</b>\n{platform_lines}\n\n"
                f"<b>Agentes:</b>\n{agent_statuses}\n\n"
                f"🔄 Ciclos ejecutados: {self._cycle_count}\n"
                f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            )
            await self._send_telegram(message)
        except Exception as exc:
            logger.error("[Orchestrator] Error en reporte diario: %s", exc)

    async def auto_evolve(self) -> None:
        """Ciclo de auto-evolución — analiza rendimiento y optimiza estrategias."""
        logger.info("[Orchestrator] Iniciando auto-evolución...")
        try:
            agent_stats = [a.get_status() for a in self._agents.values()]
            analysis = await self.think(
                system="Eres el sistema de auto-evolución de Aria AI. Analiza el rendimiento de los agentes y propón mejoras concretas.",
                user=(
                    f"Estadísticas de agentes: {agent_stats}\n"
                    "Propón ajustes de estrategia basados en tasas de éxito y revenue generado."
                ),
                model=AIModel.STRATEGY,
            )
            if analysis:
                await self._send_telegram(
                    f"🧬 <b>AUTO-EVOLUCIÓN</b>\n\n{analysis[:800]}"
                )
                logger.info("[Orchestrator] Auto-evolución completada")
        except Exception as exc:
            logger.error("[Orchestrator] Error en auto-evolución: %s", exc)

    async def _send_cycle_report(
        self,
        results: dict[str, Any],
        intelligence: dict[str, Any],
        plan: dict[str, Any],
    ) -> None:
        missions = results.get("missions", [])
        ok = sum(1 for m in missions if isinstance(m, dict) and m.get("success"))
        total = len(missions)
        message = (
            f"🔄 <b>CICLO {self._cycle_count} COMPLETADO</b>\n\n"
            f"🎯 Foco: {plan.get('market_focus', 'N/A')}\n"
            f"💡 Score: {plan.get('opportunity_score', 0)}/10\n"
            f"✅ Misiones: {ok}/{total}\n"
            f"💰 Revenue esperado: ${plan.get('expected_revenue_usd', 0):.2f}\n\n"
            f"<i>{plan.get('rationale', '')[:200]}</i>"
        )
        await self._send_telegram(message)

    async def _save_cycle(self, results: dict[str, Any]) -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            missions = results.get("missions", [])
            ok = sum(1 for m in missions if isinstance(m, dict) and m.get("success"))
            await db.save_cycle(
                self._cycle_count,
                {"missions": missions, "success_count": ok},
                duration_ms=0,
            )
        except Exception as exc:
            logger.warning("[Orchestrator] No se pudo guardar ciclo: %s", exc)

    def get_all_agent_statuses(self) -> list[dict[str, Any]]:
        return [a.get_status() for a in self._agents.values()]
