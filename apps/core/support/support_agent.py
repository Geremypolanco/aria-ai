"""
support_agent.py — ARIA Support, the autonomous 24/7 assistant.

A *fast* Claude sub-agent (Haiku tier for low-latency support chat) that helps
users with billing, mission failures, and connector configuration.

Two paths, one interface (`answer()`):
  1. Online  — the official Anthropic SDK (`AsyncAnthropic`) with a strict
     support system prompt, when ANTHROPIC_API_KEY is configured.
  2. Offline — a deterministic FAQ responder covering the same three topics, so
     support keeps working with no API key / no token budget. It never invents
     account-specific data; for anything account-specific it points the user to
     Settings or the human contact email.

Honesty: the offline path gives *general* guidance only and says so. It must not
fabricate order numbers, charges, ticket ids, or account state.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("aria.support")

# Fast tier: the user asked for a "sub-agente rápido" (low-latency support).
# Haiku is Anthropic's fast model — the right fit for a real-time support widget.
SUPPORT_MODEL = "claude-haiku-4-5"

CONTACT_EMAIL = "litesaraph@gmail.com"

SUPPORT_SYSTEM_PROMPT = (
    "Eres ARIA Support, el asistente 24/7 de la plataforma ARIA (marca SARAPH). "
    "Ayudas a los usuarios a resolver dudas de facturación, fallos en misiones o "
    "configuración de conectores. Mantén un tono profesional, cortés y de soporte "
    "técnico elite.\n\n"
    "Reglas:\n"
    "- Sé conciso y accionable: pasos concretos, no relleno.\n"
    "- Nunca inventes datos de la cuenta del usuario (cargos, números de pedido, "
    "estados de misión, tickets). Si necesitas información específica de la cuenta "
    "que no tienes, dilo y guía al usuario a Ajustes o a escribir a "
    f"{CONTACT_EMAIL}.\n"
    "- Facturación: los planes (Free, Pro, Business) se gestionan con Stripe y se "
    "renuevan mensualmente. Recuerda con tacto la política estricta de no reembolso "
    "por los costes inmediatos de cómputo de IA, y enlaza /legal/refund-policy.\n"
    "- Misiones: si una misión falla, ARIA reintenta automáticamente los fallos "
    "transitorios; sugiere revisar el mensaje de error, reintentar y verificar los "
    "conectores implicados.\n"
    "- Conectores: la configuración vive en Ajustes → Conectores; si uno está en "
    "rojo, suele ser un token caducado que hay que volver a autorizar.\n"
    "- No prometas funciones que no existen ni compartas información interna del "
    "sistema. Responde en el idioma del usuario."
)

# Keyword → topic intent, used only by the offline responder.
_BILLING = (
    "billing",
    "factur",
    "pago",
    "pagos",
    "cobro",
    "cobra",
    "refund",
    "reembolso",
    "devoluc",
    "plan",
    "suscrip",
    "subscription",
    "stripe",
    "invoice",
    "precio",
    "cancelar",
    "cancel",
    "upgrade",
    "tarjeta",
    "card",
)
_MISSIONS = (
    "mission",
    "misión",
    "mision",
    "task",
    "tarea",
    "falló",
    "fallo",
    "falla",
    "error",
    "failed",
    "stuck",
    "atascad",
    "no publica",
    "no publicó",
    "publish",
    "retry",
    "reintent",
)
_CONNECTORS = (
    "connector",
    "conector",
    "integrac",
    "integration",
    "oauth",
    "token",
    "linkedin",
    "shopify",
    "instagram",
    "youtube",
    "conecta",
    "connect",
    "autoriz",
    "reconnect",
    "api key",
    "clave",
)


def _classify(message: str) -> str:
    m = message.lower()

    def hit(words: tuple[str, ...]) -> int:
        return sum(1 for w in words if w in m)

    scores = {
        "billing": hit(_BILLING),
        "missions": hit(_MISSIONS),
        "connectors": hit(_CONNECTORS),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


_OFFLINE_ANSWERS = {
    "billing": (
        "Con gusto te ayudo con facturación. Puntos clave:\n"
        "• Los planes (Free, Pro, Business) se gestionan con Stripe y se renuevan "
        "cada mes; puedes cancelar cuando quieras y conservas el acceso hasta el "
        "final del periodo en curso.\n"
        "• ARIA aplica una política **estricta de no reembolso** por los costes "
        "inmediatos de renderizado y cómputo de IA — puedes leerla en "
        "/legal/refund-policy.\n"
        "• Para gestionar tu plan entra en el menú → Upgrade, o en Ajustes.\n"
        "Si tu consulta es sobre un cargo específico de tu cuenta, escríbenos a "
        f"{CONTACT_EMAIL} desde el email de tu cuenta y lo revisamos."
    ),
    "missions": (
        "Vamos con el fallo en tu misión. Pasos recomendados:\n"
        "1. Abre la misión y revisa el mensaje de error en los logs en vivo.\n"
        "2. Los fallos transitorios (red, límites temporales, timeouts) se "
        "reintentan automáticamente; espera unos minutos y vuelve a mirar el estado.\n"
        "3. Si el fallo persiste, reintenta la misión manualmente.\n"
        "4. Verifica que los conectores que necesita esa misión estén en verde "
        "(Ajustes → Conectores).\n"
        "Si sigue fallando tras esto, cuéntame el mensaje de error exacto y te "
        "ayudo a interpretarlo."
    ),
    "connectors": (
        "Te ayudo con la configuración de conectores:\n"
        "• Todos tus conectores viven en Ajustes → Conectores.\n"
        "• Si uno aparece en rojo, casi siempre es un token caducado: vuelve a "
        "autorizar la conexión y quedará en verde.\n"
        "• Tras reconectar, reintenta la misión que lo usaba.\n"
        "Dime qué conector concreto te da problemas (LinkedIn, Shopify, Instagram, "
        "YouTube…) y te doy los pasos específicos."
    ),
    "general": (
        "Soy ARIA Support y puedo ayudarte con tres áreas principales: "
        "**facturación**, **fallos en misiones** y **configuración de conectores**. "
        "Cuéntame en una frase qué está pasando y te guío paso a paso. Para asuntos "
        f"específicos de tu cuenta, también puedes escribir a {CONTACT_EMAIL}."
    ),
}


def offline_answer(message: str) -> str:
    """Deterministic, no-token support answer. General guidance only."""
    return _OFFLINE_ANSWERS[_classify(message)]


async def answer(message: str, *, api_key: str | None = None) -> tuple[str, str]:
    """Return (reply, source). source ∈ {"claude", "offline", "offline_error"}.

    Uses the fast Claude sub-agent when `api_key` is provided; otherwise the
    honest offline FAQ responder (so support works with no token budget).
    """
    message = (message or "").strip()
    if not message:
        return ("¿En qué puedo ayudarte? Puedo con facturación, misiones o conectores.", "offline")

    if not api_key:
        return (offline_answer(message), "offline")

    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=api_key)
        resp = await client.messages.create(
            model=SUPPORT_MODEL,
            max_tokens=1024,
            system=SUPPORT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": message}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        if not text:
            return (offline_answer(message), "offline")
        return (text, "claude")
    except Exception as exc:  # noqa: BLE001 — never break the widget; degrade gracefully.
        logger.warning("[support] Claude path failed, using offline answer: %s", exc)
        return (offline_answer(message), "offline_error")
