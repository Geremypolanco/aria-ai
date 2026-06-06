"""
revenue_engine.py — Motor Central de Ingresos para ARIA AI.

Orquesta todo el sistema de generación de ingresos:
  1. Detecta oportunidades de mercado (tendencias + nichos)
  2. Crea productos digitales listos para vender (Gumroad)
  3. Genera copy completo (landing, emails, ads, social)
  4. Publica y distribuye en todos los canales
  5. Configura follow-up automatizado
  6. Registra revenue en Supabase y distribuye en economía circular

Meta: Generar el primer dólar en 72 horas y escalar de ahí.

Estrategia de lanzamiento rápido (basada en Lean Launch de Eric Ries +
Rob Walling's "Start Small Stay Small"):
  - MVP digital en 24h (template pack, checklist, mini-guía)
  - Publicar en Gumroad con precio bajo ($9-$27)
  - Distribuir en 5 canales gratuitos simultáneamente
  - Colectar feedback y mejorar
  - Escalar lo que funciona
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from apps.core.config import settings
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.revenue")


# ─────────────────────────────────────────────────────────────────
# PRODUCTOS LISTOS PARA LANZAR INMEDIATAMENTE
# No necesitan validación — tienen demanda comprobada
# ─────────────────────────────────────────────────────────────────

READY_TO_LAUNCH_PRODUCTS = [
    {
        "id": "prompts_pack_001",
        "title": "500 Prompts de ChatGPT para Negocios Hispanos",
        "type": "template_pack",
        "price_usd": 17,
        "target_audience": "emprendedores y profesionales latinoamericanos",
        "pain": "no saben cómo aprovechar la IA en su negocio",
        "benefit": "automatizar y escalar con IA sin ser técnico",
        "contents": [
            "100 prompts para marketing y ventas",
            "100 prompts para atención al cliente",
            "100 prompts para creación de contenido",
            "100 prompts para operaciones y productividad",
            "100 prompts para finanzas y reportes",
            "Guía de uso (PDF) + ejemplos reales",
        ],
        "creation_time_hours": 8,
        "gumroad_category": "productivity",
        "keywords": ["ChatGPT", "IA", "prompts", "negocios", "productividad"],
        "distribution_channels": ["twitter", "linkedin", "reddit_latinoamerica", "facebook_groups"],
    },
    {
        "id": "freelance_kit_001",
        "title": "Kit Completo del Freelancer: Contratos, Propuestas y Precios",
        "type": "template_pack",
        "price_usd": 27,
        "target_audience": "freelancers y consultores",
        "pain": "clientes que no pagan, propuestas que no cierran, precios mal puestos",
        "benefit": "cerrar más clientes, protegerse legalmente y cobrar lo que valen",
        "contents": [
            "5 contratos de servicio en español (Word + PDF editable)",
            "3 plantillas de propuesta que cierran el 70% de los casos",
            "Calculadora de precios (Excel): descubre cuánto cobrar",
            "Guía: cómo subir tus precios sin perder clientes",
            "Scripts de cobro para clientes morosos",
            "Checklist de onboarding de clientes nuevos",
        ],
        "creation_time_hours": 12,
        "gumroad_category": "business",
        "keywords": ["freelancer", "contratos", "propuestas", "cobrar", "clientes"],
        "distribution_channels": ["linkedin", "twitter", "reddit_freelance", "facebook_groups"],
    },
    {
        "id": "social_media_kit_001",
        "title": "30 Días de Contenido para Instagram y LinkedIn (Listo para Publicar)",
        "type": "content_calendar",
        "price_usd": 19,
        "target_audience": "emprendedores y coaches sin tiempo para crear contenido",
        "pain": "no saber qué publicar, inconsistencia en redes, cero engagement",
        "benefit": "publicar contenido de calidad todos los días sin estrés",
        "contents": [
            "30 posts de Instagram con copy listo (texto + idea visual)",
            "30 posts de LinkedIn con estructura comprobada",
            "10 ideas de Reels/Stories con scripts",
            "Calendario editorial en Notion (plantilla)",
            "Guía de hashtags por nicho",
            "Bonus: 5 hooks virales que funcionan siempre",
        ],
        "creation_time_hours": 10,
        "gumroad_category": "marketing",
        "keywords": ["contenido", "instagram", "linkedin", "redes sociales", "marketing"],
        "distribution_channels": ["instagram", "twitter", "linkedin", "pinterest"],
    },
    {
        "id": "email_marketing_kit_001",
        "title": "Sistema de Email Marketing para Pequeños Negocios (Sin Experiencia Previa)",
        "type": "system_guide",
        "price_usd": 37,
        "target_audience": "dueños de pequeños negocios y tiendas online",
        "pain": "no saber cómo capturar emails ni qué enviar a su lista",
        "benefit": "crear una lista de emails que genera ventas en piloto automático",
        "contents": [
            "Guía paso a paso: de 0 a tu primera lista de 1000 suscriptores",
            "5 secuencias de email listas para copiar y pegar",
            "20 subjects que generan +40% de open rate",
            "Plantilla de landing page (HTML editable)",
            "Checklist: configuración de Mailchimp/ConvertKit en 1 hora",
            "Guía de segmentación para enviar el email correcto al segmento correcto",
        ],
        "creation_time_hours": 16,
        "gumroad_category": "marketing",
        "keywords": ["email marketing", "newsletter", "lista de emails", "mailchimp", "automatización"],
        "distribution_channels": ["linkedin", "twitter", "reddit_marketing", "facebook_groups"],
    },
    {
        "id": "seo_checklist_001",
        "title": "Checklist SEO 2025: 127 Puntos para Rankear en Google Sin Agencia",
        "type": "checklist_system",
        "price_usd": 17,
        "target_audience": "dueños de negocios y creadores de contenido",
        "pain": "no aparecer en Google, depender de agencias caras, tráfico orgánico cero",
        "benefit": "rankear en la primera página de Google con recursos limitados",
        "contents": [
            "127 puntos de verificación organizados por prioridad",
            "Guía de uso: por dónde empezar según tu situación",
            "Hoja de cálculo para rastrear progreso",
            "Glosario de términos SEO en español",
            "Bonus: 50 herramientas SEO gratuitas y cómo usarlas",
        ],
        "creation_time_hours": 6,
        "gumroad_category": "seo",
        "keywords": ["SEO", "Google", "posicionamiento", "tráfico orgánico", "checklist"],
        "distribution_channels": ["twitter", "linkedin", "reddit_seo", "facebook_groups"],
    },
]


# ─────────────────────────────────────────────────────────────────
# MOTOR PRINCIPAL
# ─────────────────────────────────────────────────────────────────

class RevenueEngine:
    """
    Motor central de generación de ingresos de ARIA AI.
    Coordina: detección de oportunidades → creación → distribución → seguimiento.
    """

    def __init__(self):
        self.ai = get_ai_client()

    async def run_revenue_cycle(self) -> dict[str, Any]:
        """
        Ciclo completo de generación de ingresos.
        Ejecuta el proceso de creación y publicación de producto.
        """
        logger.info("[RevenueEngine] Iniciando ciclo de ingresos")
        results: dict[str, Any] = {"cycle": "revenue", "agent": "revenue_engine"}

        # 1. Seleccionar el mejor producto para lanzar ahora
        product = await self._select_best_product()
        results["selected_product"] = product

        # 2. Generar copy completo con IA
        copy = await self._generate_full_copy(product)
        results["copy_generated"] = bool(copy)

        # 3. Crear en Gumroad
        gumroad_result = await self._create_gumroad_product(product, copy)
        results["gumroad"] = gumroad_result

        # 4. Distribuir en canales
        distribution = await self._distribute(product, copy, gumroad_result)
        results["distribution"] = distribution

        # 5. Registrar en Supabase
        await self._record_launch(product, gumroad_result, results)

        results["success"] = gumroad_result.get("success", False)
        return results

    async def _select_best_product(self) -> dict:
        """Selecciona el producto con mejor oportunidad ahora mismo."""
        try:
            from apps.core.tools.market_tools import MarketTools
            market = MarketTools()
            trends = await market.get_trending_topics() if hasattr(market, 'get_trending_topics') else []
        except Exception:
            trends = []

        # Priorizar por tendencias si hay datos, o rotar entre los ready_to_launch
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            launched = await db.get_recent_logs(limit=10, level="PRODUCT_LAUNCHED")
            launched_ids = [l.get("metadata", {}).get("product_id") for l in launched]
        except Exception:
            launched_ids = []

        # Elegir el primero que no haya sido lanzado recientemente
        for product in READY_TO_LAUNCH_PRODUCTS:
            if product["id"] not in launched_ids:
                logger.info("[RevenueEngine] Producto seleccionado: %s", product["title"])
                return product

        # Si todos fueron lanzados, elegir el de mejor precio
        return sorted(READY_TO_LAUNCH_PRODUCTS, key=lambda x: x["price_usd"], reverse=True)[0]

    async def _generate_full_copy(self, product: dict) -> dict:
        """Genera copy completo para el producto usando IA."""
        try:
            from apps.core.tools.copywriting_engine import CopywritingEngine
            engine = CopywritingEngine()

            # Generar descripción de Gumroad
            gumroad_listing = engine.write_gumroad_product(
                name=product["title"],
                audience=product["target_audience"],
                pain=product["pain"],
                what_is=f"Un pack digital completo que incluye: " + ", ".join(product["contents"][:3]),
                benefits=[
                    f"Resolver {product['pain']} definitivamente",
                    product["benefit"],
                    "Acceso inmediato, descarga instantánea",
                    "Garantía de 30 días",
                ],
                price=f"${product['price_usd']}",
                contents=product["contents"],
            )

            # Generar emails con IA si está disponible
            enhanced_description = gumroad_listing.get("gumroad_description", "")
            if self.ai:
                try:
                    ai_response = await self.ai.complete(
                        system=(
                            "Eres un copywriter experto. Mejora esta descripción de producto "
                            "para que sea más persuasiva, usando técnicas AIDA y PAS. "
                            "Mantén el español natural y conversacional. "
                            "Añade urgencia y social proof. Máximo 400 palabras."
                        ),
                        user=f"Mejora esta descripción:\n\n{enhanced_description}",
                        model=AIModel.CREATIVE,
                        max_tokens=600,
                    )
                    if ai_response.success and ai_response.content:
                        enhanced_description = ai_response.content
                except Exception as e:
                    logger.warning("[RevenueEngine] AI copy enhancement failed: %s", e)

            # Generar email de lanzamiento
            from apps.core.tools.copywriting_engine import HOOKS_BY_FORMAT
            import random
            email_subject = random.choice(HOOKS_BY_FORMAT.get("email_subject", ["Nuevo producto disponible"]))
            email_subject = email_subject.replace("{nombre}", "").replace("{nicho}", product["target_audience"])

            # Generar social posts
            social_posts = {
                "twitter": (
                    f"Acabo de publicar: '{product['title']}'\n\n"
                    f"Para {product['target_audience']} que quieren {product['benefit']}.\n\n"
                    f"${product['price_usd']} — acceso inmediato.\n\n"
                    f"Link: [gumroad_url]"
                ),
                "linkedin": (
                    f"Nuevo recurso disponible:\n\n"
                    f"'{product['title']}'\n\n"
                    f"Si eres {product['target_audience']} y {product['pain']} es tu obstáculo, "
                    f"esto es para ti.\n\n"
                    f"Incluye: " + ", ".join(product["contents"][:3]) + ".\n\n"
                    f"Precio: ${product['price_usd']} — enlace en comentarios."
                ),
            }

            return {
                "gumroad_description": enhanced_description,
                "email_subject": email_subject,
                "social_posts": social_posts,
                "short_pitch": gumroad_listing.get("short_pitch", product["title"]),
            }

        except Exception as exc:
            logger.error("[RevenueEngine] Error generando copy: %s", exc)
            return {"error": str(exc)}

    async def _create_gumroad_product(self, product: dict, copy: dict) -> dict:
        """Crea el producto en Gumroad via API."""
        gumroad_token = getattr(settings, "GUMROAD_TOKEN", None)
        if not gumroad_token:
            return {"success": False, "error": "GUMROAD_TOKEN no configurado"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Primero crear el producto
                resp = await client.post(
                    "https://api.gumroad.com/v2/products",
                    data={
                        "access_token": gumroad_token,
                        "name": product["title"],
                        "description": copy.get("gumroad_description", product["title"]),
                        "price": product["price_usd"] * 100,  # Gumroad usa centavos
                        "url": f"https://aria-products.gumroad.com/{product['id']}",
                        "published": "true",
                    },
                )

            if resp.status_code not in (200, 201):
                return {
                    "success": False,
                    "error": f"Gumroad HTTP {resp.status_code}: {resp.text[:200]}",
                }

            data = resp.json()
            if not data.get("success"):
                return {"success": False, "error": data.get("message", "Unknown Gumroad error")}

            product_data = data.get("product", {})
            url = product_data.get("short_url") or product_data.get("url", "")

            logger.info("[RevenueEngine] Producto creado en Gumroad: %s — %s", product["title"], url)
            return {
                "success": True,
                "gumroad_id": product_data.get("id", ""),
                "url": url,
                "price_usd": product["price_usd"],
                "title": product["title"],
            }

        except Exception as exc:
            logger.error("[RevenueEngine] Gumroad error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def _distribute(self, product: dict, copy: dict, gumroad: dict) -> dict:
        """Distribuye el producto en todos los canales disponibles."""
        url = gumroad.get("url", "[url pendiente]")
        results = {}

        # Telegram al propietario
        try:
            telegram_msg = (
                f"<b>Nuevo producto lanzado</b>\n\n"
                f"<b>{product['title']}</b>\n"
                f"Precio: ${product['price_usd']}\n"
                f"Audiencia: {product['target_audience']}\n\n"
                f"URL: {url}\n\n"
                f"<i>El motor de ingresos está funcionando.</i>"
            )
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"https://api.telegram.org/bot{settings.TELEGRAM_TOKEN}/sendMessage",
                    json={
                        "chat_id": settings.TELEGRAM_CHAT_ID,
                        "text": telegram_msg,
                        "parse_mode": "HTML",
                    },
                )
            results["telegram"] = {"sent": res.status_code == 200}
        except Exception as exc:
            results["telegram"] = {"error": str(exc)}

        # Twitter/X si está configurado
        try:
            twitter_key = getattr(settings, "TWITTER_API_KEY", None)
            if twitter_key:
                tweet = copy.get("social_posts", {}).get("twitter", "").replace("[gumroad_url]", url)
                if tweet:
                    from apps.core.tools.social_media import SocialMediaManager
                    sm = SocialMediaManager()
                    tweet_result = await sm.post_content("twitter", tweet)
                    results["twitter"] = tweet_result
        except Exception as exc:
            results["twitter"] = {"error": str(exc)}

        # Buffer para programación si está disponible
        try:
            buffer_token = getattr(settings, "BUFFER_TOKEN", None)
            if buffer_token:
                from apps.core.tools.buffer_tools import BufferTools
                buffer = BufferTools()
                linkedin_post = copy.get("social_posts", {}).get("linkedin", "").replace("[gumroad_url]", url)
                if linkedin_post:
                    buffer_result = await buffer.schedule_post(linkedin_post, networks=["linkedin"])
                    results["buffer_linkedin"] = buffer_result
        except Exception as exc:
            results["buffer"] = {"error": str(exc)}

        return results

    async def _record_launch(self, product: dict, gumroad: dict, results: dict) -> None:
        """Registra el lanzamiento en Supabase."""
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            await db.log(
                level="PRODUCT_LAUNCHED",
                message=f"Producto lanzado: {product['title']} — ${product['price_usd']}",
                agent="revenue_engine",
                metadata={
                    "product_id": product["id"],
                    "title": product["title"],
                    "price_usd": product["price_usd"],
                    "gumroad_url": gumroad.get("url", ""),
                    "gumroad_success": gumroad.get("success", False),
                },
            )
        except Exception as exc:
            logger.error("[RevenueEngine] Error registrando lanzamiento: %s", exc)

    # ─── UTILIDADES PÚBLICAS ────────────────────────────────────

    def get_ready_products(self) -> list[dict]:
        """Retorna todos los productos listos para lanzar."""
        return READY_TO_LAUNCH_PRODUCTS

    def get_product_by_id(self, product_id: str) -> Optional[dict]:
        return next((p for p in READY_TO_LAUNCH_PRODUCTS if p["id"] == product_id), None)

    def estimate_revenue_potential(self, product_id: str, conversions: int = 10) -> dict:
        """Estima el potencial de ingresos de un producto."""
        product = self.get_product_by_id(product_id)
        if not product:
            return {"error": "Producto no encontrado"}
        price = product["price_usd"]
        return {
            "product": product["title"],
            "price": price,
            "conservative_revenue": price * conversions,         # 10 ventas
            "moderate_revenue": price * conversions * 5,         # 50 ventas
            "optimistic_revenue": price * conversions * 20,      # 200 ventas
            "breakeven_sales": 1,                                # productos digitales = 100% margen
            "note": "Productos digitales tienen 90-100% de margen después del primer dólar",
        }

    async def create_product_from_trend(self, trend_topic: str, niche: str) -> dict:
        """
        Crea un nuevo producto digital basado en una tendencia detectada.
        Usa IA para generar el contenido.
        """
        if not self.ai:
            return {"success": False, "error": "AI client no disponible"}

        try:
            # Generar idea de producto con IA
            idea_response = await self.ai.complete(
                system=(
                    "Eres un experto en productos digitales. "
                    "Dado un tema tendencia y un nicho, propón un producto digital específico "
                    "que se pueda crear en 1-3 días y venderse por $17-$97. "
                    "Responde en JSON con: title, type, price_usd (número), contents (lista), "
                    "benefit, pain, target_audience."
                ),
                user=f"Tema: {trend_topic}\nNicho: {niche}\n\nPropón un producto digital.",
                model=AIModel.STRATEGY,
                max_tokens=500,
            )

            if not idea_response.success:
                return {"success": False, "error": "AI no disponible"}

            # Parsear la respuesta
            import json, re
            raw = idea_response.content
            # Extraer JSON si está en markdown
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                product_idea = json.loads(json_match.group())
            else:
                product_idea = {"title": f"Guía: {trend_topic} para {niche}", "price_usd": 27}

            product_idea.update({
                "id": f"ai_generated_{trend_topic[:20].lower().replace(' ', '_')}",
                "distribution_channels": ["twitter", "linkedin"],
            })

            logger.info("[RevenueEngine] Producto AI generado: %s", product_idea.get("title"))
            return {"success": True, "product": product_idea}

        except Exception as exc:
            logger.error("[RevenueEngine] Error creando producto desde tendencia: %s", exc)
            return {"success": False, "error": str(exc)}


# ─────────────────────────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────────────────────────

_engine: Optional[RevenueEngine] = None


def get_revenue_engine() -> RevenueEngine:
    global _engine
    if _engine is None:
        _engine = RevenueEngine()
    return _engine
