"""
ecommerce_agent.py — Agente Especializado de E-commerce y Ventas High-Ticket v1.0

Este agente es el cerebro de las operaciones de comercio electrónico de Aria.
Sus responsabilidades son:
1. Investigar en la web las mejores prácticas de Shopify, Zapier y e-commerce.
2. Crear productos completos (listing, inventario, imágenes, videos) en Shopify.
3. Diseñar y ejecutar embudos de venta para servicios de alto valor (High-Ticket).
4. Automatizar flujos de trabajo entre Shopify y otras apps vía Zapier (MCP).
5. Aprender continuamente de las tendencias del mercado para optimizar la tienda.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings
from apps.core.tools.ai_client import AIModel, get_ai_client
from apps.core.tools.aria_tools import tool_registry

logger = logging.getLogger("aria.ecommerce_agent")


# ── CONOCIMIENTO INTEGRADO DE E-COMMERCE ─────────────────────────────────────

ECOMMERCE_KNOWLEDGE = {
    "shopify_listing_best_practices": [
        "Título SEO: incluir keyword principal, marca y atributo clave (color, material, tamaño).",
        "Descripción HTML persuasiva: usar formato AIDA (Atención, Interés, Deseo, Acción).",
        "Imágenes: mínimo 3-5 fotos de alta resolución (fondo blanco + lifestyle). Alt text con keywords.",
        "Precio competitivo: investigar competidores antes de fijar precio. Mostrar precio original tachado.",
        "Inventario: siempre gestionar con Shopify para evitar overselling.",
        "Tags: incluir 10-15 tags relevantes para búsquedas internas y apps de marketing.",
        "SEO metafields: optimizar título SEO (max 70 chars) y meta descripción (max 160 chars).",
        "Structured data: asegurar que el tema incluya Product schema para Google Shopping.",
        "Reviews: configurar app de reseñas (Judge.me, Yotpo) para generar social proof.",
        "Colecciones: organizar productos en colecciones lógicas para mejorar navegación.",
    ],
    "zapier_shopify_automations": [
        "New Order → Slack/Gmail: notificar al equipo de cada venta en tiempo real.",
        "New Customer → Mailchimp/Klaviyo: añadir a lista de email marketing (con consentimiento).",
        "Inventory Updated → Gmail: alertar cuando el stock baja de umbral mínimo.",
        "Abandoned Cart → Gmail/SMS: enviar recordatorio personalizado a las 1h, 24h y 72h.",
        "New Order → Google Sheets: registrar ventas para análisis y reportes automáticos.",
        "New Customer → HubSpot: crear contacto en CRM para seguimiento.",
        "Quiz/Form Submission → OpenAI → Gmail: consultoría de producto personalizada con IA.",
        "New Paid Order → Typeform: enviar encuesta de satisfacción post-compra.",
        "Product Back in Stock → Email List: notificar a clientes interesados.",
        "New Order → Airtable: sincronizar datos para gestión de operaciones.",
    ],
    "high_ticket_sales_strategies": [
        "Cualificación: usar formulario de aplicación para filtrar prospectos serios antes de invertir tiempo.",
        "Posicionamiento de autoridad: publicar casos de éxito, testimonios y resultados cuantificables.",
        "Vender transformación, no precio: enfocarse en el ROI y cambio de vida que obtendrá el cliente.",
        "Proceso consultivo: actuar como asesor experto, no como vendedor. Escuchar más que hablar.",
        "Propuesta de valor única: diferenciarse claramente de la competencia con garantías y bonos.",
        "Seguimiento de valor: enviar recursos útiles (artículos, videos, casos de éxito) entre contactos.",
        "Urgencia real: usar fechas límite y plazas limitadas genuinas, no artificiales.",
        "Precio ancla: mostrar el valor total del servicio antes de revelar el precio real.",
        "Garantía de resultados: ofrecer garantía de devolución para reducir el riesgo percibido.",
        "Onboarding premium: el proceso de incorporación del cliente debe ser impecable y memorable.",
    ],
    "product_research_framework": [
        "Analizar tendencias en Google Trends, Amazon Best Sellers y TikTok Shop.",
        "Validar demanda con keyword research (Ahrefs, SEMrush, Google Keyword Planner).",
        "Estudiar reseñas negativas de competidores para identificar gaps del mercado.",
        "Calcular márgenes: precio de venta debe ser mínimo 3x el costo (regla del 3x).",
        "Verificar restricciones: evitar productos con patentes, regulaciones o alta competencia.",
        "Evaluar potencial de upsell: productos con accesorios o consumibles recurrentes.",
        "Analizar estacionalidad para planificar inventario y campañas de marketing.",
    ],
    "content_for_ecommerce": [
        "Videos de producto: mostrar el producto en uso, unboxing y comparativas (30-90 segundos).",
        "Fotos lifestyle: mostrar el producto en contexto real con modelos o ambientes aspiracionales.",
        "Infografías: destacar características técnicas de forma visual y fácil de entender.",
        "User Generated Content (UGC): incentivar a clientes a compartir fotos/videos usando el producto.",
        "Guías de compra: crear contenido educativo que posicione a Aria como experta en el nicho.",
        "Comparativas: artículos 'Producto A vs Producto B' para capturar tráfico de búsqueda.",
    ]
}


class EcommerceAgent(BaseAgent):
    """
    Agente especializado en e-commerce, Shopify, Zapier y ventas High-Ticket.
    Aprende continuamente de la web y ejecuta operaciones reales en Shopify.
    """

    def __init__(self) -> None:
        super().__init__(
            name="ecommerce",
            description="Agente de e-commerce: Shopify, Zapier, listings, inventario y High-Ticket",
            capabilities=[
                "shopify_product_creation",
                "listing_optimization",
                "inventory_management",
                "zapier_automation",
                "high_ticket_sales",
                "market_research",
                "content_creation",
            ],
        )
        self.knowledge = ECOMMERCE_KNOWLEDGE
        self._zapier = tool_registry.get_tool("zapier")
        self._web = tool_registry.get_tool("web_scraping")

    async def _execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta la misión de e-commerce según el contexto recibido."""
        task = context.get("task", "full_ecommerce_pipeline")
        topic = context.get("target_topic", "productos de alto valor")

        logger.info(f"[EcommerceAgent] Iniciando tarea: {task} | Tema: {topic}")

        if task == "research_and_create_product":
            return await self._research_and_create_product(topic)
        elif task == "optimize_store":
            return await self._optimize_store()
        elif task == "setup_zapier_automations":
            return await self._setup_zapier_automations()
        elif task == "high_ticket_funnel":
            return await self._create_high_ticket_funnel(topic)
        elif task == "full_ecommerce_pipeline":
            return await self._full_ecommerce_pipeline(topic)
        else:
            return await self._full_ecommerce_pipeline(topic)

    # ── PIPELINE COMPLETO ─────────────────────────────────────────

    async def _full_ecommerce_pipeline(self, topic: str) -> Dict[str, Any]:
        """
        Pipeline completo de e-commerce:
        1. Investigar tendencias y oportunidades de mercado.
        2. Generar idea de producto con IA.
        3. Crear listing optimizado en Shopify.
        4. Configurar automatizaciones de Zapier.
        5. Crear embudo de ventas High-Ticket.
        """
        results = {}

        # Paso 1: Investigar el mercado
        market_data = await self._research_market(topic)
        results["market_research"] = market_data

        # Paso 2: Generar idea de producto con IA
        product_idea = await self._generate_product_idea(topic, market_data)
        results["product_idea"] = product_idea

        # Paso 3: Crear listing en Shopify (si está configurado)
        if settings.SHOPIFY_ENABLED and product_idea.get("title"):
            shopify_result = await self._create_shopify_listing(product_idea)
            results["shopify_listing"] = shopify_result
            
            # Tomar screenshot del producto creado si tenemos la URL
            if shopify_result.get("success") and shopify_result.get("product_url"):
                from apps.core.tools.web_tools import WebTools
                wt = WebTools()
                ss_res = await wt.take_screenshot(shopify_result["product_url"])
                if ss_res.get("success"):
                    results["product_screenshot"] = ss_res["screenshot_path"]

        # Paso 4: Configurar Zapier
        zapier_result = await self._setup_zapier_automations()
        results["zapier_automations"] = zapier_result

        # Paso 5: Estrategia High-Ticket
        highticket_strategy = await self._create_high_ticket_funnel(topic)
        results["high_ticket_strategy"] = highticket_strategy

        results["success"] = True
        results["summary"] = f"Pipeline e-commerce completado para: {topic}"
        return results

    # ── INVESTIGACIÓN DE MERCADO ──────────────────────────────────

    async def _research_market(self, topic: str) -> Dict[str, Any]:
        """Investiga tendencias, competidores y oportunidades en la web con screenshots."""
        logger.info(f"[EcommerceAgent] Investigando mercado para: {topic}")

        research_data = {
            "topic": topic,
            "best_practices": self.knowledge["shopify_listing_best_practices"],
            "product_research_framework": self.knowledge["product_research_framework"],
            "screenshots": []
        }

        # Intentar búsqueda web y screenshots si está disponible
        if self._web:
            try:
                search_query = f"best shopify products to sell {topic} 2025 high demand"
                # Usamos el buscador expandido que implementamos antes
                from apps.core.tools.web_tools import WebTools
                wt = WebTools()
                search_results = await wt.search_web(search_query, num_results=3)
                
                if search_results.get("success") and search_results.get("results"):
                    research_data["web_findings"] = str(search_results["results"])
                    
                    # Tomar screenshot del primer resultado relevante (competencia)
                    top_url = search_results["results"][0].get("url")
                    if top_url:
                        ss_res = await wt.take_screenshot(top_url)
                        if ss_res.get("success"):
                            research_data["screenshots"].append(ss_res["screenshot_path"])
                            logger.info(f"[EcommerceAgent] Screenshot de competencia guardado: {ss_res['screenshot_path']}")
                            
            except Exception as e:
                logger.warning(f"[EcommerceAgent] Error en investigacion con screenshots: {e}")

        return research_data

    async def _research_and_create_product(self, topic: str) -> Dict[str, Any]:
        """Investiga y crea un producto completo en Shopify."""
        market_data = await self._research_market(topic)
        product_idea = await self._generate_product_idea(topic, market_data)

        if settings.SHOPIFY_ENABLED and product_idea.get("title"):
            return await self._create_shopify_listing(product_idea)

        return {"success": True, "product_idea": product_idea, "note": "Shopify no configurado — modo simulación"}

    # ── GENERACIÓN DE PRODUCTOS CON IA ────────────────────────────

    async def _generate_product_idea(self, topic: str, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Usa IA para generar una idea de producto completa y optimizada para Shopify."""
        ai = get_ai_client()
        if not ai:
            return self._fallback_product_idea(topic)

        system_prompt = (
            "Eres un experto en e-commerce y Shopify con 10 años de experiencia. "
            "Tu especialidad es crear listings de productos que convierten y se posicionan en Google. "
            "Responde SOLO con JSON válido sin markdown."
        )

        best_practices = "\n".join(f"- {p}" for p in self.knowledge["shopify_listing_best_practices"][:5])

        user_prompt = f"""Crea un listing completo y optimizado para Shopify sobre: "{topic}"

MEJORES PRÁCTICAS A APLICAR:
{best_practices}

Genera el JSON con este formato exacto:
{{
  "title": "Título SEO optimizado (max 70 chars, incluir keyword principal)",
  "description_html": "<p>Descripción persuasiva en HTML usando formato AIDA. Mínimo 200 palabras.</p>",
  "price": "precio en USD como string (ej: '49.99')",
  "compare_at_price": "precio original tachado (ej: '79.99')",
  "sku": "código SKU único",
  "inventory": 50,
  "category": "tipo de producto",
  "vendor": "nombre de marca",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "seo_title": "Título para Google (max 70 chars)",
  "seo_description": "Meta descripción para Google (max 160 chars)",
  "requires_shipping": true,
  "weight": 0.5,
  "weight_unit": "kg",
  "image_suggestions": ["descripción de imagen 1", "descripción de imagen 2", "descripción de imagen 3"],
  "video_concept": "concepto para video de producto de 30-60 segundos",
  "zapier_automations": ["automatización 1 recomendada", "automatización 2 recomendada"],
  "high_ticket_upsell": "descripción de servicio premium relacionado para vender a $500-$5000"
}}"""

        try:
            product = await ai.complete_json(
                system=system_prompt,
                user=user_prompt,
                model=AIModel.CREATIVE,
                max_tokens=1500,
                agent_name="ecommerce",
            )
            if product and product.get("title"):
                logger.info(f"[EcommerceAgent] Producto generado: {product.get('title')}")
                return product
        except Exception as e:
            logger.error(f"[EcommerceAgent] Error generando producto con IA: {e}")

        return self._fallback_product_idea(topic)

    def _fallback_product_idea(self, topic: str) -> Dict[str, Any]:
        """Plan de emergencia cuando la IA no responde."""
        return {
            "title": f"Producto Premium de {topic}",
            "description_html": f"<p>Descubre el mejor producto de <strong>{topic}</strong>. Calidad premium garantizada.</p>",
            "price": "99.99",
            "compare_at_price": "149.99",
            "sku": f"ARIA-{topic[:3].upper()}-001",
            "inventory": 50,
            "category": "General",
            "vendor": "Aria Premium",
            "tags": [topic, "premium", "calidad", "oferta", "nuevo"],
            "seo_title": f"Comprar {topic} Premium | Mejor Precio",
            "seo_description": f"Encuentra el mejor {topic} al mejor precio. Envío rápido y garantía incluida.",
            "requires_shipping": True,
            "image_suggestions": ["foto de producto en fondo blanco", "foto lifestyle en uso", "detalle de calidad"],
            "video_concept": f"Video de 45 segundos mostrando {topic} en uso con testimonios de clientes",
            "zapier_automations": ["New Order → Slack notification", "New Customer → Mailchimp"],
            "high_ticket_upsell": f"Consultoría personalizada de {topic} — $997/sesión",
        }

    # ── CREACIÓN DE LISTING EN SHOPIFY ────────────────────────────

    async def _create_shopify_listing(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Crea un listing completo y optimizado en Shopify."""
        try:
            from apps.core.integrations.shopify_engine import ShopifyEngine
            engine = ShopifyEngine(settings.SHOPIFY_SHOP_NAME, settings.SHOPIFY_ACCESS_TOKEN)

            product_id = engine.create_optimized_product(product_data)
            if product_id:
                shop_url = f"https://{settings.SHOPIFY_SHOP_NAME}.myshopify.com/products/"
                logger.info(f"[EcommerceAgent] Listing creado en Shopify: {product_data['title']}")
                return {
                    "success": True,
                    "product_id": product_id,
                    "shop_url": shop_url,
                    "title": product_data["title"],
                    "price": product_data.get("price"),
                    "note": "Listing optimizado creado con SEO, inventario y tags.",
                }
            return {"success": False, "error": "No se pudo crear el producto en Shopify"}
        except Exception as e:
            logger.error(f"[EcommerceAgent] Error creando listing en Shopify: {e}")
            return {"success": False, "error": str(e)}

    async def _optimize_store(self) -> Dict[str, Any]:
        """Analiza y optimiza la tienda Shopify existente."""
        try:
            from apps.core.integrations.shopify_engine import ShopifyEngine
            engine = ShopifyEngine(settings.SHOPIFY_SHOP_NAME, settings.SHOPIFY_ACCESS_TOKEN)

            products = engine.get_all_products()
            orders_report = engine.get_orders_report()

            optimizations = []
            for product in products[:10]:
                issues = []
                if not product.get("images"):
                    issues.append("Sin imágenes — añadir mínimo 3 fotos de alta calidad")
                if len(product.get("tags", "")) < 20:
                    issues.append("Pocos tags — añadir 10-15 tags relevantes para SEO")
                if not product.get("body_html") or len(product.get("body_html", "")) < 200:
                    issues.append("Descripción corta — expandir con beneficios y keywords")
                if issues:
                    optimizations.append({"product": product.get("title"), "issues": issues})

            return {
                "success": True,
                "total_products": len(products),
                "revenue_report": orders_report,
                "optimization_recommendations": optimizations,
                "best_practices": self.knowledge["shopify_listing_best_practices"],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── AUTOMATIZACIONES ZAPIER ───────────────────────────────────

    async def _setup_zapier_automations(self) -> Dict[str, Any]:
        """Configura y documenta las automatizaciones de Zapier para Shopify."""
        automations = self.knowledge["zapier_shopify_automations"]

        if self._zapier:
            try:
                # Intentar listar las acciones disponibles en Zapier vía MCP
                result = await self._zapier.call_zapier_action(
                    "list_actions",
                    {"app": "shopify"}
                )
                logger.info(f"[EcommerceAgent] Zapier acciones disponibles: {result}")
                return {
                    "success": True,
                    "recommended_automations": automations,
                    "zapier_connection": result,
                    "note": "Zapier MCP conectado. Configurar Zaps recomendados en el dashboard de Zapier.",
                }
            except Exception as e:
                logger.warning(f"[EcommerceAgent] Zapier MCP no disponible: {e}")

        return {
            "success": True,
            "recommended_automations": automations,
            "note": "Automatizaciones documentadas. Configurar manualmente en zapier.com/apps/shopify/integrations",
        }

    # ── EMBUDO HIGH-TICKET ────────────────────────────────────────

    async def _create_high_ticket_funnel(self, topic: str) -> Dict[str, Any]:
        """Diseña un embudo de ventas para servicios de alto valor relacionados con el tema."""
        ai = get_ai_client()
        if not ai:
            return self._fallback_high_ticket_funnel(topic)

        system_prompt = (
            "Eres un experto en ventas de servicios de alto valor (High-Ticket) con experiencia "
            "en negocios digitales, consultoría y coaching premium. "
            "Responde SOLO con JSON válido sin markdown."
        )

        strategies = "\n".join(f"- {s}" for s in self.knowledge["high_ticket_sales_strategies"][:5])

        user_prompt = f"""Diseña un embudo de ventas High-Ticket para servicios relacionados con: "{topic}"

ESTRATEGIAS A APLICAR:
{strategies}

Genera el JSON con este formato:
{{
  "service_name": "nombre del servicio premium",
  "price_range": "rango de precio (ej: $997 - $4,997)",
  "target_audience": "descripción del cliente ideal",
  "value_proposition": "propuesta de valor única en 2 oraciones",
  "funnel_stages": [
    {{"stage": "Awareness", "action": "qué hacer para atraer leads"}},
    {{"stage": "Interest", "action": "cómo generar interés"}},
    {{"stage": "Qualification", "action": "cómo cualificar prospectos"}},
    {{"stage": "Proposal", "action": "cómo presentar la propuesta"}},
    {{"stage": "Close", "action": "técnica de cierre recomendada"}}
  ],
  "follow_up_sequence": ["mensaje 1 (día 1)", "mensaje 2 (día 3)", "mensaje 3 (día 7)"],
  "shopify_integration": "cómo integrar este servicio en la tienda Shopify",
  "zapier_automation": "automatización de Zapier recomendada para este embudo"
}}"""

        try:
            funnel = await ai.complete_json(
                system=system_prompt,
                user=user_prompt,
                model=AIModel.STRATEGY,
                max_tokens=1200,
                agent_name="ecommerce",
            )
            if funnel and funnel.get("service_name"):
                logger.info(f"[EcommerceAgent] Embudo High-Ticket creado: {funnel.get('service_name')}")
                return {"success": True, "funnel": funnel}
        except Exception as e:
            logger.error(f"[EcommerceAgent] Error creando embudo High-Ticket: {e}")

        return self._fallback_high_ticket_funnel(topic)

    def _fallback_high_ticket_funnel(self, topic: str) -> Dict[str, Any]:
        """Embudo de emergencia cuando la IA no responde."""
        return {
            "success": True,
            "funnel": {
                "service_name": f"Consultoría Premium de {topic}",
                "price_range": "$997 - $4,997",
                "target_audience": f"Emprendedores y empresas que necesitan dominar {topic}",
                "value_proposition": f"Transformamos tu negocio con {topic} en 90 días o te devolvemos el dinero.",
                "funnel_stages": [
                    {"stage": "Awareness", "action": "Publicar contenido educativo en LinkedIn y blog"},
                    {"stage": "Interest", "action": "Ofrecer webinar gratuito de 60 minutos"},
                    {"stage": "Qualification", "action": "Formulario de aplicación con 5 preguntas clave"},
                    {"stage": "Proposal", "action": "Llamada de descubrimiento de 30 min + propuesta personalizada"},
                    {"stage": "Close", "action": "Assumptive Close con garantía de resultados"},
                ],
                "follow_up_sequence": [
                    "Día 1: Enviar caso de éxito relevante",
                    "Día 3: Compartir recurso gratuito de valor",
                    "Día 7: Email de 'break-up' con urgencia genuina",
                ],
                "shopify_integration": "Crear página de servicio en Shopify con botón de aplicación",
                "zapier_automation": "Form submission → Calendly → Gmail confirmation → HubSpot CRM",
            }
        }
