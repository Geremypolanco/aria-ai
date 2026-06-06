"""
firewall.py — Punto de entrada unificado del sistema de seguridad.

Aplica en orden:
  1. Auth Guard       — ¿Está autorizado este usuario?
  2. Rate Limiter     — ¿Está enviando demasiado rápido?
  3. Input Sanitizer  — ¿El mensaje es seguro?
  4. Threat Detector  — ¿El comportamiento es malicioso?

Uso:
    fw = get_firewall()
    decision = await fw.inspect(chat_id, text, sender, chat_type)
    if not decision.allowed:
        return  # bloquear silenciosamente
    # usar decision.clean_text en lugar del texto original
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import List, Optional
from apps.core.security.auth_guard import AccessLevel, get_auth_guard
from apps.core.security.audit_logger import get_audit_logger
from apps.core.security.input_sanitizer import get_sanitizer
from apps.core.security.rate_limiter import get_rate_limiter
from apps.core.security.threat_detector import get_threat_detector
logger = logging.getLogger("aria.security.firewall")

@dataclass
class FirewallDecision:
    allowed: bool
    clean_text: str
    user_id: str
    access_level: str
    block_reason: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

class AriaFirewall:
    """Firewall multicapa para Aria. Cada mensaje pasa por 4 capas antes de llegar a la IA."""

    def __init__(self):
        self._auth = get_auth_guard()
        self._rate = get_rate_limiter()
        self._sanitizer = get_sanitizer()
        self._threats = get_threat_detector()
        self._audit = get_audit_logger()
        self._total_inspected = 0
        self._total_blocked = 0

    async def inspect(self, chat_id: str, text: str,
                      sender: str = "unknown", chat_type: str = "private") -> FirewallDecision:
        """
        Inspecciona un mensaje y devuelve una decisión.
        Siempre usar decision.clean_text (no el original) si allowed=True.
        """
        self._total_inspected += 1
        audit = self._audit

        # CAPA 1: Autenticación
        access_level = self._auth.check(chat_id, chat_type)
        if access_level == AccessLevel.DENIED:
            self._total_blocked += 1
            audit.access_denied(chat_id, "not_in_whitelist")
            return FirewallDecision(allowed=False, clean_text="", user_id=chat_id,
                                    access_level=access_level.value, block_reason="auth:not_authorized")
        audit.access_granted(chat_id, chat_type)

        # CAPA 2: Rate Limiting
        rate_ok, rate_reason = self._rate.check(chat_id)
        if not rate_ok:
            self._total_blocked += 1
            audit.rate_limited(chat_id, rate_reason)
            return FirewallDecision(allowed=False, clean_text="", user_id=chat_id,
                                    access_level=access_level.value, block_reason=f"rate:{rate_reason}")

        # CAPA 3: Sanitización
        sanitize_result = self._sanitizer.sanitize(text, user_id=chat_id)
        if sanitize_result.blocked:
            self._total_blocked += 1
            audit.input_blocked(chat_id, sanitize_result.block_reason or "unknown", text[:80])
            return FirewallDecision(allowed=False, clean_text="", user_id=chat_id,
                                    access_level=access_level.value, block_reason=sanitize_result.block_reason)
        clean_text = sanitize_result.clean_text

        # CAPA 4: Detección de amenazas
        is_threat, threat_score, signals = self._threats.analyze(chat_id, clean_text)
        if is_threat:
            self._total_blocked += 1
            audit.threat_detected(chat_id, threat_score, signals)
            self._rate.block(chat_id, duration_s=1800)
            logger.critical("[Firewall] BLOQUEADO (threat): chat_id=%s score=%d", chat_id, threat_score)
            return FirewallDecision(allowed=False, clean_text="", user_id=chat_id,
                                    access_level=access_level.value,
                                    block_reason=f"threat:score={threat_score}")

        warnings = sanitize_result.flags
        if threat_score > 15:
            warnings.append(f"threat_score:{threat_score}")

        return FirewallDecision(allowed=True, clean_text=clean_text, user_id=chat_id,
                                access_level=access_level.value, warnings=warnings)

    def status(self) -> dict:
        return {"firewall": "active", "total_inspected": self._total_inspected,
                "total_blocked": self._total_blocked,
                "block_rate_pct": round(self._total_blocked / max(self._total_inspected, 1) * 100, 1),
                "auth": self._auth.status(), "rate_limiter": self._rate.global_stats(),
                "threats": self._threats.global_stats(), "audit": self._audit.stats()}

    def owner_bypass(self, chat_id: str) -> bool:
        return self._auth.is_owner(chat_id)

_instance: Optional[AriaFirewall] = None
def get_firewall() -> AriaFirewall:
    global _instance
    if _instance is None:
        _instance = AriaFirewall()
    return _instance
