"""
orchestrator.py — Director central de ARIA AI. Prioridad absoluta: MONETIZACION.

Mejoras v4:
- Proactividad 24/7 reforzada
- Prioridad en Shopify, Zapier y High-Ticket
- Expansion automatica de busqueda en WebTools
- Fix: Dashboard de ingresos unificado con tabla 'revenue'
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.orchestrator")

TELEGRAM_API = "https://api.telegram.org/bot"


class Orchestrator(BaseAgent):
    """
    Director central del sistema ARIA AI.
    Mision: generar ingresos reales de forma autonoma.
    Motor IA: HuggingFace (primario) → Groq → OpenAI
    """

    def __init__(self) -> None:
        super().__init__(
            name="orchestrator",
            description="Director central — monetizacion autonoma y coordinacion de agentes",
            capabilities=["market_analysis", "planning", "coordination", "reporting"],
        )
        self._agents: dict[str, BaseAgent] = {}
        self._cycle_count = 0

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        return await self.run_cycle()

    async def execute_mission(self, mission_text: str) -> dict[str, Any]:
        """Ejecuta una misión específica bajo demanda (ej: desde Telegram)."""
        logger.info("[Orchestrator] Ejecutando misión: %s", mission_text)

        # Misión de creación multimedia/software
        if "create" in mission_text.lower():
            parts = mission_text.split()
            fmt = parts[1] if len(parts) > 1 else "image"
            topic = " ".join(parts[3:]) if len(parts) > 3 else "negocios digitales"

            agent = await self._get_agent("content")
            if agent:
                return await agent.execute(
                    {"task": "creative_creation", "format": fmt, "topic": topic}
                )

        return {"success": False, "error": "Misión no reconocida o agente no disponible"}

    # ── CICLO PRINCIPAL ───────────────────────────────────────────

    async def run_cycle(self) -> dict[str, Any]:
        """
        Ciclo autonomo completo:
        1. Inteligencia de mercado real (internet)
        2. Plan de accion con IA (HF primario)
        3. Ejecucion en paralelo por prioridad
        4. Logging en Supabase
        5. Reporte por Telegram
        """
        self._cycle_count += 1
        cycle_start = time.time()
        logger.info("[Orchestrator] ─── CICLO #%d INICIADO ───", self._cycle_count)

        # Asegurar que los agentes estén cargados
        if not self._agents:
            self._auto_discover_agents()

        # Log inicio en Supabase
        cycle_id = await self._log_cycle_start()

        # 1. Inteligencia de mercado REAL
        intelligence = await self._gather_market_intelligence()

        # 2. Plan de monetizacion con IA (HuggingFace primario)
        plan = await self._generate_monetization_plan(intelligence)
        if not plan.get("missions"):
            plan = self._fallback_monetization_plan()

        # 3. Monetizacion siempre primero
        plan = self._enforce_monetization_priority(plan)

        logger.info(
            "[Orchestrator] Plan: %d misiones — foco: %s",
            len(plan["missions"]),
            plan.get("focus", "monetizacion"),
        )

        # 4. Ejecutar misiones en paralelo por prioridad
        results = await self._execute_by_priority(plan["missions"])

        cycle_time = time.time() - cycle_start
        revenue_summary = self._extract_revenue_summary(results)

        # 5. Log resultado en Supabase
        await self._log_cycle_end(cycle_id, results, revenue_summary)

        # 6. Reportar por Telegram
        await self._send_cycle_report(results, intelligence, revenue_summary, cycle_time)

        return {
            "cycle": self._cycle_count,
            "missions_run": len(results),
            "plan_focus": plan.get("focus", ""),
            "market_opportunity": intelligence.get("top_opportunity", ""),
            "revenue_summary": revenue_summary,
            "cycle_time_s": round(cycle_time, 1),
        }

    # ── SUPABASE LOGGING ──────────────────────────────────────────

    async def _log_cycle_start(self) -> str | None:
        """Registra inicio del ciclo en Supabase."""
        try:
            from apps.core.tools.db_setup import log_to_supabase

            data = {
                "status": "running",
                "started_at": datetime.now(UTC).isoformat(),
                "summary": {"cycle_number": self._cycle_count},
            }
            await log_to_supabase("autonomous_cycles", data)
        except Exception as exc:
            logger.debug("[Orchestrator] DB log start error: %s", exc)
        return None

    async def _log_cycle_end(
        self, cycle_id: str | None, results: list[dict], revenue: dict
    ) -> None:
        """Registra fin del ciclo en Supabase."""
        try:
            from apps.core.tools.db_setup import log_to_supabase

            errors = [r.get("error", "") for r in results if not r.get("success")]
            data = {
                "status": "completed",
                "completed_at": datetime.now(UTC).isoformat(),
                "revenue_generated": revenue.get("total_revenue_usd", 0),
                "articles_published": revenue.get("items_published", 0),
                "products_created": revenue.get("products_listed", 0),
                "errors": errors[:5],
                "summary": {
                    "cycle_number": self._cycle_count,
                    "missions_ok": revenue.get("missions_successful", 0),
                    "missions_fail": revenue.get("missions_failed", 0),
                },
            }
            await log_to_supabase("autonomous_cycles", data)
        except Exception as exc:
            logger.debug("[Orchestrator] DB log end error: %s", exc)

    # ── INTELIGENCIA DE MERCADO REAL ─────────────────────────────

    async def _gather_market_intelligence(self) -> dict[str, Any]:
        """Recopila inteligencia de mercado REAL desde internet."""
        try:
            from apps.core.tools.web_tools import WebTools

            wt = WebTools()
            logger.info("[Orchestrator] Accediendo a internet para inteligencia de mercado...")
            intel = await wt.gather_market_intelligence(
                focus="digital products passive income AI tools saas affiliate marketing"
            )
            all_titles = intel.get("trending_titles", [])
            intel["top_opportunity"] = (
                all_titles[0] if all_titles else "mercado digital en expansion"
            )
            intel["sources_used"] = intel.get("sources_available", [])
            logger.info(
                "[Orchestrator] Inteligencia: %d fuentes, %d tendencias",
                intel.get("sources_count", 0),
                intel.get("total_data_points", 0),
            )
            return intel
        except Exception as exc:
            logger.error("[Orchestrator] Error inteligencia: %s", exc)
            return {
                "error": str(exc),
                "sources_used": [],
                "trending_titles": [],
                "top_opportunity": "productos digitales con IA",
            }

    # ── PLAN DE MONETIZACION CON IA ───────────────────────────────

    async def _generate_monetization_plan(self, intelligence: dict[str, Any]) -> dict[str, Any]:
        """
        Genera plan de accion usando IA detallado.
        """
        ai = get_ai_client()
        if not ai:
            logger.error("[Orchestrator] AI client no disponible")
            return {}

        trending = intelligence.get("trending_titles", [])[:8]
        hn_top = intelligence.get("hacker_news", [{}])
        hn_title = hn_top[0].get("title", "") if hn_top else ""
        reddit_top = intelligence.get("reddit", [{}])
        reddit_title = reddit_top[0].get("title", "") if reddit_top else ""

        system_prompt = (
            "Eres el director estrategico de ARIA AI, un sistema de monetizacion autonoma proactiva 24/7. "
            "Tu mision es identificar oportunidades de ingresos masivos y ejecutarlas sin omitir ningun detalle. "
            "Priorizas Shopify, Zapier y servicios High-Ticket sobre contenido SEO tradicional. "
            "Responde SOLO con JSON valido sin markdown."
        )

        user_prompt = f"""CONTEXTO DEL MERCADO ({datetime.now(UTC).strftime('%Y-%m-%d')}):
- Tendencia HackerNews: {hn_title or 'No disponible'}
- Tendencia Reddit: {reddit_title or 'No disponible'}
- Trending topics: {', '.join(trending[:5]) or 'IA, negocios digitales, automatizacion'}

REGLAS DE ORO:
1. No omitas detalles: cada mision debe tener un 'target_topic' especifico y ambicioso.
2. Monetizacion Directa: Prioriza al agente 'ecommerce' y 'cfo' para Shopify y High-Ticket.
3. Calidad: Los productos deben ser de alta calidad, con listings optimizados y SEO.

AGENTES DISPONIBLES:
- ecommerce: gestiona Shopify, crea productos, listings optimizados, inventario, imagenes y videos.
- cfo: gestiona pagos, Gumroad, y estrategia de ventas High-Ticket ($997+).
- content: genera articulos SEO con links de afiliado.
- pm: investiga nichos rentables y estrategias de automatizacion Zapier.
- social: distribuye contenido en redes via Buffer.

Genera el plan de monetizacion detallado. JSON esperado:
{{
  "focus": "descripcion estrategica del foco de hoy",
  "market_opportunity": "oportunidad detectada en tendencias",
  "estimated_revenue_usd": 0,
  "missions": [
    {{
      "agent": "ecommerce",
      "task": "full_ecommerce_pipeline",
      "priority": 1,
      "target_topic": "producto/servicio especifico de alto valor",
      "revenue_target_usd": 500,
      "rationale": "explicacion detallada de por que este producto hoy"
    }}
  ]
}}"""

        try:
            plan = await ai.complete_json(
                system=system_prompt,
                user=user_prompt,
                model=AIModel.STRATEGY,
                max_tokens=1200,
                agent_name="orchestrator",
            )
            if plan and plan.get("missions"):
                logger.info("[Orchestrator] Plan IA (HF): %s", plan.get("focus", ""))
                return plan
        except Exception as exc:
            logger.error("[Orchestrator] Error generando plan: %s", exc)

        return {}

    def _enforce_monetization_priority(self, plan: dict) -> dict:
        """Garantiza que content y cfo SIEMPRE esten en el plan."""
        missions = plan.get("missions", [])
        existing_agents = {m.get("agent") for m in missions}

        if "ecommerce" not in existing_agents:
            missions.insert(
                0,
                {
                    "agent": "ecommerce",
                    "task": "full_ecommerce_pipeline",
                    "priority": 1,
                    "target_topic": "productos premium para nicho tech/IA",
                    "revenue_target_usd": 500,
                    "rationale": "Shopify + Zapier = ingresos escalables",
                },
            )

        if "cfo" not in existing_agents:
            missions.insert(
                1,
                {
                    "agent": "cfo",
                    "task": "high_ticket_sales_strategy",
                    "priority": 2,
                    "target_topic": "servicios de consultoria IA high-ticket",
                    "revenue_target_usd": 1000,
                    "rationale": "Ventas high-ticket maximizan el ROI",
                },
            )

        missions.sort(key=lambda x: x.get("priority", 99))
        plan["missions"] = missions
        return plan

    def _fallback_monetization_plan(self) -> dict:
        """Plan de emergencia cuando la IA no responde."""
        return {
            "focus": "monetizacion multicanal — e-commerce Shopify + contenido + high-ticket",
            "market_opportunity": "e-commerce y servicios premium con IA en expansion",
            "missions": [
                {
                    "agent": "ecommerce",
                    "task": "full_ecommerce_pipeline",
                    "priority": 1,
                    "target_topic": "productos de alto valor con IA",
                    "revenue_target_usd": 500,
                    "rationale": "Shopify + Zapier + High-Ticket = maximos ingresos",
                },
                {
                    "agent": "content",
                    "task": "full_pipeline",
                    "priority": 2,
                    "target_topic": "herramientas de IA para e-commerce 2025",
                    "revenue_target_usd": 50,
                },
                {
                    "agent": "cfo",
                    "task": "create_and_sell_ebook",
                    "priority": 3,
                    "target_topic": "guia de automatizacion con IA y Shopify",
                    "revenue_target_usd": 100,
                },
            ],
        }

    # ── EJECUCION DE MISIONES ────────────────────────────────────

    async def _execute_by_priority(self, missions: list[dict]) -> list[dict]:
        """Ejecuta misiones en paralelo por grupos de prioridad."""
        if not missions:
            return []

        groups: dict[int, list] = {}
        for m in missions:
            p = m.get("priority", 99)
            groups.setdefault(p, []).append(m)

        all_results = []
        for priority in sorted(groups.keys()):
            group = groups[priority]
            logger.info(
                "[Orchestrator] Prioridad %d: %s",
                priority,
                [m.get("agent") for m in group],
            )
            tasks = [self._run_mission(m) for m in group]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, r in enumerate(results):
                if isinstance(r, Exception):
                    all_results.append(
                        {
                            "agent": group[i].get("agent"),
                            "success": False,
                            "error": str(r),
                        }
                    )
                else:
                    all_results.append(r)

        return all_results

    async def _run_mission(self, mission: dict) -> dict:
        """Ejecuta una mision individual."""
        agent_name = mission.get("agent", "")
        task = mission.get("task", "")
        topic = mission.get("target_topic", "")

        try:
            agent = await self._get_agent(agent_name)
            if not agent:
                return {
                    "agent": agent_name,
                    "success": False,
                    "error": f"Agente '{agent_name}' no encontrado",
                }

            logger.info("[Orchestrator] Ejecutando: %s -> %s (%s)", agent_name, task, topic)
            result = await agent.run(mission)

            # Notificación de Zapier deshabilitada temporalmente a petición del usuario
            # if result.get("success") and agent_name in ["cfo", "ecommerce"] and result.get("shop_url"):
            #     await self._notify_zapier_new_product(result)

            return result
        except Exception as exc:
            logger.error("[Orchestrator] Error en mision %s: %s", agent_name, exc)
            return {"agent": agent_name, "success": False, "error": str(exc)}

    async def _get_agent(self, name: str) -> BaseAgent | None:
        """Obtiene o carga un agente por nombre."""
        if name in self._agents:
            return self._agents[name]

        # Auto-discovery si no esta cargado
        self._auto_discover_agents()
        return self._agents.get(name)

    def _auto_discover_agents(self) -> None:
        """Carga dinamicamente todos los agentes disponibles."""
        try:
            from apps.core.agents.cfo_agent import CFOAgent
            from apps.core.agents.content_agent import ContentAgent
            from apps.core.agents.ecommerce_agent import EcommerceAgent
            from apps.core.agents.pm_agent import PMAgent

            self._agents["content"] = ContentAgent()
            self._agents["cfo"] = CFOAgent()
            self._agents["pm"] = PMAgent()
            self._agents["ecommerce"] = EcommerceAgent()

            # Agentes opcionales o en desarrollo
            try:
                from apps.core.agents.affiliate_agent import AffiliateAgent

                self._agents["affiliate"] = AffiliateAgent()
            except ImportError:
                logger.debug("[Orchestrator] AffiliateAgent no disponible")

            try:
                from apps.core.agents.social_agent import SocialAgent

                self._agents["social"] = SocialAgent()
            except ImportError:
                logger.debug("[Orchestrator] SocialAgent no disponible")

            logger.info("[Orchestrator] %d agentes cargados correctamente", len(self._agents))
        except Exception as exc:
            logger.error("[Orchestrator] Error en auto-discovery: %s", exc)

    def _extract_revenue_summary(self, results: list[dict]) -> dict:
        """Calcula resumen de ingresos y exitos del ciclo."""
        summary = {
            "total_revenue_usd": 0.0,
            "items_published": 0,
            "products_listed": 0,
            "missions_successful": 0,
            "missions_failed": 0,
        }
        for r in results:
            if r.get("success"):
                summary["missions_successful"] += 1
                summary["total_revenue_usd"] += float(r.get("revenue_usd", 0))
                if r.get("agent") == "content":
                    summary["items_published"] += 1
                if r.get("agent") in ["cfo", "ecommerce"]:
                    summary["products_listed"] += 1
            else:
                summary["missions_failed"] += 1
        return summary

    async def get_status(self) -> dict[str, Any]:
        """Retorna el estado actual del Orchestrator para el bot de Telegram."""
        if not self._agents:
            self._auto_discover_agents()

        caps = self.check_capabilities()
        return {
            "cycle_count": self._cycle_count,
            "agents_loaded": list(self._agents.keys()),
            "capabilities": dict.fromkeys(caps.get("available", []), True),
            "missing_capabilities": caps.get("unavailable", []),
        }

    async def _send_cycle_report(
        self, results: list, intelligence: dict, revenue: dict, duration: float
    ) -> None:
        """Envia reporte del ciclo a Telegram con screenshots si existen."""
        import html as _html

        from apps.core.tools.telegram_bot import get_bot

        bot = get_bot()
        chat_id = str(settings.TELEGRAM_CHAT_ID) if settings.TELEGRAM_CHAT_ID else None

        ok = revenue["missions_failed"] == 0
        icon = "✅" if ok else "⚠️"
        total_rev = revenue["total_revenue_usd"]
        foco = _html.escape(intelligence.get("top_opportunity", "Monetización"))
        misiones = f"{revenue['missions_successful']}/{len(results)}"

        kw = 11
        data_rows = [
            f"{'Duración':<{kw}} {duration:.1f}s",
            f"{'Ingresos':<{kw}} ${total_rev:.2f}",
            f"{'Foco':<{kw}} {foco}",
            f"{'Misiones':<{kw}} {misiones}",
        ]
        if revenue.get("products_listed", 0) > 0:
            data_rows.append(f"{'Productos':<{kw}} {revenue['products_listed']}")

        sections = [
            f"{icon} <b>CICLO #{self._cycle_count}  ·  COMPLETADO</b>",
            "<pre>" + "\n".join(data_rows) + "</pre>",
        ]

        shop_url = getattr(settings, "SHOPIFY_URL", None) or getattr(
            settings, "SHOPIFY_SHOP_NAME", None
        )
        if shop_url:
            safe_url = _html.escape(str(shop_url))
            sections.append(f'  🛒 <a href="https://{safe_url}">Shopify →</a>')

        await bot.notify_owner("\n".join(sections), already_html=True)

        # Enviar screenshots si hay alguno en los resultados
        if chat_id:
            for r in results:
                if r.get("product_screenshot"):
                    await bot._send_photo(
                        chat_id,
                        r["product_screenshot"],
                        caption=f"📸 Producto · {r.get('agent', 'ecommerce')}",
                    )
                market_research = r.get("market_research", {})
                if isinstance(market_research, dict) and market_research.get("screenshots"):
                    for ss_path in market_research["screenshots"]:
                        await bot._send_photo(
                            chat_id,
                            ss_path,
                            caption=f"🔍 Análisis · {r.get('agent', 'ecommerce')}",
                        )

    async def start(self) -> None:
        """Inicializacion del orquestador."""
        self._auto_discover_agents()
        logger.info("[Orchestrator] Sistema listo.")

    async def stop(self) -> None:
        """Limpieza del orquestador."""
        logger.info("[Orchestrator] Apagando...")
