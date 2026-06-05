"""
orchestrator.py — Director central de ARIA AI. Prioridad absoluta: MONETIZACIÓN.

Responsabilidades:
- Recopila inteligencia de mercado REAL (internet: HN, Reddit, noticias, Google)
- Genera plan de accion con IA enfocado en INGRESOS REALES
- Ejecucion en paralelo por grupos de prioridad
- Monetizacion en CADA ciclo sin excepcion
- Reporta ingresos y oportunidades por Telegram
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
    Director central del sistema ARIA AI.
    Misión única: generar ingresos reales de forma autónoma.
    """

    def __init__(self) -> None:
        super().__init__(
            name="orchestrator",
            description="Director central — monetización autónoma y coordinación de agentes",
            capabilities=["market_analysis", "planning", "coordination", "reporting", "internet_research"],
        )
        self._agents: dict[str, BaseAgent] = {}
        self._cycle_count = 0

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Ciclo autónomo principal."""
        return await self.run_cycle()

    # ── CICLO PRINCIPAL ───────────────────────────────────────────

    async def run_cycle(self) -> dict[str, Any]:
        """
        Ciclo autónomo completo:
        1. Inteligencia de mercado real (internet)
        2. Plan de acción con IA — monetización primero
        3. Ejecución en paralelo por prioridad
        4. Reporte de resultados e ingresos
        """
        self._cycle_count += 1
        cycle_start = time.time()
        logger.info("[Orchestrator] ─── CICLO #%d INICIADO ───", self._cycle_count)

        # 1. Inteligencia de mercado REAL desde internet
        intelligence = await self._gather_market_intelligence()

        # 2. Plan de acción enfocado en monetización
        plan = await self._generate_monetization_plan(intelligence)
        if not plan.get("missions"):
            plan = self._fallback_monetization_plan()

        # 3. Garantizar que monetización siempre está primero
        plan = self._enforce_monetization_priority(plan)

        logger.info(
            "[Orchestrator] Plan: %d misiones — foco: %s",
            len(plan["missions"]),
            plan.get("focus", "monetizacion"),
        )

        # 4. Ejecutar misiones en paralelo por grupos de prioridad
        results = await self._execute_by_priority(plan["missions"])

        cycle_time = time.time() - cycle_start

        # 5. Calcular resumen de ingresos del ciclo
        revenue_summary = self._extract_revenue_summary(results)

        # 6. Reportar resultados
        await self._send_cycle_report(results, intelligence, revenue_summary, cycle_time)

        return {
            "cycle": self._cycle_count,
            "missions_run": len(results),
            "plan_focus": plan.get("focus", ""),
            "market_opportunity": intelligence.get("top_opportunity", ""),
            "revenue_summary": revenue_summary,
            "cycle_time_s": round(cycle_time, 1),
        }

    # ── INTELIGENCIA DE MERCADO REAL ─────────────────────────────

    async def _gather_market_intelligence(self) -> dict[str, Any]:
        """
        Recopila inteligencia de mercado REAL desde internet.
        Fuentes: HN, Reddit, noticias, búsqueda web.
        Sin esta información, ARIA trabaja a ciegas.
        """
        try:
            from apps.core.tools.web_tools import WebTools
            wt = WebTools()
            logger.info("[Orchestrator] Accediendo a internet para inteligencia de mercado...")
            intel = await wt.gather_market_intelligence(
                focus="digital products passive income AI tools saas affiliate marketing"
            )

            # Identificar la oportunidad principal de los datos
            all_titles = intel.get("trending_titles", [])
            intel["top_opportunity"] = all_titles[0] if all_titles else "mercado digital en expansion"
            intel["sources_used"] = intel.get("sources_available", [])

            logger.info(
                "[Orchestrator] Inteligencia recopilada de %d fuentes, %d tendencias",
                intel.get("sources_count", 0),
                intel.get("total_data_points", 0),
            )
            return intel

        except Exception as exc:
            logger.error("[Orchestrator] Error recopilando inteligencia: %s", exc)
            return {
                "error": str(exc),
                "sources_used": [],
                "trending_titles": [],
                "top_opportunity": "productos digitales",
            }

    # ── PLAN DE MONETIZACIÓN CON IA ───────────────────────────────

    async def _generate_monetization_plan(self, intelligence: dict[str, Any]) -> dict[str, Any]:
        """
        Genera plan de acción usando IA con contexto real de internet.
        Cada plan tiene SIEMPRE monetización como prioridad #1.
        """
        ai = get_ai_client()
        if not ai:
            logger.error("[Orchestrator] AI client no disponible")
            return {}

        # Preparar resumen de tendencias para la IA
        trending = intelligence.get("trending_titles", [])[:8]
        hn_top = intelligence.get("hacker_news", [{}])
        hn_title = hn_top[0].get("title", "") if hn_top else ""
        reddit_top = intelligence.get("reddit", [{}])
        reddit_title = reddit_top[0].get("title", "") if reddit_top else ""

        prompt = f"""Eres el director estratégico de ARIA AI, un sistema de monetización autónoma.

CONTEXTO DEL MERCADO HOY ({datetime.now(timezone.utc).strftime('%Y-%m-%d')}):
- Tendencia #1 HN: {hn_title or 'No disponible'}
- Tendencia #1 Reddit: {reddit_title or 'No disponible'}  
- Trending topics: {', '.join(trending[:5]) or 'No disponible'}
- Fuentes consultadas: {', '.join(intelligence.get('sources_used', ['ninguna']))}

AGENTES DISPONIBLES:
- content (ContentAgent): genera artículos SEO, los publica en Medium/Dev.to/Hashnode con links de afiliado
- cfo (CFOAgent): crea ebooks/PDFs y los vende en Gumroad/Stripe  
- affiliate (AffiliateAgent): busca y promociona productos en Amazon/ClickBank/Hotmart
- social (SocialAgent): distribuye contenido en Twitter/LinkedIn/Instagram/Buffer
- seo (SEOAgent): optimiza contenido para posicionamiento orgánico
- analytics (AnalyticsAgent): mide ingresos y tráfico reales
- evolution (EvolutionAgent): mejora el código de ARIA basado en errores de producción

MISIÓN: Genera el plan de acción para MAXIMIZAR INGRESOS en el próximo ciclo.

REGLAS ABSOLUTAS:
1. content y cfo SIEMPRE deben estar en el plan (prioridad 1 y 2)
2. Cada misión debe tener un objetivo de ingresos específico
3. Basa los temas en las tendencias REALES del mercado que ves arriba
4. evolution solo si hay errores críticos — prioridad baja

Responde SOLO con JSON válido (sin markdown):
{{
  "focus": "descripción del foco de monetización",
  "market_opportunity": "oportunidad específica identificada",
  "estimated_revenue_usd": 0,
  "missions": [
    {{
      "agent": "nombre_agente",
      "task": "descripción_específica",
      "priority": 1,
      "target_topic": "tema basado en tendencia real",
      "revenue_target_usd": 0,
      "rationale": "por qué esto genera dinero ahora"
    }}
  ]
}}"""

        try:
            response = await ai.chat.completions.create(
                model=AIModel.FAST,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            plan = __import__("json").loads(raw)
            logger.info("[Orchestrator] Plan IA generado: %s", plan.get("focus", ""))
            return plan
        except Exception as exc:
            logger.error("[Orchestrator] Error generando plan: %s", exc)
            return {}

    def _enforce_monetization_priority(self, plan: dict) -> dict:
        """
        Garantiza que las misiones de monetización SIEMPRE estén presentes y primero.
        Nunca puede haber un ciclo sin content o cfo.
        """
        missions = plan.get("missions", [])
        existing_agents = {m.get("agent") for m in missions}

        # Content es SIEMPRE prioridad 1
        if "content" not in existing_agents:
            missions.insert(0, {
                "agent": "content",
                "task": "full_pipeline",
                "priority": 1,
                "target_topic": "inteligencia artificial para negocios 2025",
                "revenue_target_usd": 50,
                "rationale": "Contenido SEO con afiliados = ingresos pasivos 24/7",
            })

        # CFO (productos digitales) siempre en top 3
        if "cfo" not in existing_agents:
            missions.insert(1, {
                "agent": "cfo",
                "task": "create_and_sell_ebook",
                "priority": 2,
                "target_topic": "productividad con IA",
                "revenue_target_usd": 100,
                "rationale": "Ebooks en Gumroad = ingresos directos sin intermediario",
            })

        # Reordenar por prioridad
        missions.sort(key=lambda x: x.get("priority", 99))
        plan["missions"] = missions
        return plan

    def _fallback_monetization_plan(self) -> dict:
        """Plan de monetización de emergencia cuando la IA falla."""
        return {
            "focus": "monetización directa — content + digital products",
            "market_opportunity": "mercado de herramientas IA en expansión",
            "missions": [
                {
                    "agent": "content",
                    "task": "full_pipeline",
                    "priority": 1,
                    "target_topic": "herramientas de IA para ganar dinero en 2025",
                    "revenue_target_usd": 50,
                },
                {
                    "agent": "cfo",
                    "task": "create_and_sell_ebook",
                    "priority": 2,
                    "target_topic": "guía de automatización con IA",
                    "revenue_target_usd": 100,
                },
                {
                    "agent": "affiliate",
                    "task": "promote_products",
                    "priority": 3,
                    "target_topic": "software de productividad",
                    "revenue_target_usd": 30,
                },
                {
                    "agent": "social",
                    "task": "distribute_content",
                    "priority": 4,
                    "target_topic": "IA y negocios digitales",
                    "revenue_target_usd": 10,
                },
            ],
        }

    # ── EJECUCIÓN DE MISIONES ────────────────────────────────────

    async def _execute_by_priority(self, missions: list[dict]) -> list[dict]:
        """
        Ejecuta misiones en paralelo por grupos de prioridad.
        Prioridad 1 primero, luego 2, etc.
        """
        if not missions:
            return []

        # Agrupar por prioridad
        groups: dict[int, list] = {}
        for m in missions:
            p = m.get("priority", 99)
            groups.setdefault(p, []).append(m)

        all_results = []
        for priority in sorted(groups.keys()):
            group = groups[priority]
            logger.info(
                "[Orchestrator] Ejecutando prioridad %d: %s",
                priority,
                [m.get("agent") for m in group],
            )
            tasks = [self._run_mission(m) for m in group]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, r in enumerate(results):
                if isinstance(r, Exception):
                    all_results.append({
                        "agent": group[i].get("agent"),
                        "success": False,
                        "error": str(r),
                    })
                else:
                    all_results.append(r)

        return all_results

    async def _run_mission(self, mission: dict) -> dict:
        """Ejecuta una misión individual cargando el agente correspondiente."""
        agent_name = mission.get("agent", "")
        task = mission.get("task", "")
        topic = mission.get("target_topic", "")

        try:
            agent = await self._get_agent(agent_name)
            if not agent:
                return {
                    "agent": agent_name,
                    "success": False,
                    "error": f"Agente '{agent_name}' no existe o no se pudo cargar",
                }

            context = {
                "task": task,
                "target_topic": topic,
                "market_focus": topic,
                "primary_language": getattr(settings, "CONTENT_LANGUAGE", "es"),
                "revenue_target_usd": mission.get("revenue_target_usd", 0),
                "rationale": mission.get("rationale", ""),
            }

            result = await agent.execute(context)
            result["agent"] = agent_name
            result["mission_task"] = task
            return result

        except Exception as exc:
            logger.error("[Orchestrator] Misión %s/%s falló: %s", agent_name, task, exc)
            return {"agent": agent_name, "success": False, "error": str(exc)}

    async def _get_agent(self, name: str) -> Optional[BaseAgent]:
        """Lazy loading de agentes — solo carga los que necesita."""
        if name in self._agents:
            return self._agents[name]

        agent_map = {
            "content": "apps.core.agents.content_agent.ContentAgent",
            "cfo": "apps.core.agents.cfo_agent.CFOAgent",
            "affiliate": "apps.core.agents.affiliate_agent.AffiliateAgent",
            "social": "apps.core.agents.social_agent.SocialAgent",
            "seo": "apps.core.agents.seo_agent.SEOAgent",
            "analytics": "apps.core.agents.analytics_agent.AnalyticsAgent",
            "evolution": "apps.core.agents.evolution_agent.EvolutionAgent",
            "market": "apps.core.agents.market_agent.MarketAgent",
        }

        module_path = agent_map.get(name)
        if not module_path:
            logger.warning("[Orchestrator] Agente '%s' no mapeado", name)
            return None

        try:
            mod_name, cls_name = module_path.rsplit(".", 1)
            mod = __import__(mod_name, fromlist=[cls_name])
            cls = getattr(mod, cls_name)
            agent = cls()
            self._agents[name] = agent
            return agent
        except Exception as exc:
            logger.error("[Orchestrator] No se pudo cargar agente '%s': %s", name, exc)
            return None

    # ── REPORTES ──────────────────────────────────────────────────

    def _extract_revenue_summary(self, results: list[dict]) -> dict[str, Any]:
        """Extrae resumen de ingresos de todos los resultados del ciclo."""
        total_usd = 0.0
        successful = 0
        failed = 0
        items_published = 0
        products_listed = 0

        for r in results:
            if r.get("success"):
                successful += 1
                revenue = r.get("revenue_usd", 0) or r.get("estimated_revenue_usd", 0) or 0
                total_usd += float(revenue)
                items_published += len(r.get("published", []))
                if r.get("gumroad") or r.get("stripe"):
                    products_listed += 1
            else:
                failed += 1

        return {
            "total_revenue_usd": round(total_usd, 2),
            "missions_successful": successful,
            "missions_failed": failed,
            "items_published": items_published,
            "products_listed": products_listed,
        }

    async def _send_cycle_report(
        self,
        results: list[dict],
        intelligence: dict,
        revenue_summary: dict,
        cycle_time: float,
    ) -> None:
        """Envía reporte del ciclo por Telegram."""
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
            return

        ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
        successful = revenue_summary["missions_successful"]
        failed = revenue_summary["missions_failed"]
        revenue = revenue_summary["total_revenue_usd"]
        published = revenue_summary["items_published"]
        products = revenue_summary["products_listed"]
        opportunity = intelligence.get("top_opportunity", "")[:80]
        sources = ", ".join(intelligence.get("sources_used", ["sin datos"]))

        status_icon = "✅" if failed == 0 else ("⚠️" if successful > 0 else "❌")

        lines = [
            f"<b>{status_icon} Ciclo #{self._cycle_count} completado</b> — {ts}",
            "",
            f"<b>Ingresos este ciclo:</b> ${revenue:.2f}",
            f"<b>Publicaciones:</b> {published} | <b>Productos:</b> {products}",
            f"<b>Misiones:</b> {successful} ✅  {failed} ❌ — {cycle_time:.0f}s",
            "",
        ]

        if opportunity:
            lines += [f"<b>Oportunidad detectada:</b> {opportunity}", ""]

        lines.append(f"<i>Fuentes: {sources}</i>")

        # Agregar errores si hay
        errors = [r for r in results if not r.get("success")]
        if errors:
            lines += ["", "<b>Errores:</b>"]
            for e in errors[:3]:
                lines.append(f"  • {e.get('agent', '?')}: {str(e.get('error', ''))[:80]}")

        text = "\n".join(lines)
        await self._telegram_send(text)

    async def _telegram_send(self, text: str) -> None:
        """Envía mensaje por Telegram."""
        url = f"{TELEGRAM_API}{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                })
        except Exception as exc:
            logger.error("[Orchestrator] Error Telegram: %s", exc)

    # ── STATUS ───────────────────────────────────────────────────

    async def get_status(self) -> dict[str, Any]:
        """Estado del orchestrator y agentes cargados."""
        capabilities = await self.check_capabilities()
        return {
            "cycle_count": self._cycle_count,
            "agents_loaded": list(self._agents.keys()),
            "capabilities": capabilities,
        }
