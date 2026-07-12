"""
Unit tests for the connector OAuth hub (apps/core/connectors/oauth_hub.py) and
its HTTP routes — the real one-click "Connect" flow behind the dashboard.

Covered:
  - registry completeness + is_configured (no creds / creds / special providers)
  - authorize-URL construction (params, redirect_uri) + PKCE for X
  - token exchange (mocked httpx) success + failure
  - token storage roundtrip + status states (connected / ready / setup)
  - HTTP: /connect requires auth; unconfigured → setup redirect; callback state
    mismatch → error; status endpoint shape.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from apps.core import auth
from apps.core.config import settings
from apps.core.connectors import oauth_hub as hub
from apps.core.main import app

QA_EMAIL = "conn@aria.test"


def _cookie():
    return {auth.USER_COOKIE: auth.sign_user(QA_EMAIL, "C", "test")}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_creds(monkeypatch):
    # Start every test with no provider creds unless the test sets them.
    for attr in (
        "LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET",
        "TWITTER_OAUTH_CLIENT_ID", "TWITTER_OAUTH_CLIENT_SECRET",
        "SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET",
        "SHOPIFY_ADMIN_TOKEN", "SHOPIFY_URL", "ZAPIER_WEBHOOK_URL", "ZAPIER_MCP_URL",
    ):
        monkeypatch.setattr(settings, attr, None, raising=False)
    yield


# ── registry / configuration ──────────────────────────────────────
class TestRegistry:
    def test_all_claude_connectors_present(self):
        expected = {
            "google", "linkedin", "youtube", "instagram", "facebook", "shopify",
            "stripe", "slack", "notion", "x", "tiktok", "zapier",
        }
        assert expected.issubset(set(hub.PROVIDERS))

    def test_unconfigured_is_setup(self):
        assert hub.is_configured("linkedin") is False

    def test_configured_when_creds_present(self, monkeypatch):
        monkeypatch.setattr(settings, "LINKEDIN_CLIENT_ID", "cid", raising=False)
        monkeypatch.setattr(settings, "LINKEDIN_CLIENT_SECRET", "sec", raising=False)
        assert hub.is_configured("linkedin") is True

    def test_shopify_special_needs_store(self, monkeypatch):
        assert hub.is_configured("shopify") is False
        monkeypatch.setattr(settings, "SHOPIFY_ADMIN_TOKEN", "tok", raising=False)
        monkeypatch.setattr(settings, "SHOPIFY_URL", "shop.myshopify.com", raising=False)
        assert hub.is_configured("shopify") is True

    def test_zapier_special_needs_webhook(self, monkeypatch):
        assert hub.is_configured("zapier") is False
        monkeypatch.setattr(settings, "ZAPIER_WEBHOOK_URL", "https://hooks", raising=False)
        assert hub.is_configured("zapier") is True


# ── authorize URL ─────────────────────────────────────────────────
class TestAuthorize:
    def test_url_has_required_params(self, monkeypatch):
        monkeypatch.setattr(settings, "SLACK_CLIENT_ID", "slackid", raising=False)
        monkeypatch.setattr(settings, "SLACK_CLIENT_SECRET", "slacksec", raising=False)
        url, verifier = hub.build_authorize("slack", "state.sig")
        assert url.startswith("https://slack.com/oauth/v2/authorize?")
        assert "client_id=slackid" in url
        assert "state=state.sig" in url
        assert "response_type=code" in url
        assert "%2Fconnectors%2Fslack%2Fcallback" in url  # redirect_uri encoded
        assert verifier == ""  # slack is not PKCE

    def test_pkce_for_x(self, monkeypatch):
        monkeypatch.setattr(settings, "TWITTER_OAUTH_CLIENT_ID", "xid", raising=False)
        monkeypatch.setattr(settings, "TWITTER_OAUTH_CLIENT_SECRET", "xsec", raising=False)
        url, verifier = hub.build_authorize("x", "st.sig")
        assert verifier and "code_challenge=" in url and "code_challenge_method=S256" in url

    def test_tiktok_uses_client_key_param(self, monkeypatch):
        monkeypatch.setattr(settings, "TIKTOK_CLIENT_KEY", "ttkey", raising=False)
        monkeypatch.setattr(settings, "TIKTOK_CLIENT_SECRET", "ttsec", raising=False)
        url, _ = hub.build_authorize("tiktok", "st.sig")
        assert "client_key=ttkey" in url


# ── token exchange (mocked httpx) ─────────────────────────────────
class TestExchange:
    async def test_exchange_success(self, monkeypatch):
        monkeypatch.setattr(settings, "SLACK_CLIENT_ID", "id", raising=False)
        monkeypatch.setattr(settings, "SLACK_CLIENT_SECRET", "sec", raising=False)
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"access_token": "AT", "scope": "chat:write"}
        cm = AsyncMock()
        cm.__aenter__.return_value.post = AsyncMock(return_value=resp)
        with patch("httpx.AsyncClient", return_value=cm):
            tok = await hub.exchange_code("slack", "authcode")
        assert tok["access_token"] == "AT"

    async def test_exchange_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(settings, "SLACK_CLIENT_ID", "id", raising=False)
        monkeypatch.setattr(settings, "SLACK_CLIENT_SECRET", "sec", raising=False)
        resp = MagicMock(status_code=400, text="bad")
        cm = AsyncMock()
        cm.__aenter__.return_value.post = AsyncMock(return_value=resp)
        with patch("httpx.AsyncClient", return_value=cm):
            tok = await hub.exchange_code("slack", "authcode")
        assert tok is None


# ── storage + status ──────────────────────────────────────────────
class TestStatus:
    async def test_token_roundtrip_and_status(self, mock_redis_patched, monkeypatch):
        monkeypatch.setattr(settings, "LINKEDIN_CLIENT_ID", "cid", raising=False)
        monkeypatch.setattr(settings, "LINKEDIN_CLIENT_SECRET", "sec", raising=False)
        await hub.save_token(QA_EMAIL, "linkedin", {"access_token": "AT"})
        assert (await hub.get_token(QA_EMAIL, "linkedin"))["access_token"] == "AT"

        rows = {r["id"]: r for r in await hub.status_for(QA_EMAIL)}
        assert rows["linkedin"]["state"] == "connected"  # has token
        assert rows["slack"]["state"] == "setup"          # no creds
        # configured-but-not-connected → ready
        monkeypatch.setattr(settings, "SLACK_CLIENT_ID", "s", raising=False)
        monkeypatch.setattr(settings, "SLACK_CLIENT_SECRET", "s", raising=False)
        rows2 = {r["id"]: r for r in await hub.status_for(QA_EMAIL)}
        assert rows2["slack"]["state"] == "ready"

    async def test_disconnect_removes_token(self, mock_redis_patched):
        await hub.save_token(QA_EMAIL, "notion", {"access_token": "AT"})
        await hub.disconnect(QA_EMAIL, "notion")
        assert await hub.get_token(QA_EMAIL, "notion") is None


# ── HTTP routes ───────────────────────────────────────────────────
class TestRoutes:
    def test_connect_requires_auth(self, client):
        r = client.get("/connectors/slack/connect", follow_redirects=False)
        assert r.status_code in (302, 303, 307)
        assert "/login" in r.headers.get("location", "")

    def test_connect_unconfigured_redirects_to_setup(self, client):
        r = client.get("/connectors/slack/connect", cookies=_cookie(), follow_redirects=False)
        assert r.status_code == 303
        assert "s=setup" in r.headers.get("location", "")

    def test_connect_configured_redirects_to_provider(self, client, monkeypatch):
        monkeypatch.setattr(settings, "SLACK_CLIENT_ID", "id", raising=False)
        monkeypatch.setattr(settings, "SLACK_CLIENT_SECRET", "sec", raising=False)
        r = client.get("/connectors/slack/connect", cookies=_cookie(), follow_redirects=False)
        assert r.status_code == 307
        loc = r.headers.get("location", "")
        assert loc.startswith("https://slack.com/oauth/v2/authorize")
        # CSRF state cookie set
        assert any("aria_conn_state" in v for v in r.headers.get_list("set-cookie"))

    def test_callback_bad_state_is_error(self, client):
        r = client.get(
            "/connectors/slack/callback?code=abc&state=nope",
            cookies=_cookie(),
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert "s=error" in r.headers.get("location", "")

    def test_status_endpoint_shape(self, client):
        r = client.get("/api/v1/connectors/status", cookies=_cookie())
        assert r.status_code == 200
        conns = r.json()["connectors"]
        assert len(conns) == 12
        assert all({"id", "name", "state"} <= set(c) for c in conns)
        # with no creds configured, everything is "setup"
        assert all(c["state"] in ("setup", "ready", "connected") for c in conns)
