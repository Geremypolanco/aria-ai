"""
copywriting_engine.py — Motor de Copywriting Completo para ARIA AI.

Genera copy que vende para cualquier formato:
  - Emails de venta (cold, warm, nurture, launch)
  - Páginas de venta (VSL, long-form, short-form)
  - Anuncios (Facebook/Instagram/TikTok/Google)
  - Posts de redes sociales que convierten
  - Descripciones de productos (Gumroad, Shopify)
  - Secuencias de email (welcome, onboarding, sales, winback)
  - Bio y headlines de perfil
  - Scripts de vídeo (hook + retención + CTA)

Fuentes: Gary Halbert, Eugene Schwartz, David Ogilvy, Dan Kennedy,
         Claude Hopkins, Joseph Sugarman, Frank Kern, Todd Brown.
"""
from __future__ import annotations

import logging
import random
from typing import Any, Optional

logger = logging.getLogger("aria.copywriting")


# ─────────────────────────────────────────────────────────────────
# HOOKS UNIVERSALES — Lo más crítico en marketing digital
# Los primeros 3 segundos deciden si alguien lee/ve/compra
# ─────────────────────────────────────────────────────────────────

HOOKS_BY_FORMAT = {
    "tiktok_reel": [
        "Esto que voy a decirte le tomó a la gente años descubrir...",
        "El error que comete el 90% de {nicho} (y cómo evitarlo)",
        "Nadie habla de esto porque no les conviene que lo sepas.",
        "Hice {resultado} en {tiempo}. Aquí exactamente cómo.",
        "Para de {acción_mala}. Empieza a hacer esto.",
        "Si tienes {problema}, este video es para ti.",
        "La diferencia entre los que {logran} y los que no.",
        "Me tomó {tiempo} aprender esto. Tú lo sabrás en 60 segundos.",
        "Secreto de los que ganan más dinero en {nicho}: {insight}",
        "{resultado_impresionante}? Sí, es posible. Aquí el método.",
    ],
    "email_subject": [
        "[Urgente] {nombre}, tu oportunidad cierra mañana",
        "¿Por qué tu {competidor} te está ganando? (y cómo revertirlo)",
        "El método de {persona_famosa} que nadie te enseñó",
        "Respuesta a tu pregunta sobre {tema}",
        "{nombre}: hice algo especial para ti",
        "Cometí un error y quiero que te beneficies de eso",
        "La verdad sobre {tema popular en nicho}",
        "{número} personas ya lo tienen. ¿Tú?",
        "Cierra esto si no quieres {resultado_deseado}",
        "Advertencia: esto podría cambiar la forma en que ves {tema}",
    ],
    "landing_headline": [
        "Cómo {resultado_deseado} sin {sacrificio_típico}",
        "El sistema de {X pasos} para {resultado} que usan los expertos",
        "Finalmente: {solución} que funciona para {audiencia} en {tiempo}",
        "Deja de {acción_mala}. Esto funciona mejor.",
        "Atención {audiencia}: {promesa_concreta_y_creíble}",
        "¿Cuánto tiempo más vas a perder en {problema}?",
        "{resultado_impresionante} en {tiempo}: la guía honesta",
        "El único {producto/sistema} que {garantía_específica}",
    ],
    "facebook_ad": [
        "Alerta para {audiencia}: {problema_urgente}",
        "¿Cuánto te está costando {problema} cada mes?",
        "Esto funciona incluso si {objeción_común}",
        "Hice {resultado} partiendo de cero. Sin {requisito_intimidante}.",
        "{testimonio_corto_impactante} — ¿quieres el mismo resultado?",
    ],
    "twitter_post": [
        "Thread: cómo {resultado_impresionante} en {tiempo} 🧵",
        "Unpopular opinion: {afirmación_contraintuitiva}",
        "Hace {tiempo} era {situación_inicial}. Hoy {situación_actual}. Esto cambió todo:",
        "El único consejo de {tema} que necesitas:",
        "Nadie te dice esto sobre {tema}:",
    ],
}

# ─────────────────────────────────────────────────────────────────
# SECUENCIAS DE EMAIL — LAS 5 QUE TODO NEGOCIO NECESITA
# ─────────────────────────────────────────────────────────────────

EMAIL_SEQUENCES = {
    "welcome_sequence": {
        "purpose": "Convertir suscriptor nuevo en comprador en 7 días",
        "emails": [
            {
                "day": 0,
                "subject": "Bienvenido a [NOMBRE_MARCA] — aquí está tu regalo",
                "hook": "Hola {nombre}, gracias por unirte.",
                "body": (
                    "Hay UNA cosa que separa a los que logran {resultado_deseado} "
                    "de los que lo intentan por años sin lograrlo...\n\n"
                    "Es tener el sistema correcto.\n\n"
                    "Durante los próximos días te voy a compartir exactamente lo que funciona "
                    "— sin rodeos, sin teoría vacía.\n\n"
                    "Primero: aquí está lo que prometí:\n{lead_magnet_link}\n\n"
                    "Mañana te cuento el error #1 que comete {audiencia} "
                    "(y por qué te está costando {costo_del_error})."
                ),
                "cta": "Descarga tu [RECURSO] aquí",
            },
            {
                "day": 1,
                "subject": "El error que cometí (y que probablemente tú también)",
                "hook": "Voy a ser honesto contigo.",
                "body": (
                    "Cuando empecé en {nicho}, cometí el mismo error que comete el 90%:\n"
                    "{error_común}.\n\n"
                    "Me costó {precio_del_error} y {tiempo_perdido}.\n\n"
                    "No quiero que tú pagues ese mismo precio.\n\n"
                    "Por eso mañana te voy a mostrar exactamente qué hacer en su lugar."
                ),
                "cta": "Responde este email con tu mayor frustración en {nicho}",
            },
            {
                "day": 2,
                "subject": "Cómo {resultado_específico} (caso real)",
                "hook": "Historia rápida:",
                "body": (
                    "{nombre_cliente} llegó a mí con exactamente el mismo problema que tú tienes.\n\n"
                    "{descripción_problema_en_sus_palabras}.\n\n"
                    "En {tiempo}, usando {método/producto}, logró {resultado_específico}.\n\n"
                    "¿Qué hizo diferente? {insight_clave}.\n\n"
                    "Mañana te cuento exactamente cómo replicar esto."
                ),
                "cta": "Ver el caso completo →",
            },
            {
                "day": 4,
                "subject": "Tengo algo para ti (oferta de bienvenida)",
                "hook": "Quiero ayudarte a {resultado_deseado} más rápido.",
                "body": (
                    "Esta semana solamente, tengo disponible {producto} por {precio_especial} "
                    "(normalmente {precio_normal}).\n\n"
                    "Esto incluye:\n"
                    "✓ {beneficio_1}\n"
                    "✓ {beneficio_2}\n"
                    "✓ {beneficio_3}\n"
                    "✓ Garantía de {garantía}\n\n"
                    "Esta oferta cierra el {fecha}."
                ),
                "cta": "Sí, quiero {producto} por {precio_especial} →",
            },
            {
                "day": 6,
                "subject": "Último aviso — oferta cierra en 24h",
                "hook": "Solo un recordatorio rápido.",
                "body": (
                    "La oferta especial de bienvenida cierra mañana a medianoche.\n\n"
                    "Después de eso, {producto} vuelve a su precio regular de {precio_normal}.\n\n"
                    "Si estás en la valla, permíteme responderte esto:\n"
                    "¿Cuánto tiempo más vas a convivir con {problema}?\n\n"
                    "Cada día que pasa es {costo_de_no_actuar}.\n\n"
                    "La garantía de {garantía} elimina todo el riesgo de tu lado."
                ),
                "cta": "Quiero {resultado_deseado} — entrar ahora →",
            },
        ],
    },

    "nurture_sequence": {
        "purpose": "Mantener audiencia caliente con valor + venta suave",
        "frequency": "2x por semana",
        "email_types": [
            "Caso de estudio con resultado real",
            "Tutorial/tip accionable (sin vender)",
            "Herramienta o recurso gratuito",
            "Historia personal con lección de negocio",
            "Curación: los mejores recursos de la semana",
            "Q&A: responder pregunta de suscriptor",
            "Desmitificación: mito común del nicho vs realidad",
        ],
    },

    "launch_sequence": {
        "purpose": "Lanzamiento de producto en 10 días — máximas ventas",
        "structure": {
            "pre_launch_days": "D-7 a D-4: crear anticipación y calificar audiencia",
            "cart_open": "D-3 a D-2: apertura con oferta especial de early bird",
            "middle": "D-1: testimonio real + FAQ + objeciones",
            "close": "D0: 3 emails — 12h, 3h, 1h antes del cierre",
        },
        "close_day_subjects": [
            "[12h] La oferta cierra esta noche a medianoche",
            "[3h] {nombre}, ¿nos acompañas?",
            "[ÚLTIMAS HORAS] El precio sube en 60 minutos",
        ],
    },

    "winback_sequence": {
        "purpose": "Reactivar suscriptores inactivos > 60 días",
        "emails": [
            {
                "subject": "¿Sigues ahí, {nombre}?",
                "body": "Han pasado un tiempo. Quiero asegurarme de que sigues recibiendo valor de nosotros.",
                "cta": "Sí, sigo interesado — confirmar →",
            },
            {
                "subject": "Antes de decirte adiós...",
                "body": (
                    "Si no escucho de ti en 48h, te eliminaré de la lista. "
                    "No porque no me importes — sino porque no quiero molestarte "
                    "si {tema} ya no es tu prioridad.\n\n"
                    "Pero si sigues aquí, tengo algo nuevo que podría interesarte:"
                ),
                "cta": "¡Sigo aquí! Muéstrame lo nuevo →",
            },
        ],
    },

    "abandoned_cart": {
        "purpose": "Recuperar ventas perdidas — recupera 10-15% de carritos",
        "emails": [
            {
                "delay": "1h",
                "subject": "{nombre}, olvidaste algo en tu carrito",
                "body": "Vi que estuviste a punto de {resultado_del_producto}. ¿Algo te detuvo?",
            },
            {
                "delay": "24h",
                "subject": "Tu {producto} todavía te espera (+ respuesta a tus dudas)",
                "body": "Quizás tenías preguntas. Aquí las respondo todas:",
            },
            {
                "delay": "72h",
                "subject": "Última oportunidad — tu carrito expira hoy",
                "body": "Solo estoy haciendo esto disponible hasta medianoche de hoy.",
            },
        ],
    },
}


# ─────────────────────────────────────────────────────────────────
# GENERADORES DE COPY POR FORMATO
# ─────────────────────────────────────────────────────────────────

class SalesPageWriter:
    """Genera páginas de venta completas — long-form y short-form."""

    @staticmethod
    def write_long_form_sales_page(
        product: str,
        audience: str,
        pain: str,
        solution: str,
        benefits: list[str],
        price: str,
        guarantee: str,
        testimonials: list[str] = [],
        bonuses: list[str] = [],
    ) -> dict:
        """Genera una página de venta larga al estilo copywriting clásico."""
        headline = f"Cómo {solution} sin {pain} — garantizado en {price}"

        subheadline = (
            f"El sistema exacto que {audience} usa para {solution} "
            f"en tiempo récord, incluso si {pain} has sido tu mayor obstáculo."
        )

        lead_paragraph = (
            f"Si eres {audience} y llevas tiempo luchando con {pain}, "
            f"quiero que leas cada palabra de esta página — "
            f"porque lo que voy a mostrarte podría cambiar tu situación completamente."
        )

        benefits_section = "Lo que vas a lograr:\n" + "\n".join(
            f"✓ {b}" for b in benefits
        )

        social_proof = ""
        if testimonials:
            social_proof = "Esto es lo que dicen quienes ya lo usan:\n\n" + "\n\n".join(
                f'"{t}"' for t in testimonials
            )

        offer_section = (
            f"¿Qué incluye {product}?\n\n"
            + benefits_section
            + ("\n\nBONUS ESPECIALES:\n" + "\n".join(f"🎁 {b}" for b in bonuses) if bonuses else "")
            + f"\n\nTodo esto por solo: {price}"
        )

        guarantee_section = (
            f"GARANTÍA TOTAL: {guarantee}\n\n"
            f"Pon {product} a prueba durante {guarantee}. "
            f"Si no ves resultados, te devuelvo cada centavo — sin preguntas, sin demoras."
        )

        cta_section = (
            f"Sí, quiero {solution} →\n"
            f"[BOTÓN: Obtener {product} por {price}]\n\n"
            f"Esta oferta es temporal y puede cambiar en cualquier momento."
        )

        faq_section = (
            "Preguntas frecuentes:\n\n"
            f"¿Funciona si soy principiante en {audience}? Sí, está diseñado para eso.\n\n"
            f"¿Cuándo veo resultados? La mayoría ve primeros resultados en 7-14 días.\n\n"
            f"¿Hay garantía? Sí: {guarantee}.\n\n"
            f"¿Qué pasa si no funciona para mí? Te devolvemos el dinero, sin preguntas."
        )

        return {
            "type": "long_form_sales_page",
            "headline": headline,
            "subheadline": subheadline,
            "lead": lead_paragraph,
            "benefits": benefits_section,
            "social_proof": social_proof,
            "offer": offer_section,
            "guarantee": guarantee_section,
            "cta": cta_section,
            "faq": faq_section,
            "full_page": "\n\n".join(filter(bool, [
                headline, subheadline, lead_paragraph,
                benefits_section, social_proof, offer_section,
                guarantee_section, cta_section, faq_section
            ])),
        }

    @staticmethod
    def write_vsl_script(
        product: str,
        audience: str,
        pain: str,
        insight: str,
        solution: str,
        price: str,
        duration_minutes: int = 15,
    ) -> dict:
        """Genera script para Video Sales Letter (VSL)."""
        return {
            "type": "VSL_script",
            "duration": f"~{duration_minutes} minutos",
            "sections": {
                "hook_0_30s": (
                    f"Si eres {audience} y sigues lidiando con {pain}, "
                    f"para el video — porque en los próximos {duration_minutes} minutos "
                    f"voy a mostrarte algo que va a cambiar eso completamente."
                ),
                "pain_amplification_1_3min": (
                    f"Sé exactamente cómo te sientes. "
                    f"Llevas tiempo intentando resolver {pain} "
                    f"y parece que nada funciona. "
                    f"No es tu culpa — el problema es que nadie te ha dado el sistema correcto."
                ),
                "insight_and_reframe_3_6min": (
                    f"Aquí está lo que descubrí después de {insight}: "
                    f"el problema no es {pain} en sí. "
                    f"El problema es que {insight}. "
                    f"Cuando entendí eso, todo cambió."
                ),
                "solution_presentation_6_10min": (
                    f"Por eso creé {product}. "
                    f"Es {solution}. "
                    f"No requiere {obstáculo_típico}. "
                    f"Solo requiere seguir el sistema."
                ),
                "social_proof_10_12min": (
                    "[Testimonio 1: resultado específico]\n"
                    "[Testimonio 2: resultado específico]\n"
                    "[Testimonio 3: resultado específico]"
                ),
                "offer_stack_12_14min": (
                    f"Aquí está todo lo que obtienes:\n"
                    f"→ {product} (valor: $XXX)\n"
                    f"→ Bonus 1 (valor: $XX)\n"
                    f"→ Bonus 2 (valor: $XX)\n"
                    f"Todo por {price} — una sola vez."
                ),
                "close_and_cta_14_15min": (
                    f"Tienes dos opciones: seguir haciendo lo mismo y obtener los mismos resultados, "
                    f"o hacer clic abajo y empezar a {solution} hoy. "
                    f"La garantía elimina todo el riesgo. "
                    f"Haz clic ahora."
                ),
            },
        }


class SocialMediaCopywriter:
    """Genera copy para redes sociales que genera ventas."""

    @staticmethod
    def write_instagram_carousel(
        topic: str,
        insight: str,
        steps: list[str],
        cta: str,
    ) -> list[dict]:
        """Genera slides para carrusel de Instagram."""
        slides = [
            {"slide": 1, "type": "hook", "text": f"{topic}\n(Guarda esto — lo vas a necesitar)"},
            {"slide": 2, "type": "problem", "text": f"El 90% de la gente hace {topic} mal.\nAsí es como lo hacen:"},
        ]
        for i, step in enumerate(steps, 3):
            slides.append({"slide": i, "type": "step", "text": f"Paso {i-2}: {step}"})
        slides.append({"slide": len(slides)+1, "type": "cta", "text": cta})
        return slides

    @staticmethod
    def write_linkedin_post(
        hook: str,
        story_or_insight: str,
        lesson: str,
        cta: str,
    ) -> str:
        return (
            f"{hook}\n\n"
            f"{story_or_insight}\n\n"
            f"La lección:\n{lesson}\n\n"
            f"---\n{cta}"
        )

    @staticmethod
    def write_twitter_thread(
        hook: str,
        points: list[str],
        conclusion: str,
        cta: str,
    ) -> list[str]:
        tweets = [f"🧵 {hook}\n\n(Thread)"]
        for i, point in enumerate(points, 1):
            tweets.append(f"{i}/ {point}")
        tweets.append(f"Conclusión:\n{conclusion}")
        tweets.append(f"---\n{cta}\n\n(RT si fue útil 🔁)")
        return tweets


class AdCopywriter:
    """Genera anuncios pagados para Facebook, Instagram, TikTok, Google."""

    @staticmethod
    def write_facebook_ad(
        audience: str,
        pain: str,
        solution: str,
        cta: str,
        ad_format: str = "single_image",
    ) -> dict:
        """Genera copy completo para anuncio de Facebook/Instagram."""
        headline = f"¿Cansado de {pain}? Existe una solución."
        primary_text = (
            f"Atención {audience}:\n\n"
            f"Si {pain} es tu mayor obstáculo ahora mismo, "
            f"esto fue diseñado específicamente para ti.\n\n"
            f"{solution}.\n\n"
            f"Sin {pain}. Sin {obstáculo_típico}.\n\n"
            f"Solo resultados — con garantía total."
        ).replace("{obstáculo_típico}", "excusas")
        description = f"{solution} — disponible por tiempo limitado."
        return {
            "format": ad_format,
            "headline": headline,
            "primary_text": primary_text,
            "description": description,
            "cta_button": cta,
            "audience_note": f"Target: {audience} — intereses relacionados con {pain}",
        }

    @staticmethod
    def write_google_ad(
        keyword: str,
        benefit: str,
        cta: str,
    ) -> dict:
        """Genera anuncio de Google Ads con RSA."""
        return {
            "type": "RSA (Responsive Search Ad)",
            "headlines": [
                f"{benefit} — Empieza Hoy",
                f"Resuelve {keyword} Definitivamente",
                f"La Solución #1 para {keyword}",
                f"Garantizado: {benefit}",
                f"Obtén {benefit} Ahora",
            ],
            "descriptions": [
                f"Solución probada para {keyword}. Garantía de satisfacción. Sin riesgos.",
                f"{benefit} en tiempo récord. Miles de clientes satisfechos. {cta}.",
            ],
            "cta": cta,
        }


class ProductDescriptionWriter:
    """Genera descripciones de productos digitales para Gumroad, Shopify, etc."""

    @staticmethod
    def write_gumroad_listing(
        product_name: str,
        audience: str,
        pain: str,
        what_is_it: str,
        benefits: list[str],
        price: str,
        what_inside: list[str],
        guarantee: str = "30 días",
    ) -> dict:
        description = (
            f"## ¿Para quién es {product_name}?\n\n"
            f"Para {audience} que están cansados de {pain} "
            f"y quieren {benefits[0] if benefits else 'resultados reales'}.\n\n"
            f"## ¿Qué es exactamente?\n\n"
            f"{what_is_it}\n\n"
            f"## ¿Qué lograrás?\n\n"
            + "\n".join(f"✓ {b}" for b in benefits)
            + f"\n\n## ¿Qué incluye?\n\n"
            + "\n".join(f"📁 {w}" for w in what_inside)
            + f"\n\n## Garantía\n\n"
            f"Si en {guarantee} no estás satisfecho, te devuelvo el {price} completo. Sin preguntas.\n\n"
            f"---\n\n*Acceso inmediato después del pago. Descarga instantánea.*"
        )
        return {
            "product_name": product_name,
            "price_suggestion": price,
            "gumroad_description": description,
            "short_pitch": f"{product_name}: {benefits[0] if benefits else 'resultados reales'} — {price}",
        }


# ─────────────────────────────────────────────────────────────────
# MOTOR PRINCIPAL
# ─────────────────────────────────────────────────────────────────

class CopywritingEngine:
    """Motor unificado de copywriting para ARIA AI."""

    def __init__(self):
        self.sales_page = SalesPageWriter()
        self.social = SocialMediaCopywriter()
        self.ads = AdCopywriter()
        self.products = ProductDescriptionWriter()

    def get_hooks(self, format: str, n: int = 5) -> list[str]:
        hooks = HOOKS_BY_FORMAT.get(format, [])
        return random.sample(hooks, min(n, len(hooks)))

    def get_email_sequence(self, sequence_type: str) -> dict:
        return EMAIL_SEQUENCES.get(sequence_type, {})

    def list_sequences(self) -> list[str]:
        return list(EMAIL_SEQUENCES.keys())

    def write_welcome_email(self, brand: str, lead_magnet: str, audience: str, benefit: str) -> dict:
        seq = EMAIL_SEQUENCES["welcome_sequence"]
        email = seq["emails"][0].copy()
        email["body"] = email["body"].replace("{resultado_deseado}", benefit).replace("{audiencia}", audience)
        email["subject"] = email["subject"].replace("[NOMBRE_MARCA]", brand)
        return email

    def write_product_launch_email(self, product: str, price: str, benefits: list[str],
                                    urgency: str = "48 horas") -> str:
        return (
            f"🚀 {product} ya está disponible\n\n"
            f"Lo que obtienes:\n"
            + "\n".join(f"✓ {b}" for b in benefits[:5])
            + f"\n\nPrecio especial de lanzamiento: {price}\n"
            f"Esta oferta cierra en {urgency}.\n\n"
            f"[Obtener acceso ahora →]"
        )

    def generate_ad_set(self, product: str, audience: str, pain: str, solution: str, price: str) -> dict:
        return {
            "facebook": self.ads.write_facebook_ad(audience, pain, solution, f"Obtener {product}"),
            "google": self.ads.write_google_ad(pain, solution, f"Empieza hoy — {price}"),
            "instagram_carousel": self.social.write_instagram_carousel(
                topic=pain,
                insight=solution,
                steps=[f"Paso {i}" for i in range(1, 4)],
                cta=f"Consigue {product} en el link de la bio →",
            ),
        }

    def write_gumroad_product(self, name: str, audience: str, pain: str,
                              what_is: str, benefits: list[str], price: str,
                              contents: list[str]) -> dict:
        return self.products.write_gumroad_listing(
            name, audience, pain, what_is, benefits, price, contents
        )
