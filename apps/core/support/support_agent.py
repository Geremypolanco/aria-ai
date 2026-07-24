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

# Fast tier: the user asked for a "fast sub-agent" (low-latency support).
# Haiku is Anthropic's fast model — the right fit for a real-time support widget.
SUPPORT_MODEL = "claude-haiku-4-5"

CONTACT_EMAIL = "litesaraph@gmail.com"

SUPPORT_SYSTEM_PROMPT = (
    "You are ARIA Support, the 24/7 assistant for the ARIA platform (SARAPH brand). "
    "You help users resolve billing questions, mission failures, or connector "
    "configuration issues. Maintain a professional, courteous, elite technical "
    "support tone.\n\n"
    "Rules:\n"
    "- Be concise and actionable: concrete steps, no filler.\n"
    "- Never invent account-specific data (charges, order numbers, mission "
    "statuses, tickets). If you need specific account information you don't "
    "have, say so and direct the user to Settings or to write to "
    f"{CONTACT_EMAIL}.\n"
    "- Billing: plans (Free, Pro, Business) are managed via Stripe and renew "
    "monthly. Tactfully remind users of the strict no-refund policy for "
    "immediate AI compute costs, and link to /legal/refund-policy.\n"
    "- Missions: if a mission fails, ARIA automatically retries transient "
    "failures; suggest reviewing the error message, retrying, and checking the "
    "connectors involved.\n"
    "- Connectors: configuration lives under Settings → Connectors; if one "
    "shows red, it's usually an expired token that needs to be reauthorized.\n"
    "- Never promise features that don't exist or share internal system "
    "information. Respond in the user's language."
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
        "Happy to help with billing. Key points:\n"
        "• Plans (Free, Pro, Business) are managed via Stripe and renew "
        "monthly; you can cancel anytime and keep access until the end of "
        "the current period.\n"
        "• ARIA enforces a **strict no-refund policy** for immediate rendering "
        "and AI compute costs — you can read it at "
        "/legal/refund-policy.\n"
        "• To manage your plan, go to the menu → Upgrade, or Settings.\n"
        "If your question is about a specific charge on your account, email us at "
        f"{CONTACT_EMAIL} from your account's email and we'll look into it."
    ),
    "missions": (
        "Let's look at your mission failure. Recommended steps:\n"
        "1. Open the mission and review the error message in the live logs.\n"
        "2. Transient failures (network, temporary limits, timeouts) are "
        "retried automatically; wait a few minutes and check the status again.\n"
        "3. If the failure persists, retry the mission manually.\n"
        "4. Verify that the connectors this mission needs are green "
        "(Settings → Connectors).\n"
        "If it's still failing after this, tell me the exact error message and I'll "
        "help you interpret it."
    ),
    "connectors": (
        "I'll help with your connector configuration:\n"
        "• All your connectors live under Settings → Connectors.\n"
        "• If one shows red, it's almost always an expired token: reauthorize "
        "the connection and it'll turn green.\n"
        "• After reconnecting, retry the mission that was using it.\n"
        "Tell me which specific connector is giving you trouble (LinkedIn, Shopify, "
        "Instagram, YouTube…) and I'll give you the specific steps."
    ),
    "general": (
        "I'm ARIA Support and I can help with three main areas: "
        "**billing**, **mission failures**, and **connector configuration**. "
        "Tell me in one sentence what's going on and I'll guide you step by step. "
        f"For account-specific matters, you can also email {CONTACT_EMAIL}."
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
        return ("How can I help you? I can assist with billing, missions, or connectors.", "offline")

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
