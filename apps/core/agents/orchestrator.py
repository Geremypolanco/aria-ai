"""
orchestrator.py — Director central de ARIA AI. Prioridad absoluta: MONETIZACION.

Mejoras v3:
- HuggingFace como motor IA principal (via AriaAIClient)
- Fix: _generate_monetization_plan usa ai.complete_json() correctamente
- Supabase logging en cada ciclo
- Gumroad product creation automatica
- Buffer social distribution tras publicar
- settings.telegram_token para compatibilidad de nombres
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

    async def _log_cycle_start(self) -> Optional[str]:
        """Registra inicio del ciclo en Supabase."""
        try:
            from apps.core.tools.db_setup import log_to_supabase
            data = {
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "summary": {"cycle_number": self._cycle_count},
            }
            await log_to_supabase("autonomous_cycles", data)
        except Exception as exc:
            logger.debug("[Orchestrator] DB log start error: %s", exc)
        return None

    async def _log_cycle_end(
        self, cycle_id: Optional[str], results: list[dict], revenue: dict
    ) -> None:
        """Registra fin del ciclo en Supabase."""
        try:
            from apps.core.tools.db_setup import log_to_supabase
            errors = [r.get("error", "") for r in results if not r.get("success")]
            data = {
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
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
            intel["top_opportunity"] = all_titles[0] if all_titles else "mercado digital en expansion"
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
        Genera plan de accion usando IA.
        FIXED: usa ai.complete_json() de AriaAIClient (HF primario).
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
            "Eres el director estrategico de ARIA AI, un sistema de monetizacion autonoma. "
            "Tu objetivo es maximizar ingresos reales con contenido SEO y productos digitales. "
            "Responde SOLO con JSON valido sin markdown."
        )

        user_prompt = f"""CONTEXTO DEL MERCADO ({datetime.now(timezone.utc).strftime('%Y-%m-%d')}):
- Tendencia HackerNews: {hn_title or 'No disponible'}
- Tendencia Reddit: {reddit_title or 'No disponible'}
- Trending topics: {', '.join(trending[:5]) or 'IA, negocios digitales, automatizacion'}

AGENTES DISPONIBLES:
- content: genera articulos SEO con links de afiliado → Medium/Dev.to
- cfo: crea ebooks PDF y los vende en Gumroad
- affiliate: busca y promociona productos Amazon/ClickBank
- social: distribuye contenido en redes via Buffer
- evolution: mejora el codigo de ARIA (baja prioridad)

Genera el plan de monetizacion. JSON esperado:
{{
  "focus": "descripcion del foco",
  "market_opportunity": "oportunidad especifica",
  "estimated_revenue_usd": 0,
  "missions": [
    {{
      "agent": "content",
      "task": "full_pipeline",
      "priority": 1,
      "target_topic": "tema basado en tendencia real",
      "revenue_target_usd": 50
    }}
  ]
}}"""

        try:
            plan = await ai.complete_json(
                system=system_prompt,
                user=user_prompt,
                model=AIModel.STRATEGY,
                max_tokens=800,
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

        if "content" not in existing_agents:
            missions.insert(0, {
                "agent": "content",
                "task": "full_pipeline",
                "priority": 1,
                "target_topic": "inteligencia artificial para negocios 2025",
                "revenue_target_usd": 50,
                "rationale": "Contenido SEO con afiliados = ingresos pasivos 24/7",
            })

        if "cfo" not in existing_agents:
            missions.insert(1, {
                "agent": "cfo",
                "task": "create_and_sell_ebook",
                "priority": 2,
                "target_topic": "productividad con IA",
                "revenue_target_usd": 100,
                "rationale": "Ebooks en Gumroad = ingresos directos",
            })

        missions.sort(key=lambda x: x.get("priority", 99))
        plan["missions"] = missions
        return plan

    def _fallback_monetization_plan(self) -> dict:
        """Plan de emergencia cuando la IA no responde."""
        return {
            "focus": "monetizacion directa — content + productos digitales",
            "market_opportunity": "herramientas IA en expansion",
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
                    "target_topic": "guia de automatizacion con IA",
                    "revenue_target_usd": 100,
                },
                {
                    "agent": "affiliate",
                    "task": "promote_products",
                    "priority": 3,
                    "target_topic": "software de productividad IA",
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
                    all_results.append({
                        "agent": group[i].get("agent"),
                        "success": False,
                        "error": str(r),
                    })
                else:
                    all_results.append(r)

        return all_results

    async def _run_mission(self, mission: dict) -> dict:
        """Ejecuta una mision individual y aplica post-procesamiento."""
        agent_name = mission.get("agent", "")
        task = mission.get("task", "")
        topic = mission.get("target_topic", "")

        try:
            # Mision CFO: crear producto en Gumroad directamente
            if agent_name == "cfo":
                return await self._run_cfo_mission(mission)

            agent = await self._get_agent(agent_name)
            if not agent:
                return {
                    "agent": agent_name,
                    "success": False,
                    "error": f"Agente '{agent_name}' no disponible",
                }

            context = {
                "task": task,
                "target_topic": topic,
                "market_focus": topic,
                "revenue_target_usd": mission.get("revenue_target_usd", 0),
                "rationale": mission.get("rationale", ""),
            }

            result = await agent.run(context)
            result["agent"] = agent_name
            result["mission_task"] = task

            # Post-procesamiento: distribuir en redes si hay publicaciones
            if result.get("success") and result.get("published"):
                await self._distribute_content_social(result.get("published", []), topic)

            return result

        except Exception as exc:
            logger.error("[Orchestrator] Mision %s/%s fallo: %s", agent_name, task, exc)
            return {"agent": agent_name, "success": False, "error": str(exc)}

    async def _run_cfo_mission(self, mission: dict) -> dict:
        """
        Ejecuta mision CFO: genera ebook con IA y lo publica en Gumroad.
        HuggingFace genera el contenido. Gumroad lo vende.
        """
        topic = mission.get("target_topic", "productividad con IA")
        ai = get_ai_client()

        try:
            from apps.core.tools.gumroad_tools import GumroadTools
            gumroad = GumroadTools()
            listing = gumroad.build_ebook_listing(topic)

            # Generar descripcion del ebook con HuggingFace
            if ai:
                description_result = await ai.complete(
                    system=(
                        "Eres un experto en marketing de productos digitales. "
                        "Escribe descripciones de ventas atractivas y concisas."
                    ),
                    user=(
                        f"Escribe una descripcion de ventas de 150 palabras para un ebook sobre: {topic}. "
                        "Menciona 3 beneficios clave, quien es el publico objetivo, "
                        "y por que deben comprarlo ahora. Tono profesional pero accesible."
                    ),
                    model=AIModel.CREATIVE,
                    max_tokens=300,
                    agent_name="cfo",
                )
                if description_result.success:
                    listing["description"] = description_result.content

            # Crear producto en Gumroad
            result = await gumroad.create_product(
                name=listing["name"],
                description=listing["description"],
                price_cents=listing["price_cents"],
                tags=listing.get("tags", []),
            )

            if result.get("success"):
                # Log en Supabase
                try:
                    from apps.core.tools.db_setup import log_to_supabase
                    await log_to_supabase("products", {
                        "name": listing["name"],
                        "platform": "gumroad",
                        "product_id": result.get("product_id", ""),
                        "price": listing["price_cents"] / 100,
                        "url": result.get("url", ""),
                        "status": "active",
                    })
                except Exception:
                    pass

                # Postear en redes sociales
                try:
                    from apps.core.tools.social_tools import SocialTools
                    social = SocialTools()
                    post_text = social.format_product_post(
                        name=listing["name"],
                        url=result.get("url", ""),
                        price_usd=listing["price_cents"] / 100,
                    )
                    await social.post_content(post_text, url=result.get("url", ""))
                except Exception:
                    pass

                logger.info(
                    "[CFO] Producto creado en Gumroad: '%s' — $%.2f — %s",
                    listing["name"], listing["price_cents"] / 100, result.get("url", ""),
                )
                return {
                    "agent": "cfo",
                    "success": True,
                    "product_name": listing["name"],
                    "url": result.get("url", ""),
                    "price_usd": listing["price_cents"] / 100,
                    "revenue_usd": 0,  # Se actualiza cuando hay ventas
                    "gumroad": result,
                    "mission_task": "create_and_sell_ebook",
                }
            else:
                return {
                    "agent": "cfo",
                    "success": False,
                    "error": result.get("error", "Gumroad fallo"),
                    "mission_task": "create_and_sell_ebook",
                }

        except Exception as exc:
            logger.error("[CFO] Error en mision CFO: %s", exc)
            return {"agent": "cfo", "success": False, "error": str(exc)}

    async def _distribute_content_social(
        self, published_items: list[dict], topic: str
    ) -> None:
        """Distribuye contenido publicado en redes sociales via Buffer."""
        try:
            from apps.core.tools.social_tools import SocialTools
            social = SocialTools()
            for item in published_items[:2]:  # Max 2 posts por ciclo
                title = item.get("title", "")
                url = item.get("url", "")
                if title and url:
                    post_text = social.format_article_post(title, url, topic)
                    await social.post_content(post_text, url=url)
                    logger.info("[Social] Distribuido en Buffer: %s", title[:50])
        except Exception as exc:
            logger.debug("[Social] Error distribuyendo: %s", exc)

    async def _get_agent(self, name: str) -> Optional[BaseAgent]:
        """
        Carga agentes dinamicamente — escanea apps.core.agents en el primer uso.
        Cualquier modulo *_agent.py con una subclase de BaseAgent se registra
        automaticamente por su atributo .name — sin mapeo manual requerido.
        Nuevo agente en el directorio = disponible inmediatamente al proximo ciclo.
        """
        if not self._agents:
            self._auto_discover_agents()

        if name in self._agents:
            return self._agents[name]

        # Aliases para nombres usados en planes generados por IA
        aliases = {
            "affiliate": "cfo",
            "social": "marketing",
            "content_agent": "content",
            "cfo_agent": "cfo",
            "seo": "content",
            "analytics": "pm",
            "market": "pm",
            "monetization": "cfo",
            "copy": "content",
            "research": "pm",
            "sales": "marketing",
            "support_tickets": "support",
            "bug_fix": "dev",
            "code": "dev",
            "compliance_check": "compliance",
            "legal": "compliance",
        }
        resolved = aliases.get(name)
        if resolved and resolved in self._agents:
            logger.info("[Orchestrator] Alias '%s' resuelto a '%s'", name, resolved)
            return self._agents[resolved]

        logger.warning(
            "[Orchestrator] Agente '%s' no encontrado. Disponibles: %s",
            name, sorted(self._agents.keys()),
        )
        return None

    def _auto_discover_agents(self) -> None:
        """
        Escanea automaticamente apps.core.agents y registra todas las
        subclases de BaseAgent encontradas en modulos *_agent.py.
        No requiere mapeo manual — el registro es por agent.name.
        Cualquier agente nuevo agregado al directorio se registra al siguiente ciclo.
        """
        import importlib
        import pkgutil
        import inspect
        try:
            import apps.core.agents as agents_pkg
        except ImportError:
            logger.error("[Orchestrator] No se pudo importar apps.core.agents")
            return

        registered: list[str] = []
        skip = {"base_agent", "orchestrator"}
        for _importer, module_name, _is_pkg in pkgutil.iter_modules(agents_pkg.__path__):
            if module_name in skip or not module_name.endswith("_agent"):
                continue
            try:
                mod = importlib.import_module(f"apps.core.agents.{module_name}")
                for attr_name in dir(mod):
                    cls = getattr(mod, attr_name, None)
                    if (
                        cls and inspect.isclass(cls)
                        and issubclass(cls, BaseAgent)
                        and cls is not BaseAgent
                        and not getattr(cls, "__abstractmethods__", None)
                    ):
                        try:
                            agent = cls()
                            self._agents[agent.name] = agent
                            registered.append(agent.name)
                            break
                        except Exception as init_err:
                            logger.warning(
                                "[Orchestrator] No se pudo instanciar %s: %s",
                                attr_name, init_err,
                            )
            except Exception as exc:
                logger.warning("[Orchestrator] Error importando %s: %s", module_name, exc)

        logger.info("[Orchestrator] Agentes auto-descubiertos: %s", registered)

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
                if r.get("gumroad") or r.get("stripe") or r.get("product_name"):
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
        """Envia reporte del ciclo por Telegram."""
        tg_token = settings.telegram_token
        if not tg_token or not settings.TELEGRAM_CHAT_ID:
            logger.debug("[Orchestrator] Telegram no configurado — saltando reporte")
            return

        ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
        successful = revenue_summary["missions_successful"]
        failed = revenue_summary["missions_failed"]
        revenue = revenue_summary["total_revenue_usd"]
        published = revenue_summary["items_published"]
        products = revenue_summary["products_listed"]
        opportunity = intelligence.get("top_opportunity", "")[:80]

        status_icon = "✅" if failed == 0 else ("⚠️" if successful > 0 else "❌")

        lines = [
            f"<b>{status_icon} Ciclo #{self._cycle_count}</b> — {ts}",
            "",
            f"<b>Ingresos:</b> ${revenue:.2f}",
            f"<b>Publicaciones:</b> {published} | <b>Productos:</b> {products}",
            f"<b>Misiones:</b> {successful} OK  {failed} errores — {cycle_time:.0f}s",
        ]

        if opportunity:
            lines += ["", f"<b>Oportunidad:</b> {opportunity}"]

        # Listar publicaciones exitosas
        published_items = []
        for r in results:
            if r.get("success") and r.get("published"):
                for item in r.get("published", [])[:2]:
                    url = item.get("url", "")
                    title = item.get("title", "")
                    if url and title:
                        published_items.append(f'  • <a href="{url}">{title[:50]}</a>')
        if published_items:
            lines += ["", "<b>Publicado:</b>"] + published_items[:3]

        # Productos creados
        for r in results:
            if r.get("success") and r.get("product_name"):
                url = r.get("url", "")
                name = r.get("product_name", "")
                price = r.get("price_usd", 0)
                if name:
                    line = f'  • <a href="{url}">{name[:40]}</a> — ${price:.2f}'
                    if "<b>Productos creados:</b>" not in "\n".join(lines):
                        lines += ["", "<b>Productos creados:</b>"]
                    lines.append(line)

        errors = [r for r in results if not r.get("success")]
        if errors:
            lines += ["", "<b>Errores:</b>"]
            for e in errors[:3]:
                agent_name = e.get('agent', '?')
                error_msg = str(e.get('error', ''))
                if "no disponible" in error_msg.lower() or "no encontrado" in error_msg.lower():
                    error_msg = f"Agente '{agent_name}' no cargado."
                lines.append(f"  • {agent_name}: {error_msg[:70]}")

        text = "\n".join(lines)
        await self._telegram_send(text, tg_token)

    async def _telegram_send(self, text: str, token: Optional[str] = None) -> None:
        """Envia mensaje por Telegram."""
        tg_token = token or settings.telegram_token
        if not tg_token:
            return
        url = f"{TELEGRAM_API}{tg_token}/sendMessage"
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

    async def get_status(self) -> dict[str, Any]:
        """Estado del orchestrator."""
        return {
            "cycle_count": self._cycle_count,
            "agents_loaded": list(self._agents.keys()),
        }
