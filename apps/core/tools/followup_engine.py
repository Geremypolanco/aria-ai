"""
followup_engine.py — Motor de Follow-up Automatizado para ARIA AI.

La fortuna está en el follow-up. El 80% de ventas requieren 5+ contactos.
El 44% de vendedores se rinde después del primer no.

Este módulo gestiona:
  - Secuencias de follow-up multicanal (email + Telegram)
  - Timing óptimo basado en datos (cuándo y con qué frecuencia)
  - Personalización por comportamiento (abrió email, no respondió, etc.)
  - Score de lead (priorizar quién está más listo para comprar)
  - Registro en Supabase de todas las interacciones

Principio: Persistencia inteligente, no spam. Valor en cada toque.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.followup")


# ─────────────────────────────────────────────────────────────────
# DATOS Y CONSTANTES
# ─────────────────────────────────────────────────────────────────

# Timing óptimo de follow-up (basado en investigación de Yesware, HubSpot, Salesforce)
FOLLOWUP_TIMING = {
    "cold_outreach": [1, 3, 7, 14, 21],        # días desde primer contacto
    "warm_lead": [1, 2, 5, 10],
    "hot_lead": [0.5, 1, 2, 4],                # horas o días según urgencia
    "post_purchase": [0, 3, 7, 30, 90],        # días post-compra (onboarding + upsell)
    "abandoned_cart": [1, 24, 72],             # horas
    "webinar_no_show": [2, 24, 72],            # horas post-webinar
    "content_download": [0, 3, 7],             # días post-descarga
}

# Mejores horas para enviar emails (hora local del destinatario)
BEST_SEND_HOURS = [9, 10, 14, 15, 16]  # Martes-Jueves son los mejores días

# Templates de follow-up por situación
FOLLOWUP_TEMPLATES = {
    "no_response_1": {
        "subject": "¿Llegó mi último mensaje, {nombre}?",
        "body": (
            "Hola {nombre},\n\n"
            "Solo quería asegurarme de que mi email anterior llegó bien.\n\n"
            "Entiendo que estás ocupado — pero creo que {beneficio} podría ser "
            "exactamente lo que necesitas ahora mismo.\n\n"
            "¿Tienes 5 minutos esta semana para conversar?\n\n"
            "{firma}"
        ),
    },
    "no_response_2": {
        "subject": "Re: {tema_anterior}",
        "body": (
            "Hola {nombre},\n\n"
            "Sé que tienes mucho en el plato, así que seré directo:\n\n"
            "{dolor_específico} es un problema que podemos resolver. "
            "Y lo hacemos en {tiempo}.\n\n"
            "¿Quieres que te muestre exactamente cómo?\n\n"
            "{firma}"
        ),
    },
    "breakup_email": {
        "subject": "¿Sigo molestando, {nombre}?",
        "body": (
            "Hola {nombre},\n\n"
            "Entiendo perfectamente si {tema} ya no es una prioridad — "
            "o simplemente no es el momento.\n\n"
            "No voy a molestarte más después de este email.\n\n"
            "Pero si en algún momento {dolor} vuelve a ser urgente, "
            "sabes dónde encontrarme.\n\n"
            "Te deseo mucho éxito de todas formas.\n\n"
            "{firma}\n\n"
            "P.D: Si hay algo en lo que podría mejorar mi propuesta, "
            "tu feedback sería valioso para mí."
        ),
    },
    "value_add": {
        "subject": "Encontré algo que puede ayudarte con {tema}",
        "body": (
            "Hola {nombre},\n\n"
            "Pensé en ti cuando vi esto:\n\n"
            "{recurso_valioso}\n\n"
            "Espero que te sea útil — sin compromisos.\n\n"
            "Ah, y si en algún momento quieres explorar cómo {solución}, "
            "estoy aquí.\n\n"
            "{firma}"
        ),
    },
    "case_study": {
        "subject": "Cómo {nombre_cliente} logró {resultado} (caso real)",
        "body": (
            "Hola {nombre},\n\n"
            "Una historia rápida que creo te va a interesar:\n\n"
            "{nombre_cliente}, que también era {descripción_similar_al_lead}, "
            "tenía exactamente el mismo problema que tú:\n"
            "{problema_compartido}.\n\n"
            "En {tiempo}, con {solución}, logró {resultado_específico}.\n\n"
            "¿Quieres ver exactamente qué hizo?\n\n"
            "{firma}"
        ),
    },
    "objection_address": {
        "subject": "Sobre lo que me dijiste la última vez...",
        "body": (
            "Hola {nombre},\n\n"
            "Estuve pensando en lo que me comentaste sobre {objeción}.\n\n"
            "Tienes razón en preocuparte por eso. Muchos de nuestros clientes "
            "también lo pensaron al principio.\n\n"
            "Lo que descubrieron fue: {respuesta_a_objeción}.\n\n"
            "¿Resuelve eso tu duda?\n\n"
            "{firma}"
        ),
    },
    "urgency": {
        "subject": "La oferta cierra el {fecha}, {nombre}",
        "body": (
            "Hola {nombre},\n\n"
            "Solo quería recordarte que {oferta_especial} vence el {fecha}.\n\n"
            "Después de esa fecha:\n"
            "→ El precio sube a {precio_normal}\n"
            "→ {bonus} ya no estará disponible\n\n"
            "Si tienes alguna duda que te frena, escríbeme ahora mismo y la resolvemos.\n\n"
            "{firma}"
        ),
    },
}


# ─────────────────────────────────────────────────────────────────
# LEAD SCORING
# ─────────────────────────────────────────────────────────────────

class LeadScorer:
    """
    Score de leads basado en comportamiento — prioriza dónde enfocar energía.
    Modelo similar al que usan HubSpot, Salesforce, Marketo.
    """

    SCORE_MATRIX = {
        # Señales positivas (sumar puntos)
        "opened_email": 5,
        "clicked_link": 15,
        "visited_sales_page": 20,
        "downloaded_lead_magnet": 10,
        "replied_to_email": 25,
        "attended_webinar": 30,
        "asked_price_question": 40,
        "started_checkout": 50,
        "visited_page_multiple_times": 25,
        "shared_content": 15,
        "followed_on_social": 5,
        "watched_vsl_>50pct": 35,
        "clicked_buy_button": 45,
        "booked_call": 60,

        # Señales negativas (restar puntos)
        "unsubscribed": -100,
        "marked_spam": -100,
        "no_open_30days": -20,
        "bounced_email": -50,
        "asked_to_remove": -100,
    }

    SCORE_CATEGORIES = {
        "cold": (0, 25),
        "warm": (25, 60),
        "hot": (60, 100),
        "ready_to_buy": (100, 999),
    }

    @classmethod
    def calculate_score(cls, actions: list[str]) -> dict:
        total = sum(cls.SCORE_MATRIX.get(a, 0) for a in actions)
        total = max(0, total)  # No negativo

        category = "cold"
        for cat, (low, high) in cls.SCORE_CATEGORIES.items():
            if low <= total < high:
                category = cat
                break

        return {
            "score": total,
            "category": category,
            "recommended_action": cls._get_action(category),
            "actions_recorded": actions,
        }

    @classmethod
    def _get_action(cls, category: str) -> str:
        actions = {
            "cold": "Enviar contenido de valor. No vender todavía.",
            "warm": "Enviar caso de estudio + oferta suave con garantía.",
            "hot": "Contacto directo (llamada/DM). Oferta con urgencia.",
            "ready_to_buy": "URGENTE: contactar en las próximas 2 horas. Oferta personalizada.",
        }
        return actions.get(category, "Nutrir con contenido de valor.")


# ─────────────────────────────────────────────────────────────────
# MOTOR PRINCIPAL
# ─────────────────────────────────────────────────────────────────

class FollowUpEngine:
    """
    Motor de follow-up automatizado para ARIA AI.
    Gestiona secuencias, scoring y personalización.
    """

    def __init__(self):
        self.scorer = LeadScorer()

    def get_next_followup(
        self,
        sequence_type: str,
        days_since_last_contact: int,
        touchpoints: int,
    ) -> dict:
        """
        Determina si es momento de hacer follow-up y qué template usar.

        Returns: should_send: bool, template: str, urgency: str
        """
        timing = FOLLOWUP_TIMING.get(sequence_type, [1, 3, 7])
        max_touchpoints = len(timing)

        if touchpoints >= max_touchpoints:
            return {
                "should_send": False,
                "reason": f"Máximo de {max_touchpoints} touchpoints alcanzado para {sequence_type}",
                "recommendation": "Mover a lista de baja frecuencia o eliminar",
            }

        next_day = timing[touchpoints] if touchpoints < len(timing) else timing[-1]

        if days_since_last_contact >= next_day:
            template_key = self._choose_template(touchpoints, sequence_type)
            return {
                "should_send": True,
                "template": template_key,
                "touchpoint_number": touchpoints + 1,
                "timing_met": True,
                "days_waited": days_since_last_contact,
                "urgency": "high" if touchpoints >= len(timing) - 2 else "normal",
            }

        return {
            "should_send": False,
            "reason": f"Esperar {next_day - days_since_last_contact} días más",
            "next_send_in_days": next_day - days_since_last_contact,
        }

    def _choose_template(self, touchpoint: int, sequence_type: str) -> str:
        if sequence_type == "abandoned_cart":
            templates = ["no_response_1", "value_add", "urgency"]
        elif touchpoint == 0:
            templates = ["no_response_1"]
        elif touchpoint == 1:
            templates = ["value_add", "case_study"]
        elif touchpoint == 2:
            templates = ["objection_address", "case_study"]
        else:
            templates = ["breakup_email", "urgency"]
        return random.choice(templates)

    def render_template(self, template_key: str, context: dict) -> dict:
        """Renderiza un template de follow-up con el contexto dado."""
        template = FOLLOWUP_TEMPLATES.get(template_key, {})
        if not template:
            return {"error": f"Template '{template_key}' no encontrado"}

        subject = template.get("subject", "")
        body = template.get("body", "")

        for k, v in context.items():
            subject = subject.replace("{" + k + "}", str(v))
            body = body.replace("{" + k + "}", str(v))

        # Limpiar placeholders no reemplazados
        import re
        subject = re.sub(r"\{[^}]+\}", "", subject)
        body = re.sub(r"\{[^}]+\}", "", body)

        return {
            "template": template_key,
            "subject": subject.strip(),
            "body": body.strip(),
            "ready_to_send": True,
        }

    def score_lead(self, actions: list[str]) -> dict:
        return self.scorer.calculate_score(actions)

    def create_followup_plan(
        self,
        lead_name: str,
        lead_email: str,
        sequence_type: str,
        product: str,
        pain: str,
    ) -> dict:
        """Crea un plan completo de follow-up para un lead."""
        timing = FOLLOWUP_TIMING.get(sequence_type, [1, 3, 7])
        plan = []
        base_context = {
            "nombre": lead_name,
            "email": lead_email,
            "producto": product,
            "beneficio": f"resolver {pain}",
            "dolor_específico": pain,
            "tema": product,
            "firma": f"El equipo de ARIA AI",
        }

        for i, day in enumerate(timing):
            template_key = self._choose_template(i, sequence_type)
            rendered = self.render_template(template_key, base_context)
            plan.append({
                "touchpoint": i + 1,
                "send_on_day": day,
                "template": template_key,
                "subject": rendered.get("subject", ""),
                "preview": rendered.get("body", "")[:100] + "...",
            })

        return {
            "lead": {"name": lead_name, "email": lead_email},
            "product": product,
            "sequence_type": sequence_type,
            "total_touchpoints": len(timing),
            "total_duration_days": timing[-1],
            "plan": plan,
        }

    def get_all_templates(self) -> dict:
        return {k: {"subject": v["subject"], "purpose": k.replace("_", " ").title()}
                for k, v in FOLLOWUP_TEMPLATES.items()}

    def get_timing_guide(self) -> dict:
        return FOLLOWUP_TIMING
