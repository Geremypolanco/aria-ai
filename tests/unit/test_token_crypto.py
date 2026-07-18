"""
Tests for connector token encryption at rest (apps/core/connectors/token_crypto.py)
and its integration with oauth_hub.save_token / get_token.

Verifies: AES-256-GCM roundtrip, ciphertext is opaque + authenticated (tamper →
no token), legacy plaintext passes through unchanged, and tokens are stored
ENCRYPTED but read back in the clear.
"""

from __future__ import annotations

import json

import pytest

from apps.core.config import settings
from apps.core.connectors import oauth_hub, token_crypto


@pytest.fixture(autouse=True)
def _stable_key(monkeypatch):
    # Deterministic key material so tests don't depend on ambient secrets.
    monkeypatch.setattr(settings, "CONNECTOR_ENC_KEY", "unit-test-master-key", raising=False)
    yield


# ── CRYPTO PRIMITIVES ─────────────────────────────────────────────────────────


def test_roundtrip():
    blob = token_crypto.encrypt("ya29.super-secret-access-token")
    assert token_crypto.decrypt(blob) == "ya29.super-secret-access-token"


def test_ciphertext_is_opaque_and_prefixed():
    secret = "refresh-token-abc123"
    blob = token_crypto.encrypt(secret)
    assert blob.startswith("enc:v1:")
    assert secret not in blob  # plaintext never appears in the stored value
    assert token_crypto.is_encrypted(blob)
    assert not token_crypto.is_encrypted(secret)


def test_nonce_makes_each_ciphertext_unique():
    a = token_crypto.encrypt("same")
    b = token_crypto.encrypt("same")
    assert a != b  # random nonce per encryption
    assert token_crypto.decrypt(a) == token_crypto.decrypt(b) == "same"


def test_legacy_plaintext_passthrough():
    # A value written before encryption shipped (plain JSON) is returned unchanged.
    legacy = '{"access_token": "old"}'
    assert token_crypto.decrypt(legacy) == legacy


def test_tampering_is_detected():
    from cryptography.exceptions import InvalidTag

    blob = token_crypto.encrypt("token")
    # Flip a character in the ciphertext body.
    body = list(blob)
    body[-2] = "A" if body[-2] != "A" else "B"
    tampered = "".join(body)
    with pytest.raises((InvalidTag, Exception)):
        token_crypto.decrypt(tampered)


def test_empty_string():
    assert token_crypto.decrypt(token_crypto.encrypt("")) == ""


# ── INTEGRATION WITH oauth_hub ────────────────────────────────────────────────


class FakeCache:
    def __init__(self):
        self.kv = {}

    async def get(self, key):
        return self.kv.get(key)

    async def set(self, key, value, ttl_seconds=None):
        self.kv[key] = value


async def test_save_token_stores_encrypted_and_get_decrypts(monkeypatch):
    cache = FakeCache()
    monkeypatch.setattr("apps.core.memory.redis_client.get_cache", lambda: cache)

    token = {
        "access_token": "at-live-123",
        "refresh_token": "rt-live-456",
        "scope": "w_member_social",
        "expires_in": 3600,
    }
    await oauth_hub.save_token("user@aria.test", "linkedin", token)

    # What's actually stored is an encrypted blob — not the plaintext token.
    stored = cache.kv["aria:conn:user@aria.test:linkedin"]
    assert stored.startswith("enc:v1:")
    assert "at-live-123" not in stored
    assert "rt-live-456" not in stored

    # Read back → decrypted record with the real tokens.
    got = await oauth_hub.get_token("user@aria.test", "linkedin")
    assert got["access_token"] == "at-live-123"
    assert got["refresh_token"] == "rt-live-456"
    assert got["scope"] == "w_member_social"


async def test_get_token_reads_legacy_plaintext(monkeypatch):
    # Simulate a token written before encryption existed (plain JSON in cache).
    cache = FakeCache()
    cache.kv["aria:conn:old@aria.test:slack"] = json.dumps(
        {"access_token": "legacy", "refresh_token": ""}
    )
    monkeypatch.setattr("apps.core.memory.redis_client.get_cache", lambda: cache)

    got = await oauth_hub.get_token("old@aria.test", "slack")
    assert got["access_token"] == "legacy"
