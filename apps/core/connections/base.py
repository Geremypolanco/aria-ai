"""
BaseConnector — the one interface every third-party API connector implements.

This is the contract that makes the Factory in registry.py possible: as long
as a class satisfies this interface and self-registers with
@register_connector(...), ConnectionManager and everything else in the core
can drive it without knowing it exists. Scaling from 22 connectors to 300+ is
then a matter of adding files, not editing dispatch logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar


class BaseConnector(ABC):
    """Abstract base for an OAuth2-authorization-code style API connector.

    Subclasses implement `get_auth_url` and `exchange_code`; `refresh_token`
    is optional because not every provider issues refresh tokens (override it
    where it does — see GoogleConnection for the pattern).

    Contract: ConnectorFactory.create() instantiates subclasses with zero
    arguments (`cls()`) — don't declare a required __init__ parameter.
    """

    # Set by @register_connector — the key used everywhere else in the system
    # (ConnectionManager.AVAILABLE, cache keys, UI, routes).
    service_id: ClassVar[str] = ""
    display_name: ClassVar[str] = ""

    @abstractmethod
    def get_auth_url(self, chat_id: str) -> str | None:
        """Build the provider's OAuth consent URL for this user/session.

        Returns None when the connector isn't configured (missing client
        id/secret) rather than raising — callers treat that as "not ready".
        """
        raise NotImplementedError

    @abstractmethod
    async def exchange_code(self, code: str, chat_id: str) -> dict | None:
        """Exchange an authorization code for a token record.

        Returns a dict with at least `access_token`, or None/raises on
        failure. The caller (ConnectionManager) persists whatever is
        returned as-is, so include everything the connector's own action
        methods will later need (refresh_token, scope, service_user, ...).
        """
        raise NotImplementedError

    async def refresh_token(self, tokens: dict) -> dict:
        """Refresh an expired access token. Override where the provider
        supports it; the default signals that this connector doesn't."""
        raise NotImplementedError(f"'{self.service_id}' does not support token refresh")
