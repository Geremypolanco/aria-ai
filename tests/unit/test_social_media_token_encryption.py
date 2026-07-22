"""Regression test: SocialMediaManager.save_account() stored OAuth
access_token/refresh_token in plaintext in Supabase — exactly the scenario
token_crypto.py's own docstring warns about ("a Redis dump would let an
attacker post to every connected LinkedIn / Google / TikTok / X account").
This is a live, reachable path: social_content_tools.py's
post_via_oauth_accounts() calls SocialMediaManager().list_connected_accounts()
/.post_content(), which depend on get_account_token() to retrieve tokens.
Now encrypted at rest with the same AES-256-GCM module already used for
connector tokens, with legacy-plaintext tokens still readable.

Note: the real `apps.core.memory.supabase_client` module imports the
`supabase` SDK at module level, which isn't installed in this test
environment (it's always imported lazily inside a try/except in production
code for exactly this reason) — so this test injects a fake module into
sys.modules rather than patching the real one.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from apps.core.tools.social_media import SocialMediaManager

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fake_supabase_module(monkeypatch):
    """Injects a fake apps.core.memory.supabase_client module so the
    lazy `from apps.core.memory.supabase_client import get_db` inside
    save_account()/get_account_token() resolves to our test double instead
    of requiring the real (uninstalled) supabase SDK."""
    mock_db = MagicMock()
    fake_module = types.ModuleType("apps.core.memory.supabase_client")
    fake_module.get_db = lambda: mock_db
    monkeypatch.setitem(sys.modules, "apps.core.memory.supabase_client", fake_module)
    return mock_db


async def test_save_account_encrypts_tokens_at_rest(fake_supabase_module):
    manager = SocialMediaManager()
    captured = {}

    mock_table = MagicMock()
    fake_supabase_module._client.table.return_value = mock_table
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.execute.return_value = MagicMock(data=[])

    def fake_insert(record):
        captured["record"] = record
        return mock_table

    mock_table.insert.side_effect = fake_insert

    ok = await manager.save_account(
        "linkedin", "super-secret-access-token", "super-secret-refresh-token", 3600, {"id": "1"}
    )

    assert ok is True
    assert captured["record"]["access_token"].startswith("enc:v1:")
    assert captured["record"]["refresh_token"].startswith("enc:v1:")
    assert "super-secret-access-token" not in captured["record"]["access_token"]


async def test_get_account_token_decrypts_stored_token(fake_supabase_module):
    from apps.core.connectors.token_crypto import encrypt

    manager = SocialMediaManager()
    encrypted = encrypt("super-secret-access-token")

    mock_table = MagicMock()
    fake_supabase_module._client.table.return_value = mock_table
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.limit.return_value = mock_table
    mock_table.execute.return_value = MagicMock(
        data=[{"access_token": encrypted, "refresh_token": None, "expires_at": None}]
    )

    token = await manager.get_account_token("linkedin")

    assert token == "super-secret-access-token"


async def test_get_account_token_still_reads_legacy_plaintext_tokens(fake_supabase_module):
    manager = SocialMediaManager()

    mock_table = MagicMock()
    fake_supabase_module._client.table.return_value = mock_table
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.limit.return_value = mock_table
    mock_table.execute.return_value = MagicMock(
        data=[{"access_token": "legacy-plaintext-token", "refresh_token": None, "expires_at": None}]
    )

    token = await manager.get_account_token("linkedin")

    assert token == "legacy-plaintext-token"
