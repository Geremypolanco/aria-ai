"""Tests for the connector Factory Pattern (apps/core/connections/base.py +
registry.py). The core promise being verified: registering a brand-new
connector class is enough to make it available through ConnectionManager —
no other file has to change."""

from __future__ import annotations

import json

import pytest

from apps.core.connections.base import BaseConnector
from apps.core.connections.manager import ConnectionManager
from apps.core.connections.registry import ConnectorFactory, register_connector


def test_existing_connectors_are_discovered():
    available = ConnectorFactory.available()
    # A representative slice of real, pre-existing connectors named in the
    # architecture request (Salesforce, HubSpot) plus a few others.
    for expected in ("google", "slack", "hubspot", "salesforce", "quickbooks"):
        assert expected in available


def test_create_returns_a_base_connector_instance():
    connector = ConnectorFactory.create("google")
    assert connector is not None
    assert isinstance(connector, BaseConnector)


def test_create_unknown_service_returns_none():
    assert ConnectorFactory.create("does-not-exist") is None
    assert ConnectorFactory.is_registered("does-not-exist") is False


def test_base_connector_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        BaseConnector()  # abstract methods unimplemented


def test_register_connector_rejects_non_subclass():
    with pytest.raises(TypeError):

        @register_connector("not-a-connector")
        class NotAConnector:  # does not inherit BaseConnector
            pass


def test_adding_a_new_connector_requires_no_core_changes():
    """The literal claim: writing a new class and decorating it is the only
    integration point. ConnectionManager (already-written, unmodified core
    code) picks it up immediately via the Factory."""

    @register_connector("acme_test_crm", display_name="Acme Test CRM")
    class AcmeTestCrmConnection(BaseConnector):
        def get_auth_url(self, chat_id: str) -> str | None:
            return f"https://acme.example/oauth?state={chat_id}"

        async def exchange_code(self, code: str, chat_id: str) -> dict | None:
            return {"access_token": f"tok-{code}"}

    try:
        manager = ConnectionManager()
        url = manager.get_auth_url("acme_test_crm", "chat-42")
        assert url == "https://acme.example/oauth?state=chat-42"
    finally:
        # Don't leak the fixture connector into other tests' registry state.
        from apps.core.connections import registry as _registry

        _registry._REGISTRY.pop("acme_test_crm", None)


@pytest.mark.asyncio
async def test_manager_handle_callback_uses_the_factory(monkeypatch):
    calls = {}

    class FakeCache:
        async def set(self, key, value, ttl_seconds=0):
            calls["stored"] = (key, value)

    monkeypatch.setattr(
        "apps.core.memory.redis_client.get_cache", lambda: FakeCache(), raising=False
    )

    @register_connector("acme_test_crm2")
    class AcmeTestCrmConnection2(BaseConnector):
        def get_auth_url(self, chat_id: str) -> str | None:
            return None

        async def exchange_code(self, code: str, chat_id: str) -> dict | None:
            return {"access_token": "tok-abc"}

    try:
        manager = ConnectionManager()
        ok = await manager.handle_callback("acme_test_crm2", "code-xyz", "chat-1")
        assert ok is True
        # Tokens are encrypted at rest (AES-256-GCM via token_crypto), never
        # stored as a plain dict — decrypt to verify the actual content.
        from apps.core.connectors import token_crypto

        stored_key, stored_blob = calls["stored"]
        assert token_crypto.is_encrypted(stored_blob)
        assert json.loads(token_crypto.decrypt(stored_blob)) == {"access_token": "tok-abc"}
    finally:
        from apps.core.connections import registry as _registry

        _registry._REGISTRY.pop("acme_test_crm2", None)


@pytest.mark.asyncio
async def test_manager_handle_callback_unknown_service_is_false():
    manager = ConnectionManager()
    assert await manager.handle_callback("does-not-exist", "code", "chat-1") is False
