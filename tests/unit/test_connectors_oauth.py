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
        "LINKEDIN_CLIENT_ID",
        "LINKEDIN_CLIENT_SECRET",
        "TWITTER_OAUTH_CLIENT_ID",
        "TWITTER_OAUTH_CLIENT_SECRET",
        "SLACK_CLIENT_ID",
        "SLACK_CLIENT_SECRET",
        "SHOPIFY_ADMIN_TOKEN",
        "SHOPIFY_URL",
        "SHOPIFY_CLIENT_ID",
        "SHOPIFY_CLIENT_SECRET",
        "ZAPIER_WEBHOOK_URL",
        "ZAPIER_MCP_URL",
    ):
        monkeypatch.setattr(settings, attr, None, raising=False)
    yield


# ── registry / configuration ──────────────────────────────────────
class TestRegistry:
    def test_all_claude_connectors_present(self):
        expected = {
            "google",
            "linkedin",
            "youtube",
            "instagram",
            "facebook",
            "shopify",
            "stripe",
            "slack",
            "notion",
            "x",
            "tiktok",
            "zapier",
        }
        assert expected.issubset(set(hub.PROVIDERS))

    def test_unconfigured_is_setup(self):
        assert hub.is_configured("linkedin") is False

    def test_configured_when_creds_present(self, monkeypatch):
        monkeypatch.setattr(settings, "LINKEDIN_CLIENT_ID", "cid", raising=False)
        monkeypatch.setattr(settings, "LINKEDIN_CLIENT_SECRET", "sec", raising=False)
        assert hub.is_configured("linkedin") is True

    def test_shopify_special_needs_this_apps_own_oauth_credentials(self, monkeypatch):
        """is_configured("shopify") reflects whether ANY team can connect
        their OWN store (needs this app's Partner OAuth client id/secret) —
        NOT whether the owner has personally set up their own store's
        legacy SHOPIFY_ADMIN_TOKEN/SHOPIFY_URL, which is a separate,
        per-owner-only fallback (see apps/shopify/api_client.py's
        get_shopify_client_for())."""
        assert hub.is_configured("shopify") is False
        monkeypatch.setattr(settings, "SHOPIFY_ADMIN_TOKEN", "tok", raising=False)
        monkeypatch.setattr(settings, "SHOPIFY_URL", "shop.myshopify.com", raising=False)
        assert hub.is_configured("shopify") is False
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_ID", "cid", raising=False)
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_SECRET", "csec", raising=False)
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
        assert rows["slack"]["state"] == "setup"  # no creds
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
        assert len(conns) == len(hub.ORDER)
        assert all({"id", "name", "state"} <= set(c) for c in conns)
        # with no creds configured, everything is "setup"
        assert all(c["state"] in ("setup", "ready", "connected") for c in conns)


# ── Shopify: per-store OAuth (doesn't fit the generic redirect flow) ─
class TestShopifyConnect:
    def test_normalize_shop_domain_accepts_bare_name(self):
        assert hub.normalize_shop_domain("my-store") == "my-store.myshopify.com"

    def test_normalize_shop_domain_accepts_full_domain(self):
        assert hub.normalize_shop_domain("my-store.myshopify.com") == "my-store.myshopify.com"

    def test_normalize_shop_domain_strips_scheme_and_path(self):
        assert (
            hub.normalize_shop_domain("https://my-store.myshopify.com/admin")
            == "my-store.myshopify.com"
        )

    def test_normalize_shop_domain_rejects_injection_attempts(self):
        """The normalized domain gets fed straight into a URL we redirect
        the browser to and POST credentials to — anything that could smuggle
        a different host must come back empty, not a mangled-but-accepted
        value."""
        assert hub.normalize_shop_domain("evil.com/../my-store") == ""
        assert hub.normalize_shop_domain("my-store.evil.com") == ""
        assert hub.normalize_shop_domain("my store") == ""
        assert hub.normalize_shop_domain("") == ""
        assert hub.normalize_shop_domain("../../etc/passwd") == ""

    def test_shopify_authorize_url_requires_client_id(self, monkeypatch):
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_ID", None, raising=False)
        assert hub.shopify_authorize_url("my-store", "state.sig") is None

    def test_shopify_authorize_url_requires_valid_domain(self, monkeypatch):
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_ID", "cid", raising=False)
        assert hub.shopify_authorize_url("not a shop!", "state.sig") is None

    def test_shopify_authorize_url_is_templated_on_the_shop_domain(self, monkeypatch):
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_ID", "cid", raising=False)
        url = hub.shopify_authorize_url("my-store", "state.sig")
        assert url.startswith("https://my-store.myshopify.com/admin/oauth/authorize?")
        assert "client_id=cid" in url
        assert "state=state.sig" in url
        assert "%2Fconnectors%2Fshopify%2Fcallback" in url

    async def test_shopify_exchange_code_requires_configured_app(self, monkeypatch):
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_ID", None, raising=False)
        assert await hub.shopify_exchange_code("my-store", "code") is None

    async def test_shopify_exchange_code_success_includes_shop_domain(self, monkeypatch):
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_ID", "cid", raising=False)
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_SECRET", "csec", raising=False)
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"access_token": "shpat_real", "scope": "read_products"}
        cm = AsyncMock()
        cm.__aenter__.return_value.post = AsyncMock(return_value=resp)
        with patch("httpx.AsyncClient", return_value=cm):
            token = await hub.shopify_exchange_code("my-store", "authcode")
        assert token["access_token"] == "shpat_real"
        assert token["shop_domain"] == "my-store.myshopify.com"
        # Hit the shop's OWN token endpoint, not a fixed global URL.
        call_url = cm.__aenter__.return_value.post.call_args[0][0]
        assert call_url == "https://my-store.myshopify.com/admin/oauth/access_token"

    async def test_shopify_exchange_code_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_ID", "cid", raising=False)
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_SECRET", "csec", raising=False)
        resp = MagicMock(status_code=400, text="bad request")
        cm = AsyncMock()
        cm.__aenter__.return_value.post = AsyncMock(return_value=resp)
        with patch("httpx.AsyncClient", return_value=cm):
            token = await hub.shopify_exchange_code("my-store", "authcode")
        assert token is None

    def test_verify_shopify_hmac_accepts_correctly_signed_query(self, monkeypatch):
        import hashlib
        import hmac as hmac_mod

        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_SECRET", "csec", raising=False)
        params = {"code": "abc", "shop": "my-store.myshopify.com", "state": "st.sig"}
        message = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        signature = hmac_mod.new(b"csec", message.encode(), hashlib.sha256).hexdigest()
        assert hub.verify_shopify_hmac({**params, "hmac": signature}) is True

    def test_verify_shopify_hmac_rejects_tampered_query(self, monkeypatch):
        import hashlib
        import hmac as hmac_mod

        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_SECRET", "csec", raising=False)
        params = {"code": "abc", "shop": "my-store.myshopify.com", "state": "st.sig"}
        message = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        signature = hmac_mod.new(b"csec", message.encode(), hashlib.sha256).hexdigest()
        tampered = {**params, "code": "different-code", "hmac": signature}
        assert hub.verify_shopify_hmac(tampered) is False

    def test_verify_shopify_hmac_rejects_missing_hmac(self, monkeypatch):
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_SECRET", "csec", raising=False)
        assert hub.verify_shopify_hmac({"code": "abc", "shop": "my-store.myshopify.com"}) is False

    def test_verify_shopify_hmac_rejects_when_secret_unconfigured(self, monkeypatch):
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_SECRET", None, raising=False)
        assert hub.verify_shopify_hmac({"code": "abc", "hmac": "whatever"}) is False

    def test_connect_shows_shop_domain_form_when_configured(self, client, monkeypatch):
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_ID", "cid", raising=False)
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_SECRET", "csec", raising=False)
        r = client.get("/connectors/shopify/connect", cookies=_cookie())
        assert r.status_code == 200
        assert "shop" in r.text.lower()
        assert "myshopify.com" in r.text

    def test_connect_unconfigured_shopify_redirects_to_setup(self, client):
        r = client.get("/connectors/shopify/connect", cookies=_cookie(), follow_redirects=False)
        assert r.status_code == 303
        assert "s=setup" in r.headers.get("location", "")

    def test_connect_with_shop_redirects_to_shopify(self, client, monkeypatch):
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_ID", "cid", raising=False)
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_SECRET", "csec", raising=False)
        r = client.get(
            "/connectors/shopify/connect?shop=my-store",
            cookies=_cookie(),
            follow_redirects=False,
        )
        assert r.status_code == 307
        loc = r.headers.get("location", "")
        assert loc.startswith("https://my-store.myshopify.com/admin/oauth/authorize")
        assert any("aria_conn_state" in v for v in r.headers.get_list("set-cookie"))

    def test_connect_with_invalid_shop_shows_form_error(self, client, monkeypatch):
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_ID", "cid", raising=False)
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_SECRET", "csec", raising=False)
        r = client.get("/connectors/shopify/connect?shop=not a shop!", cookies=_cookie())
        assert r.status_code == 200
        assert "valid shop domain" in r.text.lower()

    def test_callback_rejects_missing_hmac(self, client, monkeypatch):
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_ID", "cid", raising=False)
        monkeypatch.setattr(settings, "SHOPIFY_CLIENT_SECRET", "csec", raising=False)
        r = client.get(
            "/connectors/shopify/connect?shop=my-store",
            cookies=_cookie(),
            follow_redirects=False,
        )
        state = r.headers.get("location", "").split("state=")[1].split("&")[0]
        cookies = {**_cookie(), **r.cookies}
        r2 = client.get(
            f"/connectors/shopify/callback?code=abc&state={state}&shop=my-store.myshopify.com",
            cookies=cookies,
            follow_redirects=False,
        )
        assert r2.status_code == 303
        assert "s=error" in r2.headers.get("location", "")
