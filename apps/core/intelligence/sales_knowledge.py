"""
ARIA Business Intelligence & Sales Knowledge Base v2.0
Contiene técnicas de ventas, psicología de consumo, copywriting, estrategias de marketing,
mejores prácticas de Shopify, automatizaciones de Zapier y ventas de servicios High-Ticket.
Este módulo actúa como una "librería de sabiduría" que los agentes consultan para optimizar resultados.
"""

# ── TÉCNICAS DE VENTAS CLÁSICAS ───────────────────────────────────────────────

SALES_TECHNIQUES = {
    "closing": [
        "The Assumptive Close: Actuar como si el cliente ya hubiera decidido comprar.",
        "The Urgency Close: Crear escasez real o temporal (Limited time offer).",
        "The Puppy Dog Close: Ofrecer una prueba sin compromiso.",
        "The Ben Franklin Close: Listar pros y contras, asegurando que los pros ganen por mucho.",
        "The Summary Close: Resumir todos los beneficios acordados antes de pedir la decisión.",
        "The Question Close: '¿Qué necesitarías ver para tomar esta decisión hoy?'",
    ],
    "psychology": [
        "Social Proof: Mostrar que otros ya están obteniendo resultados.",
        "Reciprocity: Dar valor gratuito antes de pedir la venta.",
        "Authority: Posicionar a ARIA como la experta indiscutible en el nicho.",
        "Commitment & Consistency: Lograr pequeños 'sí' antes del gran 'sí'.",
        "Scarcity: Limitar disponibilidad genuinamente para aumentar el deseo.",
        "Loss Aversion: Mostrar lo que el cliente pierde por NO actuar ahora.",
        "Anchoring: Presentar el precio alto primero para que el real parezca razonable.",
    ],
    "copywriting": [
        "AIDA: Attention, Interest, Desire, Action.",
        "PAS: Problem, Agitation, Solution.",
        "Before-After-Bridge: Mostrar el estado actual, el deseado y cómo el producto es el puente.",
        "The 4 P's: Promise, Picture, Proof, Push.",
        "FAB: Features, Advantages, Benefits — siempre terminar en el beneficio para el cliente.",
        "Storytelling: Usar historias de clientes reales para crear conexión emocional.",
    ],
    "follow_up": [
        "The 3-Day Rule: Primer seguimiento a los 3 días si no hay respuesta.",
        "Value-First Follow-up: Enviar un recurso útil en lugar de solo preguntar '¿viste mi mensaje?'.",
        "The 'Break-up' Email: Un último mensaje educado indicando que dejaremos de insistir (genera urgencia).",
        "Multi-channel Follow-up: Combinar email, LinkedIn y Telegram para mayor alcance.",
        "Automated Sequences: Usar Zapier + Mailchimp para secuencias de nurturing automatizadas.",
    ]
}

# ── ESTRATEGIAS DE MARKETING ──────────────────────────────────────────────────

MARKETING_STRATEGY = {
    "content_pillars": [
        "Educational: Enseñar cómo resolver un problema específico.",
        "Inspirational: Casos de éxito y transformaciones.",
        "Promotional: Ofertas directas y beneficios del producto.",
        "Engagement: Preguntas y encuestas para conocer a la audiencia.",
        "Behind-the-Scenes: Mostrar el proceso de creación del producto para generar confianza.",
    ],
    "distribution_channels": {
        "organic": ["SEO Blogs", "X (Twitter) Threads", "LinkedIn Articles", "Reddit Communities", "TikTok Orgánico"],
        "paid": ["Meta Ads", "Google Search", "TikTok Spark Ads", "Google Shopping"],
        "direct": ["Email Newsletters", "Telegram Channel", "Direct Outreach", "WhatsApp Business"],
        "ecommerce": ["Shopify Store", "Google Shopping", "Instagram Shopping", "TikTok Shop"],
    }
}

# ── CONOCIMIENTO DE SHOPIFY ───────────────────────────────────────────────────

SHOPIFY_KNOWLEDGE = {
    "listing_optimization": [
        "Título SEO: incluir keyword principal, marca y atributo clave (max 70 caracteres).",
        "Descripción HTML persuasiva: usar formato AIDA con párrafos cortos y bullet points.",
        "Imágenes: mínimo 3-5 fotos de alta resolución. Fondo blanco para comparación + lifestyle.",
        "Alt text en imágenes: incluir keyword principal y descripción del producto.",
        "Precio competitivo: investigar competidores. Mostrar precio original tachado (compare_at_price).",
        "Inventario: siempre gestionar con Shopify para evitar overselling.",
        "Tags: incluir 10-15 tags relevantes para búsquedas internas y apps de marketing.",
        "SEO metafields: optimizar título SEO (max 70 chars) y meta descripción (max 160 chars).",
        "Structured data: asegurar Product schema para Google Shopping y rich snippets.",
        "Reviews: configurar app de reseñas (Judge.me, Yotpo) para generar social proof.",
        "Colecciones: organizar productos en colecciones lógicas para mejorar navegación y SEO.",
        "Videos: añadir video de producto de 30-90 segundos para aumentar conversión.",
    ],
    "store_optimization": [
        "Tema rápido: usar Shopify 2.0 themes (Dawn, Debut) para mejor rendimiento.",
        "Core Web Vitals: optimizar LCP, FID y CLS para mejorar ranking en Google.",
        "Mobile-first: asegurar que la tienda sea perfecta en móvil (70%+ del tráfico).",
        "Checkout optimizado: reducir pasos al mínimo y ofrecer múltiples métodos de pago.",
        "Upsell y Cross-sell: configurar apps de recomendaciones (ReConvert, Frequently Bought Together).",
        "Abandoned Cart Recovery: configurar emails automáticos a 1h, 24h y 72h.",
        "Live Chat: añadir chat en vivo para resolver dudas y aumentar conversión.",
        "Trust Badges: mostrar sellos de seguridad, garantías y métodos de pago.",
        "Velocidad de carga: comprimir imágenes, usar CDN y minimizar apps innecesarias.",
    ],
    "product_research": [
        "Analizar Google Trends para identificar productos en tendencia ascendente.",
        "Revisar Amazon Best Sellers y Movers & Shakers para validar demanda.",
        "Estudiar TikTok Shop y hashtags virales para productos trending.",
        "Calcular margen: precio de venta debe ser mínimo 3x el costo (regla del 3x).",
        "Verificar restricciones: evitar productos con patentes, regulaciones o alta competencia.",
        "Evaluar potencial de upsell: productos con accesorios o consumibles recurrentes.",
        "Analizar reseñas negativas de competidores para identificar gaps del mercado.",
        "Validar con keyword research: mínimo 1,000 búsquedas mensuales del producto.",
    ],
    "marketing_channels": [
        "Google Shopping: sincronizar catálogo con Google Merchant Center para tráfico gratuito.",
        "Instagram Shopping: etiquetar productos en posts y stories para compra directa.",
        "TikTok Shop: integrar tienda para aprovechar el tráfico viral de TikTok.",
        "Pinterest Shopping: ideal para productos visuales (moda, hogar, decoración).",
        "Email Marketing: Klaviyo o Mailchimp para secuencias de bienvenida, abandono y post-compra.",
        "SMS Marketing: Postscript o Attentive para notificaciones de alta apertura.",
        "Influencer Marketing: colaborar con micro-influencers (10K-100K) para mayor ROI.",
        "Retargeting Ads: Meta Pixel y Google Ads para recuperar visitantes que no compraron.",
    ]
}

# ── CONOCIMIENTO DE ZAPIER + SHOPIFY ─────────────────────────────────────────

ZAPIER_SHOPIFY_AUTOMATIONS = {
    "revenue_generation": [
        "Quiz/Form → OpenAI → Email: consultoría de producto personalizada con IA (Revenue First Strategy).",
        "Abandoned Cart → Gmail/SMS: recordatorio personalizado a 1h, 24h y 72h.",
        "New Customer → Klaviyo: secuencia de bienvenida de 7 emails con valor y ofertas.",
        "Product Back in Stock → Email List: notificar a clientes en lista de espera.",
        "High-Value Order → Slack + CRM: alertar para seguimiento VIP personalizado.",
    ],
    "operations": [
        "New Order → Google Sheets: registrar ventas para análisis y reportes automáticos.",
        "New Order → Gmail/Slack: notificar al equipo de cada venta en tiempo real.",
        "Inventory Updated → Gmail: alertar cuando el stock baja del umbral mínimo.",
        "New Paid Order → Airtable: sincronizar datos para gestión de operaciones.",
        "Fraud Order → Slack: alertar inmediatamente para detener envío.",
    ],
    "customer_retention": [
        "New Customer → HubSpot/Salesforce: crear contacto en CRM para seguimiento.",
        "New Customer → Mailchimp: añadir a lista de email marketing (con consentimiento GDPR).",
        "Post-Purchase → Typeform: enviar encuesta de satisfacción a los 7 días.",
        "VIP Customer (LTV > $500) → Slack: identificar y dar tratamiento especial.",
        "Repeat Customer → Discount Code: enviar código de descuento automático.",
    ],
    "ai_powered": [
        "New Order → OpenAI → Personalized Thank You Email: email de agradecimiento único.",
        "Customer Review → OpenAI → Response: responder reseñas automáticamente con IA.",
        "New Product → OpenAI → Social Post: generar post de redes sociales automáticamente.",
        "Sales Data → OpenAI → Weekly Report: reporte de ventas con insights de IA.",
        "Customer Query → OpenAI → Support Response: soporte al cliente con IA 24/7.",
    ]
}

# ── VENTAS HIGH-TICKET ────────────────────────────────────────────────────────

HIGH_TICKET_KNOWLEDGE = {
    "service_categories": [
        "Consultoría de Negocios: $1,000 - $10,000/mes. Ayudar a empresas a escalar.",
        "Coaching Ejecutivo: $500 - $5,000/sesión. Desarrollo de liderazgo y estrategia.",
        "Desarrollo de Software a Medida: $5,000 - $50,000/proyecto.",
        "Agencia de Marketing Digital: $2,000 - $20,000/mes. Gestión completa de marketing.",
        "Formación Empresarial: $3,000 - $30,000/programa. Capacitación de equipos.",
        "Diseño de Marca Premium: $5,000 - $25,000/proyecto. Identidad visual completa.",
        "Automatización con IA: $3,000 - $15,000/proyecto. Implementar IA en negocios.",
        "Consultoría de E-commerce: $2,000 - $10,000/mes. Optimizar tiendas online.",
    ],
    "qualification_process": [
        "Formulario de aplicación: filtrar prospectos con 5-7 preguntas clave sobre presupuesto y objetivos.",
        "Llamada de descubrimiento: 30 min para entender el problema y evaluar fit.",
        "Propuesta personalizada: documento de 3-5 páginas con solución específica y ROI esperado.",
        "Presentación de propuesta: llamada de 60 min para presentar y resolver objeciones.",
        "Contrato y onboarding: proceso de incorporación premium que justifique el precio.",
    ],
    "pricing_strategies": [
        "Value-Based Pricing: cobrar en función del valor generado, no del tiempo invertido.",
        "Retainer Model: cobro mensual recurrente para ingresos predecibles.",
        "Performance-Based: cobrar un % de los resultados generados (ej: 10% del incremento de ventas).",
        "Productized Services: empaquetar el servicio como un producto con precio fijo y entregables claros.",
        "Tiered Packages: ofrecer 3 niveles (Básico, Profesional, Premium) para maximizar conversión.",
    ],
    "objection_handling": [
        "'Es muy caro': Reencuadrar al costo de NO resolver el problema. Mostrar ROI específico.",
        "'Necesito pensarlo': Preguntar qué información adicional necesita para decidir.",
        "'No tengo presupuesto': Explorar opciones de pago en cuotas o comenzar con un proyecto piloto.",
        "'¿Por qué tú y no otro?': Presentar casos de éxito específicos y diferenciadores únicos.",
        "'Necesito consultarlo con mi socio': Ofrecer incluir al socio en la próxima llamada.",
    ],
    "shopify_integration": [
        "Crear página de servicio en Shopify con descripción detallada y botón de aplicación.",
        "Usar Shopify para cobrar depósitos o pagos iniciales de servicios.",
        "Crear productos digitales (ebooks, cursos) como entrada al embudo High-Ticket.",
        "Configurar Zapier para que nuevas compras de productos de entrada activen seguimiento de ventas.",
        "Usar Shopify Analytics para identificar clientes de alto valor (LTV) para ofertas premium.",
    ]
}

# ── VOCABULARIO EXPANDIDO ─────────────────────────────────────────────────────

VOCABULARY_EXPANSION = {
    "persuasive_verbs": [
        "Acelerar", "Desbloquear", "Dominar", "Escalar", "Transformar", "Maximizar",
        "Automatizar", "Conquistar", "Simplificar", "Potenciar", "Optimizar", "Multiplicar"
    ],
    "emotional_triggers": [
        "Exclusivo", "Instantáneo", "Garantizado", "Revelado", "Limitado",
        "Secreto", "Probado", "Poderoso", "Esencial", "Lucrativo", "Premium", "Elite"
    ],
    "business_terms": [
        "ROI (Retorno de Inversión)", "LTV (Lifetime Value)", "CAC (Costo de Adquisición)",
        "Churn Rate", "Conversion Rate Optimization (CRO)", "Scalability", "Synergy",
        "Average Order Value (AOV)", "Customer Retention Rate", "Net Promoter Score (NPS)",
        "Gross Margin", "MRR (Monthly Recurring Revenue)", "ARR (Annual Recurring Revenue)"
    ],
    "ecommerce_terms": [
        "Listing Optimization", "Product-Market Fit", "Abandoned Cart Recovery",
        "Upsell", "Cross-sell", "Bundle", "Flash Sale", "BFCM (Black Friday Cyber Monday)",
        "Dropshipping", "Print-on-Demand", "Private Label", "White Label",
        "SKU (Stock Keeping Unit)", "COGS (Cost of Goods Sold)", "Fulfillment"
    ]
}


# ── FUNCIONES DE ACCESO ───────────────────────────────────────────────────────

def get_sales_advice(category: str = "closing") -> list:
    return SALES_TECHNIQUES.get(category, [])

def get_marketing_strategy() -> dict:
    return MARKETING_STRATEGY

def get_vocab() -> dict:
    return VOCABULARY_EXPANSION

def get_shopify_knowledge(category: str = "listing_optimization") -> list:
    """Obtiene conocimiento específico de Shopify por categoría."""
    return SHOPIFY_KNOWLEDGE.get(category, [])

def get_zapier_automations(category: str = "revenue_generation") -> list:
    """Obtiene automatizaciones de Zapier recomendadas por categoría."""
    return ZAPIER_SHOPIFY_AUTOMATIONS.get(category, [])

def get_high_ticket_knowledge(category: str = "service_categories") -> list:
    """Obtiene conocimiento de ventas High-Ticket por categoría."""
    return HIGH_TICKET_KNOWLEDGE.get(category, [])

def get_full_ecommerce_playbook() -> dict:
    """Retorna el playbook completo de e-commerce para Aria."""
    return {
        "shopify": SHOPIFY_KNOWLEDGE,
        "zapier": ZAPIER_SHOPIFY_AUTOMATIONS,
        "high_ticket": HIGH_TICKET_KNOWLEDGE,
        "sales": SALES_TECHNIQUES,
        "marketing": MARKETING_STRATEGY,
        "vocabulary": VOCABULARY_EXPANSION,
    }
