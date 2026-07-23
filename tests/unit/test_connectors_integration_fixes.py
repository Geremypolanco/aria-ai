"""Regression tests for bugs found auditing apps/core/connections/,
apps/core/connectors/ and apps/core/integrations/ — this whole connector
subsystem is currently dead code (ConnectionManager/ConnectorFactory have no
live callers; the actually-used OAuth systems are oauth_hub.py and
connections/dynamic/), but these were real, fixable bugs sitting in ~9,000
lines of maintained-looking code that would misbehave the moment anything
wires it up:

1. EtsyConnection's PKCE flow generated a real code_verifier/code_challenge
   pair, sent the challenge to Etsy, but then discarded the verifier and
   hardcoded code_verifier="" in the token exchange — Etsy's S256 check
   (SHA256(verifier) == challenge) can never pass against an empty string,
   so every Etsy OAuth exchange was guaranteed to fail.
2. AriaBusinessOSConnector.create_invoice()/update_crm_lead() never called
   any ERP/CRM API (the real httpx call was commented out) but
   unconditionally returned a confirmation string ending in "(Simulado)" —
   a fabricated success for an action that never happened anywhere.
3. McpClient._send_request() POSTed to self.server_url with no SSRF guard,
   unlike the established _assert_public_url() pattern used elsewhere in
   this repo (web_tools.py, multimodal.py) for any URL that can originate
   from user/LLM-controlled input.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


async def test_etsy_exchange_code_uses_the_real_pkce_verifier():
    from apps.core.connections.ecommerce_connection import EtsyConnection

    conn = EtsyConnection()
    with patch.object(conn, "_client_id", return_value="client-123"):
        auth_url = conn.get_auth_url("chat-1")
        assert auth_url is not None
        stored_verifier = conn._pkce_verifiers["chat-1"]
        assert stored_verifier  # non-empty, real verifier was recorded

        fake_response = MagicMock()
        fake_response.json.return_value = {"access_token": "tok", "refresh_token": "rtok"}
        fake_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=fake_response)
            mock_client_cls.return_value.__aenter__.return_value = mock_http

            await conn.exchange_code("auth-code", "chat-1")

            sent_payload = mock_http.post.call_args.kwargs["json"]
            assert sent_payload["code_verifier"] == stored_verifier
            assert sent_payload["code_verifier"] != ""

    # Verifier is single-use — popped after exchange.
    assert "chat-1" not in conn._pkce_verifiers


async def test_business_os_connector_raises_instead_of_fake_success():
    from apps.core.integrations.business_os_connector import AriaBusinessOSConnector

    conn = AriaBusinessOSConnector(erp_url="https://erp.example.com", api_key="k")

    with pytest.raises(NotImplementedError):
        await conn.create_invoice("cust-1", [{"item": "widget"}])

    with pytest.raises(NotImplementedError):
        await conn.update_crm_lead("lead-1", "won")


async def test_mcp_client_send_request_rejects_private_url():
    from apps.core.integrations.mcp_client import McpClient

    client = McpClient(server_url="http://169.254.169.254/latest/meta-data/", client_info={})
    result = await client._send_request("initialize", {})

    # _assert_public_url raises ValueError for non-public hosts; the broad
    # except in _send_request turns that into a clean None, not a real POST.
    assert result is None
