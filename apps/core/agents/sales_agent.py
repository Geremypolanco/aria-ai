"""
sales_agent.py — Agente de Ventas Autónomo de ARIA AI.

El agente que combina toda la inteligencia de ventas para generar ingresos reales.
Opera el ciclo completo:
  1. Detectar oportunidad (trending topics + nichos)
  2. Crear producto digital listo para vender
  3. Generar copy persuasivo con frameworks probados
  4. Publicar en Gumroad, Shopify u otras plataformas
  5. Distribuir en todos los canales activos
  6. Configurar follow-up automatizado
  7. Registrar en Supabase y distribuir revenue en economía circular
  8. Reportar al propietario por Telegram con métricas reales

Meta operativa: primer ingreso en 72 horas.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.sales_agent")


class SalesAgent(BaseAgent):
    """
    Agente de ventas autónomo — el motor de ingresos de ARIA AI.
    Combina sales intelligence + copywriting + distribución + follow-up.
    """

    def __init__(self, sector_id: str = "digital") -> None:
        super().__init__(
            name="sales_agent",
            description=(
                "Genera ingresos reales: detecta oportunidades, crea productos digitales, "
                "escribe copy persuasivo, publica y distribuye automáticamente."
            ),
            capabilities=[
                "product_creation", "copywriting", "gumroad", "social_media",
                "email_marketing", "follow_up", "market_analysis", "supabase", "telegram",
            ],
            sector_id=sector_id,
        )
        self._sales_intel = None
        self._copy_engine = None
        self._revenue_engine = None
        self._followup_engine = None
        self._audience_profiler = None

    def _get_sales_intel(self):
        if not self._sales_intel:
            from apps.core.tools.sales_intelligence import SalesIntelligence
            self._sales_intel = SalesIntelligence()
        return self._sales_intel

    def _get_copy_engine(self):
        if not self._copy_engine:
            from apps.core.tools.copywriting_engine import CopywritingEngine
            self._copy_engine = CopywritingEngine()
        return self._copy_engine

    def _get_revenue_engine(self):
        if not self._revenue_engine:
            from apps.core.tools.revenue_engine import get_revenue_engine
            self._revenue_engine = get_revenue_engine()
        return self._revenue_engine

    def _get_followup_engine(self):
        if not self._followup_engine:
            from apps.core.tools.followup_engine import FollowUpEngine
            self._followup_engine = FollowUpEngine()
        return self._followup_engine

    def _get_audience_profiler(self):
        if not self._audience_profiler:
            from apps.core.tools.audience_profiler import AudienceProfiler
            self._audience_profiler = AudienceProfiler()
        return self._audience_profiler

    # ── DISPATCH ─────────────────────────────────────────────────

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mode = context.get("mode", "revenue_cycle")

        if mode == "revenue_cycle":
            return await self.run_revenue_cycle()
        elif mode == "create_product":
            return await self.create_and_launch_product(
                niche=context.get("niche", "emprendedores digitales"),
                topic=context.get("topic", "productividad"),
            )
        elif mode == "write_copy":
            return await self.generate_sales_copy(
                product=context.get("product", ""),
                audience=context.get("audience", ""),
                pain=context.get("pain", ""),
                benefit=context.get("benefit", ""),
            )
        elif mode == "market_scan":
            return await self.scan_opportunities()
        elif mode == "followup_sequence":
            return await self.setup_followup(
                lead_name=context.get("lead_name", ""),
                lead_email=context.get("lead_email", ""),
                product=context.get("product", ""),
                pain=context.get("pain", ""),
            )
        elif mode == "report":
            return await self.generate_sales_report()
        else:
            return await self.run_revenue_cycle()

    # ── CICLO PRINCIPAL ───────────────────────────────────────────

    async def run_revenue_cycle(self) -> dict[str, Any]:
        """
        Ciclo completo de generación de ingresos:
        scan → create → copy → publish → distribute → report
        """
        logger.info("[SalesAgent] Iniciando ciclo de ingresos")
        results: dict[str, Any] = {"agent": self.name, "mode": "revenue_cycle"}

        # 1. Escanear oportunidades
        opportunities = await self.scan_opportunities()
        results["opportunities"] = opportunities

        # 2. Lanzar el mejor producto disponible
        revenue_engine = self._get_revenue_engine()
        launch_result = await revenue_engine.run_revenue_cycle()
        results["launch"] = launch_result

        # 3. Distribuir en redes sociales con copy generado
        if launch_result.get("success") and launch_result.get("gumroad", {}).get("url"):
            gumroad_url = launch_result["gumroad"]["url"]
            product = launch_result.get("selected_product", {})
            social_result = await self._distribute_to_social(product, gumroad_url)
            results["social_distribution"] = social_result

        # 4. Registrar y reportar
        await self._report_to_owner(results)

        results["success"] = launch_result.get("success", False)
        logger.info("[SalesAgent] Ciclo completado — éxito: %s", results["success"])
        return results

    # ── CREACIÓN DE PRODUCTO ──────────────────────────────────────

    async def create_and_launch_product(self, niche: str, topic: str) -> dict[str, Any]:
        """Crea un nuevo producto digital desde cero y lo lanza."""
        logger.info("[SalesAgent] Creando producto: %s para %s", topic, niche)

        revenue_engine = self._get_revenue_engine()
        sales_intel = self._get_sales_intel()
        copy_engine = self._get_copy_engine()

        # Generar idea de producto con IA
        product_idea = await revenue_engine.create_product_from_trend(topic, niche)
        if not product_idea.get("success"):
            # Fallback: usar producto predefinido
            predefined = sales_intel.generate_product_idea(niche, topic)
            product_data = {
                "id": f"custom_{topic[:20]}",
                "title": predefined["title_options"][0],
                "price_usd": 27,
                "target_audience": niche,
                "pain": f"no saber cómo {topic}",
                "benefit": predefined["hook"],
                "contents": [f"Guía completa de {topic}", "Plantillas incluidas", "Ejemplos reales"],
                "distribution_channels": ["twitter", "linkedin"],
            }
        else:
            product_data = product_idea["product"]

        # Generar copy completo
        copy = copy_engine.write_gumroad_product(
            name=product_data.get("title", f"Guía: {topic}"),
            audience=niche,
            pain=product_data.get("pain", f"dificultades con {topic}"),
            what_is=f"Sistema completo de {topic} para {niche}",
            benefits=[
                product_data.get("benefit", f"dominar {topic}"),
                "Resultados en 7-14 días",
                "Garantía de 30 días",
            ],
            price=f"${product_data.get('price_usd', 27)}",
            contents=product_data.get("contents", [f"Guía de {topic}"]),
        )

        return {
            "success": True,
            "product": product_data,
            "copy": copy,
            "next_steps": [
                "1. Crear el contenido del producto (usa los temas de 'contents')",
                "2. Subir a Gumroad con la descripción generada",
                "3. Publicar en los canales de distribución",
                "4. Configurar email de bienvenida post-compra",
            ],
        }

    # ── GENERACIÓN DE COPY ────────────────────────────────────────

    async def generate_sales_copy(
        self,
        product: str,
        audience: str,
        pain: str,
        benefit: str,
        copy_type: str = "full_set",
    ) -> dict[str, Any]:
        """Genera copy de ventas completo para cualquier producto."""
        copy_engine = self._get_copy_engine()
        sales_intel = self._get_sales_intel()

        result = {
            "product": product,
            "audience": audience,
        }

        # AIDA completo
        result["aida_copy"] = sales_intel.write_full_ad(product, audience, pain, benefit)

        # PAS email
        result["pas_email"] = sales_intel.write_email_copy(
            problem=pain,
            solution=f"{product} — {benefit}",
            cta=f"Obtén {product} ahora →",
        )

        # Headlines
        result["headlines"] = sales_intel.get_headlines(audience, benefit, n=5)

        # Email subjects
        result["email_subjects"] = sales_intel.get_email_subjects(nicho=audience, n=5)

        # Hooks para video/social
        result["hooks"] = {
            "tiktok": copy_engine.get_hooks("tiktok_reel", n=3),
            "email": copy_engine.get_hooks("email_subject", n=3),
            "landing": copy_engine.get_hooks("landing_headline", n=3),
        }

        # Anuncios pagados
        result["ads"] = copy_engine.generate_ad_set(product, audience, pain, benefit, "$27")

        # Objeciones comunes y respuestas
        result["objections"] = {
            "precio": sales_intel.handle_objection("precio", product=product, problem=pain)["response"],
            "tiempo": sales_intel.handle_objection("tiempo", product=product)["response"],
            "confianza": sales_intel.handle_objection("confianza", product=product)["response"],
        }

        # Mejores nichos para este producto
        keywords = [pain, benefit, audience]
        result["best_niches"] = sales_intel.best_niches_for(keywords)

        # Power words recomendadas
        result["power_words"] = {
            "urgency": sales_intel.get_power_words("urgency")[:5],
            "trust": sales_intel.get_power_words("trust")[:5],
            "transformation": sales_intel.get_power_words("transformation")[:5],
        }

        return result

    # ── ESCANEO DE OPORTUNIDADES ──────────────────────────────────

    async def scan_opportunities(self) -> dict[str, Any]:
        """Escanea el mercado para detectar las mejores oportunidades de venta."""
        opportunities = []

        # Nichos con alta demanda ahora mismo
        sales_intel = self._get_sales_intel()
        niches = sales_intel.best_niches_for(["ingresos", "marketing", "clientes", "automatización"])

        for niche in niches[:3]:
            opportunities.append({
                "niche": niche.get("niche"),
                "pain": niche.get("pain"),
                "best_offer": niche.get("best_offer"),
                "price_range": niche.get("price_range"),
                "platform": niche.get("platform"),
                "urgency": "alta" if "agudo" in niche.get("decision_speed", "") else "media",
            })

        # Productos listos para lanzar ahora
        revenue_engine = self._get_revenue_engine()
        ready_products = revenue_engine.get_ready_products()
        best_product = ready_products[0] if ready_products else {}

        return {
            "top_opportunities": opportunities,
            "recommended_product": best_product.get("title", ""),
            "recommended_price": f"${best_product.get('price_usd', 27)}",
            "creation_time": best_product.get("creation_time_hours", 8),
            "action": "Lanzar este producto en las próximas 24 horas",
            "estimated_revenue_week_1": f"${best_product.get('price_usd', 27) * 5} - ${best_product.get('price_usd', 27) * 20}",
        }

    # ── FOLLOW-UP ─────────────────────────────────────────────────

    async def setup_followup(
        self,
        lead_name: str,
        lead_email: str,
        product: str,
        pain: str,
    ) -> dict[str, Any]:
        """Configura un plan de follow-up para un lead."""
        followup_engine = self._get_followup_engine()
        plan = followup_engine.create_followup_plan(
            lead_name=lead_name,
            lead_email=lead_email,
            sequence_type="warm_lead",
            product=product,
            pain=pain,
        )

        # Guardar en Supabase
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            await db.create_task(
                agent_id=self.name,
                task_type="followup_sequence",
                input_data={
                    "lead_name": lead_name,
                    "lead_email": lead_email,
                    "product": product,
                    "plan": plan,
                },
            )
        except Exception as exc:
            logger.warning("[SalesAgent] No se pudo guardar follow-up en Supabase: %s", exc)

        return {
            "success": True,
            "lead": lead_name,
            "plan": plan,
            "first_email": plan.get("plan", [{}])[0] if plan.get("plan") else {},
        }

    # ── REPORTE ──────────────────────────────────────────────────

    async def generate_sales_report(self) -> dict[str, Any]:
        """Genera reporte de ventas con datos reales de Supabase."""
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()

            total_revenue = await db.get_total_revenue(days=30)
            by_platform = await db.get_revenue_by_platform()
            recent_logs = await db.get_recent_logs(limit=5, level="PRODUCT_LAUNCHED")
            opportunities = await db.get_best_opportunities(limit=3)

            revenue_engine = self._get_revenue_engine()
            products = revenue_engine.get_ready_products()

            return {
                "period": "últimos 30 días",
                "total_revenue_usd": total_revenue,
                "by_platform": by_platform,
                "products_launched": len(recent_logs),
                "top_opportunities": len(opportunities),
                "ready_to_launch_products": len(products),
                "next_recommended_action": (
                    "Lanzar el siguiente producto del catálogo" if total_revenue < 100
                    else "Crear un upsell para los compradores existentes"
                ),
            }
        except Exception as exc:
            logger.error("[SalesAgent] Error generando reporte: %s", exc)
            return {"error": str(exc)}

    # ── DISTRIBUCIÓN SOCIAL ──────────────────────────────────────

    async def _distribute_to_social(self, product: dict, url: str) -> dict:
        """Distribuye un producto en redes sociales."""
        results = {}
        copy_engine = self._get_copy_engine()

        tweet = (
            f"Nuevo recurso: '{product.get('title', 'Producto nuevo')}'\n\n"
            f"Para {product.get('target_audience', 'emprendedores')} "
            f"que quieren {product.get('benefit', 'resultados reales')}.\n\n"
            f"${product.get('price_usd', 27)} — acceso inmediato: {url}"
        )

        try:
            twitter_key = getattr(settings, "TWITTER_API_KEY", None)
            if twitter_key:
                from apps.core.tools.social_media import SocialMediaManager
                sm = SocialMediaManager()
                results["twitter"] = await sm.post_content("twitter", tweet)
            else:
                results["twitter"] = {"skipped": "TWITTER_API_KEY no configurado"}
        except Exception as exc:
            results["twitter"] = {"error": str(exc)}

        return results

    async def _report_to_owner(self, results: dict) -> None:
        """Envía reporte al propietario por Telegram."""
        try:
            launch = results.get("launch", {})
            product = launch.get("selected_product", {})
            gumroad = launch.get("gumroad", {})
            success = gumroad.get("success", False)

            if success:
                msg = (
                    f"<b>SalesAgent — Producto Lanzado</b>\n\n"
                    f"<b>{product.get('title', 'Producto')}</b>\n"
                    f"Precio: ${product.get('price_usd', 0)}\n"
                    f"URL: {gumroad.get('url', 'N/A')}\n\n"
                    f"Ahora distribuido en:\n"
                    + "\n".join(
                        f"  • {k}: {'OK' if isinstance(v, dict) and not v.get('error') else 'Error'}"
                        for k, v in results.get("social_distribution", {}).items()
                    )
                    + f"\n\n<i>El motor de ingresos está operativo.</i>"
                )
            else:
                error = gumroad.get("error", "Error desconocido")
                msg = (
                    f"<b>SalesAgent — Ciclo completado</b>\n\n"
                    f"Gumroad: {error}\n"
                    f"(Verifica que GUMROAD_TOKEN esté configurado en Fly.io)"
                )

            async with __import__("httpx").AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"https://api.telegram.org/bot{settings.TELEGRAM_TOKEN}/sendMessage",
                    json={
                        "chat_id": settings.TELEGRAM_CHAT_ID,
                        "text": msg,
                        "parse_mode": "HTML",
                    },
                )
        except Exception as exc:
            logger.warning("[SalesAgent] Error enviando reporte Telegram: %s", exc)
