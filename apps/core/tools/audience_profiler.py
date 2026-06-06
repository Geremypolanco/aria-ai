"""
audience_profiler.py — Motor de Perfilado de Audiencia para ARIA AI.

Construye Ideal Customer Profiles (ICP) y buyer personas con datos reales:
  - Demographics + Psychographics + Behavioral data
  - Jobs-to-be-done (JTBD) framework
  - Pain points jerarquizados por intensidad
  - Canales de distribución óptimos por perfil
  - Mensajes que resuenan por segmento
  - Gatillos de compra y objeciones anticipadas

Basado en: Buyer Persona Institute, Tony Zambito JTBD, April Dunford Positioning.
"""
from __future__ import annotations
import logging
from typing import Any, Optional
logger = logging.getLogger("aria.audience")

BUYER_PERSONAS = {
    "digital_entrepreneur_latam": {
        "name": "El Emprendedor Digital Latinoamericano",
        "age_range": "25-40",
        "income": "$500-$3000/mes (en crecimiento)",
        "location": "México, Colombia, Argentina, España, EEUU (hispano)",
        "education": "Universidad incompleta o completa, muchos autodidactas",
        "goals": [
            "Generar ingresos online sin depender de un jefe",
            "Trabajar desde casa o viajando",
            "Lograr $3000-$10000/mes para vivir con libertad",
            "Construir un negocio escalable que funcione sin él",
        ],
        "pains": [
            "No sabe cómo conseguir clientes constantemente",
            "Invierte en cursos pero no aplica lo que aprende",
            "Miedo a fracasar y al qué dirán",
            "No tiene capital para publicidad",
            "Se distrae con demasiadas estrategias a la vez",
        ],
        "jtbd": "Ayúdame a ganar mi primer $1000 online de forma que pueda repetirlo",
        "buying_triggers": [
            "Ver casos de éxito de personas similares a él",
            "Oferta con garantía de devolución",
            "Precio accesible ($17-$97)",
            "Resultado específico y medible prometido",
            "Comunidad activa incluida",
        ],
        "objections": [
            "Ya compré muchos cursos y no funcionaron",
            "No tengo tiempo ahora",
            "¿Funciona para mi nicho específico?",
            "El precio es alto para mí",
        ],
        "best_channels": ["Instagram", "TikTok", "YouTube", "WhatsApp", "Telegram"],
        "content_that_converts": [
            "Casos de éxito con números reales",
            "Tutoriales paso a paso muy específicos",
            "Contenido que desmitifica mitos del emprendimiento",
            "Comparaciones antes/después",
        ],
        "tone": "Motivador, honesto, cercano, sin promesas exageradas",
        "worst_messaging": "Hazte rico rápido, pasivo income fácil, sin esfuerzo",
    },
    "freelancer_tech": {
        "name": "El Freelancer Tech",
        "age_range": "22-35",
        "income": "$1000-$5000/mes (irregular)",
        "location": "Global, trabajo remoto",
        "education": "Autodidacta o bootcamp, a veces universitario",
        "goals": [
            "Ingresos predecibles y estables",
            "Clientes de largo plazo que paguen bien",
            "Trabajar menos horas por más dinero",
            "Subir sus precios sin perder clientes",
        ],
        "pains": [
            "Ingresos irregulares — mucho un mes, nada al siguiente",
            "Clientes que regatean y no pagan a tiempo",
            "No sabe cómo conseguir proyectos de mayor valor",
            "Agotamiento por trabajar demasiado por poco dinero",
            "No sabe cómo posicionarse como experto",
        ],
        "jtbd": "Ayúdame a tener clientes consistentes que paguen lo que valgo",
        "buying_triggers": [
            "Plantillas y sistemas listos para usar (resultado inmediato)",
            "Scripts de ventas probados",
            "Precio bajo con alto valor percibido ($27-$97)",
            "Recomendación de peer o colega",
        ],
        "objections": [
            "Puedo hacerlo yo mismo",
            "Ya lo intenté y no funcionó",
            "¿Cómo sé que es diferente a lo que ya tengo?",
        ],
        "best_channels": ["Twitter/X", "LinkedIn", "Hacker News", "Discord", "Reddit"],
        "content_that_converts": [
            "Threads de Twitter con tips accionables",
            "Posts de LinkedIn sobre lecciones de negocio",
            "Herramientas y recursos gratuitos",
            "Comparaciones de precios y estrategias de pricing",
        ],
        "tone": "Directo, técnico pero accesible, sin hype",
        "worst_messaging": "Vende en automático mientras duermes",
    },
    "small_business_owner": {
        "name": "El Dueño de Negocio Local/Online",
        "age_range": "30-55",
        "income": "$2000-$15000/mes (negocio establecido)",
        "location": "Latinoamérica y EEUU hispano",
        "education": "Variada, muchos sin educación formal en marketing digital",
        "goals": [
            "Más clientes sin depender de referidos solamente",
            "Entender el marketing digital sin ser técnico",
            "Automatizar partes del negocio para escalar",
            "Reducir dependencia de empleados clave",
        ],
        "pains": [
            "No sabe cómo usar las redes sociales para el negocio",
            "Ha pagado agencias y no vio resultados",
            "Sus clientes son irregulares y no sabe cómo fidelizarlos",
            "No tiene tiempo para aprender marketing",
        ],
        "jtbd": "Ayúdame a conseguir más clientes predecibles sin aprenderme todo el marketing digital",
        "buying_triggers": [
            "Demostración clara de ROI",
            "Caso de negocio similar al suyo",
            "Setup hecho para él (llave en mano)",
            "Soporte incluido",
        ],
        "objections": [
            "No tengo tiempo para aprenderlo",
            "Ya tengo Facebook pero no me funciona",
            "Eso funciona para otros negocios, no el mío",
            "Mi clientela no está en internet",
        ],
        "best_channels": ["Facebook", "WhatsApp Business", "Email", "Referidos"],
        "content_that_converts": [
            "Casos de negocios locales similares",
            "Tutoriales con resultados en tiempo corto",
            "Guías 'para no técnicos'",
        ],
        "tone": "Confiable, simple, sin jerga técnica, orientado a resultados",
        "worst_messaging": "Disruption, growth hacking, escala exponencial",
    },
    "content_creator": {
        "name": "El Creador de Contenido",
        "age_range": "18-35",
        "income": "$0-$3000/mes (en construcción)",
        "location": "Global, español como idioma principal",
        "education": "Universitario o autodidacta",
        "goals": [
            "Monetizar su audiencia sin vender constantemente",
            "Llegar a $3000/mes con contenido",
            "Construir una marca personal reconocida",
            "Lanzar su primer producto digital propio",
        ],
        "pains": [
            "Tiene seguidores pero no genera ingresos",
            "No sabe cómo monetizar sin perder autenticidad",
            "El algoritmo le cambia las reglas constantemente",
            "No sabe qué producto crear ni a qué precio",
        ],
        "jtbd": "Ayúdame a ganar dinero con mi audiencia sin convertirme en un vendedor",
        "buying_triggers": [
            "Ver creadores similares con ingresos reales",
            "Precio accesible para empezar ($17-$47)",
            "Resultado rápido y visible",
            "Comunidad de creadores incluida",
        ],
        "objections": [
            "Mi audiencia es pequeña todavía",
            "No sé qué producto crear",
            "Tengo miedo de perder seguidores si vendo algo",
        ],
        "best_channels": ["Instagram", "TikTok", "YouTube", "Twitter/X", "Substack"],
        "content_that_converts": [
            "Income reports (cuánto gané este mes)",
            "Behind the scenes de cómo se crea un producto",
            "Comparativas de plataformas de monetización",
        ],
        "tone": "Auténtico, transparente, inspirador pero realista",
        "worst_messaging": "Hazte influencer millonario, escala sin límites",
    },
}

class AudienceProfiler:
    """Motor de perfilado de audiencia para ARIA AI."""

    def get_persona(self, persona_key: str) -> dict:
        return BUYER_PERSONAS.get(persona_key, {})

    def get_all_personas(self) -> dict:
        return BUYER_PERSONAS

    def get_best_persona_for_product(self, product_keywords: list[str]) -> list[dict]:
        results = []
        for key, persona in BUYER_PERSONAS.items():
            score = 0
            all_text = " ".join([
                " ".join(persona.get("goals", [])),
                " ".join(persona.get("pains", [])),
                persona.get("jtbd", ""),
            ]).lower()
            for kw in product_keywords:
                if kw.lower() in all_text:
                    score += 1
            if score > 0:
                results.append({"key": key, "persona": persona, "relevance_score": score})
        return sorted(results, key=lambda x: x["relevance_score"], reverse=True)

    def get_messaging_guide(self, persona_key: str, product: str) -> dict:
        persona = BUYER_PERSONAS.get(persona_key, {})
        if not persona:
            return {"error": f"Persona '{persona_key}' no encontrada"}
        return {
            "persona": persona["name"],
            "product": product,
            "headline_angle": f"Para {persona['name']}: {product} que resuelve {persona['pains'][0] if persona.get('pains') else 'tus mayores obstáculos'}",
            "email_opening": f"Sé exactamente lo que estás viviendo. {persona['pains'][0] if persona.get('pains') else ''}.",
            "main_benefit": persona.get("jtbd", ""),
            "key_objections_to_address": persona.get("objections", [])[:3],
            "best_channels": persona.get("best_channels", []),
            "tone_guide": persona.get("tone", ""),
            "avoid": persona.get("worst_messaging", ""),
            "buying_triggers": persona.get("buying_triggers", []),
        }

    def build_icp(self, answers: dict) -> dict:
        """
        Construye un ICP personalizado basado en respuestas del propietario.
        answers: {industry, best_customer_description, why_they_buy, avg_value, channel}
        """
        return {
            "icp_summary": (
                f"Tu cliente ideal es alguien en {answers.get('industry', 'tu industria')} "
                f"que {answers.get('best_customer_description', 'tiene el problema que resuelves')}. "
                f"Compran porque {answers.get('why_they_buy', 'necesitan tu solución')}. "
                f"Valor promedio: ${answers.get('avg_value', 'por definir')}. "
                f"Los encuentras en: {answers.get('channel', 'tus canales actuales')}."
            ),
            "focus_message": f"Habla directamente a {answers.get('best_customer_description', 'tu cliente ideal')}",
            "avoid_message": "No trates de venderle a todos — la especificidad convierte",
            "next_action": "Crea 1 pieza de contenido que hable directamente a este perfil hoy",
        }
