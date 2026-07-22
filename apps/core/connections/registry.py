"""
ConnectorFactory — the Factory Manager for third-party API connectors.

The design goal: adding connector #300 means writing one class in one new
file that inherits BaseConnector and carries @register_connector("service_id")
— nothing in ConnectionManager, main.py, or anywhere else in the core changes.

That promise only holds if something actually imports every connector module
so its decorator runs. `_autodiscover()` does that by walking this package's
own directory (pkgutil), so a new `*_connection.py` file is picked up simply
by existing on disk — no import to add, no list to update.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

from apps.core.connections.base import BaseConnector

logger = logging.getLogger("aria.connections.registry")

_REGISTRY: dict[str, type[BaseConnector]] = {}
_DISCOVERED = False

# Modules in this package that aren't connectors themselves and must not be
# imported as one (avoids a circular import back into this module).
_NON_CONNECTOR_MODULES = {"base", "registry", "manager", "__init__"}


def register_connector(service_id: str, display_name: str = ""):
    """Class decorator: self-registers a BaseConnector subclass.

    Usage (in a new *_connection.py file — the only file a new connector
    needs to touch):

        @register_connector("acme_crm", display_name="Acme CRM")
        class AcmeCrmConnection(BaseConnector):
            def get_auth_url(self, chat_id): ...
            async def exchange_code(self, code, chat_id): ...
    """

    def _wrap(cls: type[BaseConnector]) -> type[BaseConnector]:
        if not (isinstance(cls, type) and issubclass(cls, BaseConnector)):
            raise TypeError(
                f"@register_connector('{service_id}'): {cls.__name__} must subclass BaseConnector"
            )
        existing = _REGISTRY.get(service_id)
        if existing is not None and existing is not cls:
            logger.warning(
                "[connectors] '%s' re-registered: %s -> %s",
                service_id,
                existing.__name__,
                cls.__name__,
            )
        cls.service_id = service_id
        cls.display_name = display_name or cls.display_name or cls.__name__
        _REGISTRY[service_id] = cls
        return cls

    return _wrap


def _autodiscover() -> None:
    """Import every *_connection.py module in this package once, so every
    @register_connector decorator in the package has had a chance to run."""
    global _DISCOVERED
    if _DISCOVERED:
        return
    _DISCOVERED = True  # set first: a failed import must not retry every call

    import apps.core.connections as pkg

    for info in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
        short_name = info.name.rsplit(".", 1)[-1]
        # Subpackages (e.g. dynamic/) are a different connector mechanism —
        # importing them here wouldn't reach classes nested in their own
        # submodules anyway, and they self-manage their own loading.
        if short_name in _NON_CONNECTOR_MODULES or info.ispkg:
            continue
        try:
            importlib.import_module(info.name)
        except Exception as exc:  # noqa: BLE001 — one bad connector must not break the rest
            logger.warning("[connectors] failed to load %s: %s", info.name, exc)


class ConnectorFactory:
    """Looks up and instantiates connectors by service_id. This is the only
    thing ConnectionManager depends on — it never imports a connector class
    directly."""

    @staticmethod
    def available() -> list[str]:
        _autodiscover()
        return sorted(_REGISTRY)

    @staticmethod
    def is_registered(service_id: str) -> bool:
        _autodiscover()
        return service_id in _REGISTRY

    @staticmethod
    def create(service_id: str) -> BaseConnector | None:
        _autodiscover()
        cls = _REGISTRY.get(service_id)
        return cls() if cls else None
