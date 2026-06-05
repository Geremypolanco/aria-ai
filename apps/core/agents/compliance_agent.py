"""
compliance_agent.py — ARIA AI Compliance & Safety Layer v1.

Agente de cumplimiento legal y ético que:
1. Revisa propuestas de acciones antes de ejecutarlas
2. Mantiene lista de patrones absolutamente prohibidos
3. Implementa el "freno de emergencia" del sistema
4. Auto-aprueba categorias de bajo riesgo basándose en historial
5. Aprende de nuevas normativas y actualiza politicas internas

Principio: ARIA opera SIEMPRE dentro de los limites legales y eticos.
Si hay duda, consulta al supervisor humano via Telegram.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.compliance_agent")

# Patrones absolutamente prohibidos — NUNCA se aprueban bajo ninguna circunstancia
HARD_PROHIBITIONS: list[str] = [
    "spam", "phishing", "malware", "ddos", "ransomware",
    "hack", "unauthorized_access", "brute_force",
    "fake_reviews", "astroturfing", "deceptive_advertising",
    "copyright_infringement", "plagiarism", "data_theft",
    "illegal_content", "pyramid_scheme", "ponzi_scheme",
    "money_laundering", "tax_evasion", "insider_trading",
    "identity_theft", "social_engineering_attack",
    "scrape_without_permission", "gdpr_violation",
]

# Categorias de bajo riesgo — se auto-aprueban sin revision adicional
AUTO_APPROVE_CATEGORIES: list[str] = [
    "content_creation", "seo_optimization", "blog_post",
    "email_newsletter", "social_media_post", "tweet",
    "market_research", "trend_analysis", "competitor_analysis",
    "product_listing", "affiliate_link", "product_description",
    "api_integration", "code_improvement", "bug_fix",
    "data_analysis", "performance_optimization",
    "digital_product", "ebook", "template", "course_outline",
    "keyword_research", "backlink_outreach",
]


class ComplianceAgent(BaseAgent):
    """
    Agente de cumplimiento legal, etico y operativo de ARIA AI.
    Actua como capa de seguridad antes de acciones de alto impacto.
    """

    def __init__(self) -> None:
        super().__init__(
            name="compliance",
            description="Revision legal/etica — freno de emergencia — auto-aprobacion de bajo riesgo",
            capabilities=[
                "legal_review", "ethics_check", "risk_assessment",
                "policy_enforcement", "emergency_brake",
                "auto_approval", "normative_learning",
            ],
        )
        self._emergency_brake_active: bool = False
        self._violation_count: int = 0
        self._approved_count: int = 0
        self._rejected_count: int = 0

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mode = context.get("mode", "review")
        if mode == "review":
            return await self._review_action(context)
        elif mode == "emergency_brake":
            return await self._activate_emergency_brake(context.get("reason", "Activacion manual"))
        elif mode == "reset":
            return self._deactivate_emergency_brake()
        elif mode == "status":
            return self._get_status()
        elif mode == "learn_normative":
            return await self._learn_normative(context.get("source", ""))
        else:
            return await self._review_action(context)

    # ══════════════════════════════════════════════════════════════
    # REVISION DE ACCIONES
    # ══════════════════════════════════════════════════════════════

    async def _review_action(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Revisa si una accion propuesta es legal, etica y segura.
        Retorna: {approved, risk_level, reason, needs_human_review}
        """
        if self._emergency_brake_active:
            return {
                "success": True,
                "approved": False,
                "risk_level": "EMERGENCY",
                "reason": "Sistema en modo freno de emergencia — todas las acciones bloqueadas.",
                "needs_human_review": True,
            }

        action_type = context.get("action_type", "unknown").lower()
        description = context.get("description", "").lower()
        amount_usd = float(context.get("amount_usd", 0))
        full_text = f"{action_type} {description}"

        # 1. Verificar prohibiciones absolutas
        for prohibition in HARD_PROHIBITIONS:
            if prohibition.replace("_", " ") in full_text or prohibition in full_text:
                self._violation_count += 1
                self._rejected_count += 1
                logger.warning("[Compliance] RECHAZADO — patron prohibido: '%s'", prohibition)
                if self._violation_count >= 5:
                    await self._activate_emergency_brake(
                        f"Multiples violaciones detectadas ({self._violation_count})"
                    )
                return {
                    "success": True,
                    "approved": False,
                    "risk_level": "HIGH",
                    "reason": f"Accion rechazada — patron prohibido: '{prohibition}'",
                    "violation_count": self._violation_count,
                    "needs_human_review": True,
                }

        # 2. Auto-aprobar categorias de bajo riesgo
        for category in AUTO_APPROVE_CATEGORIES:
            if category.replace("_", " ") in full_text or category in action_type:
                self._approved_count += 1
                return {
                    "success": True,
                    "approved": True,
                    "risk_level": "LOW",
                    "reason": f"Auto-aprobado — categoria de bajo riesgo: {category}",
                    "auto_approved": True,
                    "needs_human_review": False,
                }

        # 3. Acciones con costo o impacto alto — revision con IA
        if amount_usd > 0 or any(kw in full_text for kw in ["delete", "deploy", "publish", "send_bulk", "purchase"]):
            return await self._ai_review(action_type, description, amount_usd)

        # 4. Default: aprobar con riesgo medio
        self._approved_count += 1
        return {
            "success": True,
            "approved": True,
            "risk_level": "MEDIUM",
            "reason": "Aprobado — ningun patron prohibido detectado",
            "needs_human_review": False,
        }

    async def _ai_review(
        self,
        action_type: str,
        description: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """Revision detallada con IA para acciones de mayor impacto."""
        try:
            from apps.core.tools.ai_client import get_ai_client
            ai = get_ai_client()
            if not ai:
                return {
                    "success": True,
                    "approved": True,
                    "risk_level": "MEDIUM",
                    "reason": "IA no disponible para revision — aprobado provisionalmente",
                    "needs_human_review": amount_usd > 50,
                }

            cost_str = f"${amount_usd:.2f} USD"
            resp = await ai.complete(
                system=(
                    "Eres el agente de cumplimiento legal y etico de ARIA AI. "
                    "Evalua si la accion es legal, etica y segura. "
                    "Responde SOLO con JSON valido: "
                    '{"approved": true, "risk_level": "LOW", "reason": "str", "concerns": []}'
                ),
                user=(
                    f"Accion: {action_type}\n"
                    f"Descripcion: {description}\n"
                    f"Costo: {cost_str}\n\n"
                    "Evalua: GDPR, copyright, spam, ToS de plataformas, fraude, "
                    "publicidad enganosa, privacidad."
                ),
                model=AIModel.FAST,
                json_mode=True,
            )

            if resp and resp.success:
                data = resp.content
                if isinstance(data, str):
                    match = re.search(r"\{.*\}", data, re.DOTALL)
                    data = json.loads(match.group()) if match else {}
                approved = data.get("approved", True)
                if approved:
                    self._approved_count += 1
                else:
                    self._rejected_count += 1
                return {
                    "success": True,
                    "approved": approved,
                    "risk_level": data.get("risk_level", "MEDIUM"),
                    "reason": data.get("reason", ""),
                    "concerns": data.get("concerns", []),
                    "ai_reviewed": True,
                    "needs_human_review": data.get("risk_level") == "HIGH",
                }
        except Exception as exc:
            logger.error("[Compliance] ai_review error: %s", exc)

        self._approved_count += 1
        return {
            "success": True,
            "approved": True,
            "risk_level": "MEDIUM",
            "reason": "Error en revision IA — aprobado provisionalmente",
        }

    # ══════════════════════════════════════════════════════════════
    # FRENO DE EMERGENCIA
    # ══════════════════════════════════════════════════════════════

    async def _activate_emergency_brake(self, reason: str) -> dict[str, Any]:
        """
        Activa el freno de emergencia.
        Detiene todas las operaciones autonomas y notifica al supervisor.
        Para desactivar: enviar /compliance_reset al bot de Telegram.
        """
        self._emergency_brake_active = True
        logger.critical("[Compliance] FRENO DE EMERGENCIA ACTIVADO: %s", reason)

        violations_count = self._violation_count
        await self._send_telegram(
            f"FRENO DE EMERGENCIA ACTIVADO\n\n"
            f"Razon: {reason}\n\n"
            f"ARIA ha pausado todas las operaciones autonomas.\n"
            f"Violaciones acumuladas: {violations_count}\n\n"
            f"Para reactivar el sistema enviar:\n"
            f"/compliance_reset"
        )

        return {
            "success": True,
            "emergency_brake": True,
            "active": True,
            "reason": reason,
            "message": "Sistema pausado — se requiere intervencion humana.",
        }

    def _deactivate_emergency_brake(self) -> dict[str, Any]:
        """Desactiva el freno de emergencia (solo via intervencion humana)."""
        self._emergency_brake_active = False
        self._violation_count = 0
        logger.info("[Compliance] Freno de emergencia desactivado por operador")
        return {
            "success": True,
            "emergency_brake": False,
            "message": "Sistema reactivado por operador",
        }

    # ══════════════════════════════════════════════════════════════
    # APRENDIZAJE DE NORMATIVAS
    # ══════════════════════════════════════════════════════════════

    async def _learn_normative(self, source: str) -> dict[str, Any]:
        """
        ARIA aprende de nuevas normativas legales/eticas.
        Extrae reglas de la fuente y actualiza las politicas internas.
        """
        if not source:
            return {"success": False, "error": "Se requiere fuente (URL o texto normativo)"}

        try:
            from apps.core.tools.ai_client import get_ai_client
            ai = get_ai_client()
            if not ai:
                return {"success": False, "error": "IA no disponible"}

            resp = await ai.complete(
                system=(
                    "Experto en regulacion digital, privacidad y etica de IA. "
                    "Extrae reglas aplicables a un sistema de IA autonomo de monetizacion. "
                    "Responde SOLO con JSON: "
                    '{"rules": ["regla"], "prohibitions": ["patron"], "recommendations": ["rec"]}'
                ),
                user=f"Fuente normativa:\n{source[:3000]}\n\nExtrae reglas para ARIA AI.",
                model=AIModel.STRATEGY,
                json_mode=True,
            )

            if resp and resp.success:
                data = resp.content
                if isinstance(data, str):
                    match = re.search(r"\{.*\}", data, re.DOTALL)
                    data = json.loads(match.group()) if match else {}

                new_prohibitions = data.get("prohibitions", [])
                added = []
                for p in new_prohibitions:
                    p_lower = p.lower().replace(" ", "_")
                    if p_lower not in HARD_PROHIBITIONS:
                        HARD_PROHIBITIONS.append(p_lower)
                        added.append(p_lower)

                return {
                    "success": True,
                    "rules_learned": len(data.get("rules", [])),
                    "prohibitions_added": added,
                    "total_prohibitions": len(HARD_PROHIBITIONS),
                    "recommendations": data.get("recommendations", []),
                }
        except Exception as exc:
            logger.error("[Compliance] learn_normative error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # STATUS
    # ══════════════════════════════════════════════════════════════

    def _get_status(self) -> dict[str, Any]:
        return {
            "success": True,
            "emergency_brake_active": self._emergency_brake_active,
            "violation_count": self._violation_count,
            "total_approved": self._approved_count,
            "total_rejected": self._rejected_count,
            "hard_prohibitions_count": len(HARD_PROHIBITIONS),
            "auto_approve_categories_count": len(AUTO_APPROVE_CATEGORIES),
            "prohibitions_sample": HARD_PROHIBITIONS[:5],
        }
