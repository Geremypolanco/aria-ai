"""
rate_limiter.py — Control de velocidad de peticiones por usuario.
Protege contra spam, abuso del API de IA y DoS por un solo usuario.
Algoritmo: sliding window — contador que se reinicia cada ventana de tiempo.
"""
from __future__ import annotations
import logging, time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
logger = logging.getLogger("aria.security.rate_limiter")

@dataclass
class RateWindow:
    count: int = 0
    window_start: float = field(default_factory=time.monotonic)
    blocked_until: float = 0.0
    total_requests: int = 0
    total_blocked: int = 0

class RateLimiter:
    """
    Limita la frecuencia de mensajes por usuario.
    Defaults: Max 20 mensajes/minuto, 100/hora. Bloqueo 60s si se supera.
    """
    DEFAULT_LIMITS = {"per_minute": 20, "per_hour": 100, "block_duration_s": 60}
    STRICT_LIMITS = {"per_minute": 5, "per_hour": 30, "block_duration_s": 300}

    def __init__(self, limits: Optional[Dict] = None):
        self._limits = limits or self.DEFAULT_LIMITS
        self._windows: Dict[str, RateWindow] = defaultdict(RateWindow)
        self._hour_windows: Dict[str, RateWindow] = defaultdict(RateWindow)
        self._permanently_blocked: set = set()

    def check(self, user_id: str) -> Tuple[bool, str]:
        """Verifica si el usuario puede enviar un mensaje. Returns: (allowed, reason)"""
        now = time.monotonic()
        if user_id in self._permanently_blocked:
            return False, "permanently_blocked"
        win = self._windows[user_id]
        hour_win = self._hour_windows[user_id]
        if win.blocked_until > now:
            remaining = int(win.blocked_until - now)
            return False, f"rate_limited:{remaining}s"
        if now - win.window_start > 60:
            win.count = 0
            win.window_start = now
        if now - hour_win.window_start > 3600:
            hour_win.count = 0
            hour_win.window_start = now
        if win.count >= self._limits["per_minute"]:
            win.blocked_until = now + self._limits["block_duration_s"]
            win.total_blocked += 1
            logger.warning("[RateLimiter] %s bloqueado por %ds (límite/min)", user_id, self._limits["block_duration_s"])
            return False, "minute_limit_exceeded"
        if hour_win.count >= self._limits["per_hour"]:
            win.blocked_until = now + self._limits["block_duration_s"] * 5
            win.total_blocked += 1
            logger.warning("[RateLimiter] %s bloqueado por límite/hora", user_id)
            return False, "hour_limit_exceeded"
        win.count += 1
        hour_win.count += 1
        win.total_requests += 1
        return True, "ok"

    def block(self, user_id: str, duration_s: int = 3600) -> None:
        self._windows[user_id].blocked_until = time.monotonic() + duration_s
        logger.warning("[RateLimiter] %s bloqueado manualmente %ds", user_id, duration_s)

    def permanent_block(self, user_id: str) -> None:
        self._permanently_blocked.add(user_id)
        logger.warning("[RateLimiter] %s BLOQUEADO PERMANENTEMENTE", user_id)

    def unblock(self, user_id: str) -> None:
        self._permanently_blocked.discard(user_id)
        if user_id in self._windows:
            self._windows[user_id].blocked_until = 0.0

    def stats(self, user_id: str) -> Dict:
        win = self._windows.get(user_id, RateWindow())
        return {"user_id": user_id, "requests_this_minute": win.count,
                "total_requests": win.total_requests, "total_blocked": win.total_blocked,
                "is_blocked": win.blocked_until > time.monotonic(),
                "permanently_blocked": user_id in self._permanently_blocked}

    def global_stats(self) -> Dict:
        return {"tracked_users": len(self._windows),
                "permanently_blocked": len(self._permanently_blocked), "limits": self._limits}

_instance: Optional[RateLimiter] = None
def get_rate_limiter() -> RateLimiter:
    global _instance
    if _instance is None:
        _instance = RateLimiter()
    return _instance
