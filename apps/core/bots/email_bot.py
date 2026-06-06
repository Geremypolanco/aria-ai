"""
email_bot.py — Bot especializado en gestión de emails y notificaciones.
Aria NO redacta emails rutinarios. Este bot los maneja solo.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
logger = logging.getLogger("aria.bots.email")

EMAIL_TEMPLATES = {
    "welcome": "Bienvenida a nuevo suscriptor/cliente",
    "follow_up": "Seguimiento post-compra o post-reunión",
    "cold_outreach": "Prospección de nuevos clientes",
    "reengagement": "Reactivación de usuarios inactivos",
    "announcement": "Anuncio de producto o novedad",
    "support_reply": "Respuesta a soporte al cliente",
}

class EmailBot:
    def __init__(self):
        self._sent_count = 0
        self._drafted_count = 0
        self._queue: List[Dict] = []

    async def draft(self, template: str, context: Dict[str, str],
                    tone: str = "profesional y cálido", language: str = "es") -> Dict:
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = get_ai_client()
            template_desc = EMAIL_TEMPLATES.get(template, template)
            ctx_str = "\n".join(f"{k}: {v}" for k, v in context.items())
            response = await ai.complete(
                system=(f"Redactas emails profesionales en {language}. Tono: {tone}. "
                        f"Formato: primera línea es el ASUNTO (sin prefijo), luego línea vacía, luego el CUERPO."),
                user=f"Tipo de email: {template_desc}\n\nContexto:\n{ctx_str}",
                model=AIModel.FAST, max_tokens=400, agent_name="email_bot_draft",
            )
            if not response.success:
                return {"success": False, "error": "IA no disponible"}
            content = response.content.strip()
            lines = content.split("\n", 1)
            subject = lines[0].strip()
            body = lines[1].strip() if len(lines) > 1 else content
            self._drafted_count += 1
            draft = {"success": True, "template": template, "subject": subject, "body": body,
                     "language": language, "drafted_at": datetime.now(timezone.utc).isoformat()}
            self._queue.append(draft)
            logger.info("[EmailBot] Redactado: '%s'", subject[:60])
            return draft
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def draft_sequence(self, sequence_type: str, product: str, n_emails: int = 3) -> List[Dict]:
        templates_map = {
            "onboarding": ["welcome", "follow_up", "announcement"],
            "sales": ["cold_outreach", "follow_up", "reengagement"],
        }
        templates = templates_map.get(sequence_type, ["welcome", "follow_up", "announcement"])[:n_emails]
        results = []
        for i, template in enumerate(templates):
            draft = await self.draft(template=template,
                                     context={"producto": product, "dia": str(i + 1), "tipo": sequence_type})
            results.append(draft)
        return results

    async def analyze_email(self, email_content: str) -> Dict:
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = get_ai_client()
            response = await ai.complete(
                system="Analiza emails recibidos. Devuelve: categoría, prioridad, resumen en 1 oración, acción recomendada.",
                user=f"Email:\n{email_content[:1000]}",
                model=AIModel.FAST, max_tokens=150, agent_name="email_bot_analyze",
            )
            return {"success": True, "analysis": response.content.strip() if response.success else ""}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def status(self) -> Dict:
        return {"bot": "EmailBot", "drafted": self._drafted_count, "sent": self._sent_count,
                "queue_size": len(self._queue),
                "recent_drafts": [{"subject": d.get("subject", "")[:50]} for d in self._queue[-5:]]}

_instance: Optional[EmailBot] = None
def get_email_bot() -> EmailBot:
    global _instance
    if _instance is None:
        _instance = EmailBot()
    return _instance
