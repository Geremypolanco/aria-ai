"""
auth_guard.py — Control de acceso: solo usuarios autorizados hablan con Aria.
Política: propietario (TELEGRAM_CHAT_ID) = acceso total. Resto = denegado en modo estricto.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Set
logger = logging.getLogger("aria.security.auth_guard")

class AccessLevel(Enum):
    OWNER = "owner"
    TRUSTED = "trusted"
    LIMITED = "limited"
    DENIED = "denied"

@dataclass
class UserPermissions:
    user_id: str
    level: AccessLevel
    name: str = ""
    can_use_system_commands: bool = False
    can_trigger_bots: bool = False
    can_view_logs: bool = False
    notes: str = ""

class AuthGuard:
    def __init__(self):
        self._owner_id: Optional[str] = None
        self._whitelist: Dict[str, UserPermissions] = {}
        self._denied: Set[str] = set()
        self._allow_groups: bool = False
        self._strict_mode: bool = True
        self._initialized: bool = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        try:
            from apps.core.config import settings
            owner = str(getattr(settings, "TELEGRAM_CHAT_ID", "") or "")
            if owner:
                self._owner_id = owner
                self._whitelist[owner] = UserPermissions(
                    user_id=owner, level=AccessLevel.OWNER, name="Owner",
                    can_use_system_commands=True, can_trigger_bots=True, can_view_logs=True)
            self._initialized = True
        except Exception as e:
            logger.warning("[AuthGuard] Error inicializando: %s", e)

    def check(self, chat_id: str, message_type: str = "private") -> AccessLevel:
        self._ensure_initialized()
        if message_type in ("group", "supergroup", "channel") and not self._allow_groups:
            return AccessLevel.DENIED
        if chat_id in self._denied:
            return AccessLevel.DENIED
        perms = self._whitelist.get(chat_id)
        if perms:
            return perms.level
        if not self._owner_id:
            logger.warning("[AuthGuard] TELEGRAM_CHAT_ID no configurado — modo abierto. Configura para modo estricto.")
            return AccessLevel.LIMITED
        if self._strict_mode:
            logger.info("[AuthGuard] Acceso denegado: chat_id=%s", chat_id)
            return AccessLevel.DENIED
        return AccessLevel.DENIED

    def is_allowed(self, chat_id: str, message_type: str = "private") -> bool:
        return self.check(chat_id, message_type) != AccessLevel.DENIED

    def is_owner(self, chat_id: str) -> bool:
        self._ensure_initialized()
        return chat_id == self._owner_id

    def can_use_system_commands(self, chat_id: str) -> bool:
        self._ensure_initialized()
        perms = self._whitelist.get(chat_id)
        return perms.can_use_system_commands if perms else False

    def add_trusted_user(self, chat_id: str, name: str = "", level: AccessLevel = AccessLevel.TRUSTED) -> None:
        self._whitelist[chat_id] = UserPermissions(
            user_id=chat_id, level=level, name=name,
            can_use_system_commands=(level == AccessLevel.OWNER),
            can_trigger_bots=(level in (AccessLevel.OWNER, AccessLevel.TRUSTED)),
            can_view_logs=(level in (AccessLevel.OWNER, AccessLevel.TRUSTED)))
        logger.info("[AuthGuard] Usuario añadido: %s (%s, %s)", chat_id, name, level.value)

    def deny_user(self, chat_id: str) -> None:
        self._denied.add(chat_id)
        self._whitelist.pop(chat_id, None)
        logger.warning("[AuthGuard] Usuario denegado: %s", chat_id)

    def remove_user(self, chat_id: str) -> None:
        self._whitelist.pop(chat_id, None)
        self._denied.discard(chat_id)

    def set_strict_mode(self, strict: bool) -> None:
        self._strict_mode = strict
        logger.info("[AuthGuard] Modo estricto: %s", "ACTIVO" if strict else "DESACTIVADO")

    def set_allow_groups(self, allow: bool) -> None:
        self._allow_groups = allow

    def status(self) -> Dict:
        self._ensure_initialized()
        return {"owner_configured": bool(self._owner_id), "strict_mode": self._strict_mode,
                "allow_groups": self._allow_groups, "whitelisted_users": len(self._whitelist),
                "denied_users": len(self._denied),
                "users": {uid: {"name": p.name, "level": p.level.value} for uid, p in self._whitelist.items()}}

_instance: Optional[AuthGuard] = None
def get_auth_guard() -> AuthGuard:
    global _instance
    if _instance is None:
        _instance = AuthGuard()
    return _instance
