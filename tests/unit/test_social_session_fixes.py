"""Regression tests for bugs found auditing social_session.py:

1. save_session()/load_session() stored session cookies (auth_token, li_at,
   sessionid, c_user/xs — live credentials for the user's real social
   accounts) in PLAINTEXT in both Redis and Supabase, despite this module's
   own docstring explicitly claiming "ARIA stores the cookies encrypted."
   Now uses the same AES-256-GCM token_crypto module already used for
   connector OAuth tokens, with legacy-plaintext sessions still readable
   (decrypt() passes through unprefixed values unchanged).
2. test_session()'s Shopify test_endpoint/api_base contained a literal
   "{shop_name}" template placeholder that was never substituted anywhere
   in the codebase — every Shopify session-test request went to the
   invalid hostname "{shop_name}.myshopify.com" and failed every time.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.tools.social_session import SocialSessionManager

pytestmark = pytest.mark.asyncio


async def test_save_session_encrypts_cookies_at_rest():
    manager = SocialSessionManager()
    cookies = {"auth_token": "super-secret-value", "ct0": "csrf-value"}

    stored = {}

    class FakeCache:
        async def set(self, key, value, ttl_seconds=3600):
            stored["key"] = key
            stored["value"] = value
            return True

    with patch("apps.core.memory.redis_client.get_cache", return_value=FakeCache()):
        result = await manager.save_session("twitter", cookies)

    assert result["success"] is True
    stored_cookies = stored["value"]["cookies"]
    assert isinstance(stored_cookies, str)
    assert stored_cookies.startswith("enc:v1:")
    assert "super-secret-value" not in stored_cookies


async def test_load_session_decrypts_cookies():
    manager = SocialSessionManager()
    cookies = {"auth_token": "super-secret-value"}

    from apps.core.connectors.token_crypto import encrypt

    encrypted = encrypt(__import__("json").dumps(cookies))

    class FakeCache:
        async def get(self, key):
            return {"platform": "twitter", "cookies": encrypted, "active": True}

    with patch("apps.core.memory.redis_client.get_cache", return_value=FakeCache()):
        session = await manager.load_session("twitter")

    assert session["cookies"] == cookies


async def test_load_session_still_reads_legacy_plaintext_sessions():
    """A session saved before encryption shipped stored cookies as a raw
    dict, not an encrypted string — must still load correctly."""
    manager = SocialSessionManager()

    class FakeCache:
        async def get(self, key):
            return {"platform": "twitter", "cookies": {"auth_token": "legacy-value"}, "active": True}

    with patch("apps.core.memory.redis_client.get_cache", return_value=FakeCache()):
        session = await manager.load_session("twitter")

    assert session["cookies"] == {"auth_token": "legacy-value"}


async def test_shopify_test_session_substitutes_shop_name(monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.SHOPIFY_URL", "mystore.myshopify.com")
    manager = SocialSessionManager()

    fake_session = {
        "platform": "shopify",
        "cookies": {"_admin_session": "abc"},
        "user_info": {},
        "active": True,
    }

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {}
    captured = {}

    async def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        return fake_resp

    with patch.object(manager, "load_session", AsyncMock(return_value=fake_session)), patch.object(
        manager, "get_session_headers", AsyncMock(return_value={"Cookie": "x"})
    ), patch.object(manager._http, "get", fake_get):
        result = await manager.test_session("shopify")

    assert "{shop_name}" not in captured["url"]
    assert captured["url"] == "https://mystore.myshopify.com/admin/shop.json"
    assert result["success"] is True
