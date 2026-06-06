"""
security/ — Blindaje completo de ARIA contra amenazas externas.

Módulos:
  rate_limiter     — Limita peticiones por usuario para evitar abuso
  input_sanitizer  — Limpia y valida todos los inputs antes de procesarlos
  threat_detector  — Detecta patrones maliciosos, prompt injection, spam
  auth_guard       — Solo usuarios autorizados pueden hablar con Aria
  audit_logger     — Registra todos los eventos de seguridad
  firewall         — Punto de entrada unificado que aplica todas las capas

Uso en el webhook de Telegram:
    from apps.core.security.firewall import get_firewall
    fw = get_firewall()
    decision = await fw.inspect(chat_id, user_text, sender_name)
    if not decision.allowed:
        return  # bloquear silenciosamente
"""
from apps.core.security.rate_limiter import RateLimiter, get_rate_limiter
from apps.core.security.input_sanitizer import InputSanitizer, get_sanitizer
from apps.core.security.threat_detector import ThreatDetector, get_threat_detector
from apps.core.security.auth_guard import AuthGuard, get_auth_guard
from apps.core.security.audit_logger import AuditLogger, get_audit_logger
from apps.core.security.firewall import AriaFirewall, get_firewall, FirewallDecision

__all__ = [
    "RateLimiter", "get_rate_limiter",
    "InputSanitizer", "get_sanitizer",
    "ThreatDetector", "get_threat_detector",
    "AuthGuard", "get_auth_guard",
    "AuditLogger", "get_audit_logger",
    "AriaFirewall", "get_firewall", "FirewallDecision",
]
