"""
token_crypto.py — AES-256-GCM encryption for connector OAuth tokens at rest.

Connector access/refresh tokens must NEVER sit in the datastore in plaintext: a
Redis dump would let an attacker post to every connected LinkedIn / Google /
TikTok / X account. This wraps tokens in authenticated AES-256-GCM.

The master key is derived (SHA-256 → 32 bytes) from a server secret that lives
only in Fly secrets — a dedicated `CONNECTOR_ENC_KEY` if set, otherwise the
existing `SESSION_SECRET` / `ARIA_API_KEY`. Nothing key-related is ever stored
next to the ciphertext.

Format: ``enc:v1:`` + urlsafe_b64(nonce[12] || ciphertext||tag). The prefix lets
`decrypt()` pass through any legacy plaintext value unchanged, so enabling this
never breaks tokens written before it shipped.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("aria.token_crypto")

_PREFIX = "enc:v1:"
_AAD = b"aria-connector-token"


def _key() -> bytes:
    from apps.core.config import settings

    material = (
        getattr(settings, "CONNECTOR_ENC_KEY", None)
        or getattr(settings, "SESSION_SECRET", None)
        or getattr(settings, "ARIA_API_KEY", None)
        or ""
    )
    if not material:
        # In prod ARIA_API_KEY is always set; this only trips in a bare local env.
        logger.warning(
            "No CONNECTOR_ENC_KEY/SESSION_SECRET/ARIA_API_KEY set — connector token "
            "encryption is using a weak derived key. Set CONNECTOR_ENC_KEY in prod."
        )
    # SHA-256 gives exactly the 32 bytes AES-256 needs; the salt namespaces the key.
    return hashlib.sha256(b"aria-connector-tokens:v1:" + material.encode()).digest()


def is_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith(_PREFIX)


def encrypt(plaintext: str) -> str:
    """Encrypt a token string → an ``enc:v1:`` blob (authenticated AES-256-GCM)."""
    data = (plaintext or "").encode("utf-8")
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, data, _AAD)
    return _PREFIX + base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def decrypt(blob: object) -> str:
    """Decrypt an ``enc:v1:`` blob. Legacy plaintext (no prefix) is returned as-is.

    Raises ``cryptography.exceptions.InvalidTag`` if a v1 blob was tampered with —
    callers already guard token reads with try/except, so a bad blob yields no token.
    """
    if not is_encrypted(blob):
        return blob  # legacy plaintext written before encryption shipped
    raw = base64.urlsafe_b64decode(blob[len(_PREFIX) :].encode("ascii"))
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(_key()).decrypt(nonce, ct, _AAD).decode("utf-8")
