"""
ARIA Business Intelligence & Sales Knowledge Base v1.0
Contiene técnicas de ventas, psicología de consumo, copywriting y estrategias de marketing.
Este módulo actúa como una "librería de sabiduría" que los agentes consultan para optimizar resultados.
"""

SALES_TECHNIQUES = {
    "closing": [
        "The Assumptive Close: Actuar como si el cliente ya hubiera decidido comprar.",
        "The Urgency Close: Crear escasez real o temporal (Limited time offer).",
        "The Puppy Dog Close: Ofrecer una prueba sin compromiso.",
        "The Ben Franklin Close: Listar pros y contras, asegurando que los pros ganen por mucho.",
    ],
    "psychology": [
        "Social Proof: Mostrar que otros ya están obteniendo resultados.",
        "Reciprocity: Dar valor gratuito antes de pedir la venta.",
        "Authority: Posicionar a ARIA como la experta indiscutible en el nicho.",
        "Commitment & Consistency: Lograr pequeños 'sí' antes del gran 'sí'.",
    ],
    "copywriting": [
        "AIDA: Attention, Interest, Desire, Action.",
        "PAS: Problem, Agitation, Solution.",
        "Before-After-Bridge: Mostrar el estado actual, el deseado y cómo el producto es el puente.",
        "The 4 P's: Promise, Picture, Proof, Push.",
    ],
    "follow_up": [
        "The 3-Day Rule: Primer seguimiento a los 3 días si no hay respuesta.",
        "Value-First Follow-up: Enviar un recurso útil en lugar de solo preguntar '¿viste mi mensaje?'.",
        "The 'Break-up' Email: Un último mensaje educado indicando que dejaremos de insistir (genera urgencia).",
    ]
}

MARKETING_STRATEGY = {
    "content_pillars": [
        "Educational: Enseñar cómo resolver un problema específico.",
        "Inspirational: Casos de éxito y transformaciones.",
        "Promotional: Ofertas directas y beneficios del producto.",
        "Engagement: Preguntas y encuestas para conocer a la audiencia.",
    ],
    "distribution_channels": {
        "organic": ["SEO Blogs", "X (Twitter) Threads", "LinkedIn Articles", "Reddit Communities"],
        "paid": ["Meta Ads", "Google Search", "TikTok Spark Ads"],
        "direct": ["Email Newsletters", "Telegram Channel", "Direct Outreach"],
    }
}

VOCABULARY_EXPANSION = {
    "persuasive_verbs": [
        "Acelerar", "Desbloquear", "Dominar", "Escalar", "Transformar", "Maximizar", 
        "Automatizar", "Conquistar", "Simplificar", "Potenciar"
    ],
    "emotional_triggers": [
        "Exclusivo", "Instantáneo", "Garantizado", "Revelado", "Limitado", 
        "Secreto", "Probado", "Poderoso", "Esencial", "Lucrativo"
    ],
    "business_terms": [
        "ROI (Retorno de Inversión)", "LTV (Lifetime Value)", "CAC (Costo de Adquisición)", 
        "Churn Rate", "Conversion Rate Optimization (CRO)", "Scalability", "Synergy"
    ]
}

def get_sales_advice(category: str = "closing") -> list[str]:
    return SALES_TECHNIQUES.get(category, [])

def get_marketing_strategy() -> dict:
    return MARKETING_STRATEGY

def get_vocab() -> dict:
    return VOCABULARY_EXPANSION
