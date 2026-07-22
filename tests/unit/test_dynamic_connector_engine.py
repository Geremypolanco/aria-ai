"""Tests for the Dynamic Connector Engine (apps/core/connections/dynamic).
Uses httpx.MockTransport so no real network call is ever made, while still
exercising the real request-building, retry and auth-injection code paths."""

from __future__ import annotations

import httpx
import pytest

from apps.core.connections.dynamic.engine import (
    ConnectorAuthError,
    ConnectorConfigError,
    ConnectorHTTPError,
    DynamicConnectorEngine,
    available_connectors,
    get_engine,
    load_all_specs,
)
from apps.core.connections.dynamic.schema import AuthSpec, ConnectorSpec, EndpointSpec, RetrySpec


def _spec(**overrides) -> ConnectorSpec:
    base = dict(
        id="acme",
        name="Acme",
        base_url="https://api.acme.example",
        # A real Settings field is reused here (rather than a fictitious one)
        # because pydantic's BaseSettings rejects assigning undeclared attrs.
        auth=AuthSpec(type="api_key", settings_key="STRIPE_SECRET_KEY"),
        retry=RetrySpec(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.02),
        endpoints={
            "get_thing": EndpointSpec(method="GET", path="/things/{thing_id}"),
            "list_things": EndpointSpec(method="GET", path="/things", query_params=["limit"]),
            "create_thing": EndpointSpec(method="POST", path="/things", body_params=["name"]),
        },
    )
    base.update(overrides)
    return ConnectorSpec(**base)


def test_specs_load_and_validate_from_disk():
    specs = load_all_specs()
    assert {"hubspot", "salesforce", "stripe"} <= set(specs)


def test_available_connectors_and_unknown_id():
    assert "stripe" in available_connectors()
    with pytest.raises(ConnectorConfigError):
        get_engine("does-not-exist")


@pytest.mark.asyncio
async def test_missing_path_variable_fails_before_any_network_call():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not reach the network")

    engine = DynamicConnectorEngine(_spec(), transport=httpx.MockTransport(handler))
    with pytest.raises(ConnectorConfigError):
        await engine.call("get_thing")  # missing thing_id


@pytest.mark.asyncio
async def test_unknown_endpoint_raises_config_error():
    engine = DynamicConnectorEngine(_spec())
    with pytest.raises(ConnectorConfigError):
        await engine.call("no_such_endpoint")


@pytest.mark.asyncio
async def test_api_key_auth_missing_setting_raises_auth_error(monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.STRIPE_SECRET_KEY", None)
    engine = DynamicConnectorEngine(_spec())
    with pytest.raises(ConnectorAuthError):
        await engine.call("list_things", limit=5)


@pytest.mark.asyncio
async def test_api_key_is_injected_and_query_param_passed(monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.STRIPE_SECRET_KEY", "secret123")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth_header"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    engine = DynamicConnectorEngine(_spec(), transport=httpx.MockTransport(handler))
    result = await engine.call("list_things", limit=5)
    assert result == {"ok": True}
    assert seen["auth_header"] == "secret123"  # default AuthSpec has no value_prefix
    assert "limit=5" in seen["url"]


@pytest.mark.asyncio
async def test_oauth2_missing_token_raises_auth_error(monkeypatch):
    async def fake_get_token(email, pid):
        return None

    monkeypatch.setattr("apps.core.connectors.oauth_hub.get_token", fake_get_token)
    engine = DynamicConnectorEngine(_spec(auth=AuthSpec(type="oauth2", service_id="acme")))
    with pytest.raises(ConnectorAuthError):
        await engine.call("get_thing", email="user@example.com", thing_id="1")


@pytest.mark.asyncio
async def test_oauth2_bearer_token_injected_via_explicit_token_arg():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer tok-abc"
        return httpx.Response(200, json={"id": "1", "name": "Widget"})

    engine = DynamicConnectorEngine(
        _spec(auth=AuthSpec(type="oauth2", service_id="acme")),
        transport=httpx.MockTransport(handler),
    )
    result = await engine.call("get_thing", thing_id="1", token={"access_token": "tok-abc"})
    assert result == {"name": "Widget", "id": "1"}


@pytest.mark.asyncio
async def test_retries_transient_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.STRIPE_SECRET_KEY", "secret123")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(200, json={"ok": True})

    engine = DynamicConnectorEngine(_spec(), transport=httpx.MockTransport(handler))
    result = await engine.call("list_things", limit=1)
    assert result == {"ok": True}
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_client_error_is_not_retried(monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.STRIPE_SECRET_KEY", "secret123")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    engine = DynamicConnectorEngine(_spec(), transport=httpx.MockTransport(handler))
    with pytest.raises(ConnectorHTTPError) as exc:
        await engine.call("list_things", limit=1)
    assert exc.value.status_code == 400
    assert calls["n"] == 1  # no retry on a 4xx


@pytest.mark.asyncio
async def test_exhausted_retries_raise_connector_http_error(monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.STRIPE_SECRET_KEY", "secret123")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    engine = DynamicConnectorEngine(_spec(), transport=httpx.MockTransport(handler))
    with pytest.raises(ConnectorHTTPError) as exc:
        await engine.call("list_things", limit=1)
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_response_path_unwraps_nested_data(monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.STRIPE_SECRET_KEY", "secret123")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": 1}, {"id": 2}], "has_more": False})

    spec = _spec(
        endpoints={
            "list_things": EndpointSpec(method="GET", path="/things", response_path="data"),
        }
    )
    engine = DynamicConnectorEngine(spec, transport=httpx.MockTransport(handler))
    result = await engine.call("list_things")
    assert result == [{"id": 1}, {"id": 2}]


@pytest.mark.asyncio
async def test_salesforce_base_url_templated_from_token_instance_url():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(
            "https://my-org.my.salesforce.com/services/data/v59.0/sobjects/Account/001"
        )
        return httpx.Response(200, json={"Id": "001", "Name": "Acme Inc"})

    engine = get_engine("salesforce", transport=httpx.MockTransport(handler))
    result = await engine.call(
        "get_account",
        account_id="001",
        token={"access_token": "tok", "instance_url": "https://my-org.my.salesforce.com"},
    )
    assert result["Name"] == "Acme Inc"


@pytest.mark.asyncio
async def test_stripe_create_charge_uses_form_encoding(monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.STRIPE_SECRET_KEY", "sk_test_123")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        assert b"amount=500" in request.content
        return httpx.Response(200, json={"id": "ch_123", "status": "succeeded"})

    engine = get_engine("stripe", transport=httpx.MockTransport(handler))
    result = await engine.call(
        "create_charge", amount=500, currency="usd", source="tok_visa", description="test"
    )
    assert result["status"] == "succeeded"
