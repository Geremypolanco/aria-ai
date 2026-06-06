"""
audit_logger.py — Registro de todos los eventos de seguridad.
Registra accesos, amenazas, rate limits, inputs bloqueados y cambios de config.
"""
from __future__ import annotations
import logging, time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Deque, Dict, List, Optional
logger = logging.getLogger("aria.security.audit")

class EventType(Enum):
    ACCESS_GRANTED = "access_granted"
    ACCESS_DENIED = "access_denied"
    RATE_LIMITED = "rate_limited"
    INPUT_BLOCKED = "input_blocked"
    THREAT_DETECTED = "threat_detected"
    BOT_COMMAND = "bot_command"
    CONFIG_CHANGE = "config_change"
    SYSTEM_EVENT = "system_event"
    SUSPICIOUS_PATTERN = "suspicious_pattern"

class Severity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

@dataclass
class AuditEvent:
    event_type: str
    severity: str
    user_id: str
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    ts_monotonic: float = field(default_factory=time.monotonic)

    def to_dict(self) -> Dict:
        return asdict(self)

class AuditLogger:
    MAX_EVENTS_IN_MEMORY = 1000

    def __init__(self):
        self._events: Deque[AuditEvent] = deque(maxlen=self.MAX_EVENTS_IN_MEMORY)
        self._counts: Dict[str, int] = {}

    def log(self, event_type: EventType, user_id: str, message: str,
            severity: Severity = Severity.INFO, metadata: Optional[Dict] = None) -> AuditEvent:
        event = AuditEvent(event_type=event_type.value, severity=severity.value,
                           user_id=user_id, message=message, metadata=metadata or {})
        self._events.append(event)
        self._counts[event_type.value] = self._counts.get(event_type.value, 0) + 1
        log_fn = {Severity.INFO: logger.info, Severity.WARNING: logger.warning,
                  Severity.CRITICAL: logger.critical}.get(severity, logger.info)
        log_fn("[Audit][%s] user=%s — %s", event_type.value, user_id, message)
        return event

    def access_granted(self, user_id: str, chat_type: str = "private") -> None:
        self.log(EventType.ACCESS_GRANTED, user_id, f"Acceso concedido ({chat_type})", Severity.INFO)

    def access_denied(self, user_id: str, reason: str) -> None:
        self.log(EventType.ACCESS_DENIED, user_id, f"Acceso denegado: {reason}", Severity.WARNING,
                 {"reason": reason})

    def rate_limited(self, user_id: str, limit_type: str) -> None:
        self.log(EventType.RATE_LIMITED, user_id, f"Rate limit: {limit_type}", Severity.WARNING,
                 {"limit_type": limit_type})

    def input_blocked(self, user_id: str, reason: str, input_preview: str = "") -> None:
        self.log(EventType.INPUT_BLOCKED, user_id, f"Input bloqueado: {reason}", Severity.WARNING,
                 {"reason": reason, "input_preview": input_preview[:100]})

    def threat_detected(self, user_id: str, score: int, signals: List[str]) -> None:
        self.log(EventType.THREAT_DETECTED, user_id,
                 f"Amenaza: score={score}, señales={signals}", Severity.CRITICAL,
                 {"score": score, "signals": signals})

    def bot_command(self, user_id: str, command: str) -> None:
        self.log(EventType.BOT_COMMAND, user_id, f"Comando: {command}", Severity.INFO, {"command": command})

    def suspicious_pattern(self, user_id: str, pattern: str) -> None:
        self.log(EventType.SUSPICIOUS_PATTERN, user_id, f"Patrón sospechoso: {pattern}", Severity.WARNING,
                 {"pattern": pattern})

    def recent(self, n: int = 20, severity: Optional[str] = None, user_id: Optional[str] = None) -> List[Dict]:
        events = list(self._events)
        if severity:
            events = [e for e in events if e.severity == severity]
        if user_id:
            events = [e for e in events if e.user_id == user_id]
        return [e.to_dict() for e in events[-n:]]

    def critical_events(self, n: int = 10) -> List[Dict]:
        return self.recent(n=n, severity=Severity.CRITICAL.value)

    def stats(self) -> Dict:
        return {"total_events": len(self._events), "counts_by_type": dict(self._counts),
                "critical_count": self._counts.get(EventType.THREAT_DETECTED.value, 0) +
                                  self._counts.get(EventType.ACCESS_DENIED.value, 0),
                "recent_critical": self.critical_events(5)}

_instance: Optional[AuditLogger] = None
def get_audit_logger() -> AuditLogger:
    global _instance
    if _instance is None:
        _instance = AuditLogger()
    return _instance
