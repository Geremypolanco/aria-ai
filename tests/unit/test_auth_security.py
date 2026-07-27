"""Security regression tests for apps/core/auth.py (audit remediation).

Covers: session sign/verify roundtrip, tamper rejection, session expiry, the
removal of the public fallback signing key, and OAuth-state CSRF binding.
"""

from __future__ import annotations

import time

from apps.core import auth


def test_sign_verify_roundtrip():
    tok = auth.sign_user("user@example.com", "User", "google")
    data = auth.verify_user(tok)
    assert data is not None
    assert data["email"] == "user@example.com"
    assert data["provider"] == "google"


def test_verify_rejects_tampered_signature():
    tok = auth.sign_user("user@example.com")
    body, _sig = tok.split(".", 1)
    assert auth.verify_user(body + ".deadbeef") is None


def test_verify_rejects_garbage():
    assert auth.verify_user(None) is None
    assert auth.verify_user("") is None
    assert auth.verify_user("nodothere") is None


def test_session_expiry(monkeypatch):
    tok = auth.sign_user("user@example.com")
    # Fast-forward beyond SESSION_MAX_AGE → token must be rejected.
    monkeypatch.setattr(auth.time, "time", lambda: time.time() + auth.SESSION_MAX_AGE + 10)
    assert auth.verify_user(tok) is None


def test_no_public_fallback_secret():
    # The old hardcoded public key must never be the signing secret.
    assert auth._secret() != b"aria-session-fallback"
    # Ephemeral key is long/random, not a guessable constant.
    assert len(auth._secret()) >= 16


def test_secret_no_longer_reuses_admin_password_or_aria_api_key(monkeypatch, caplog):
    """Regression (security hardening pass): _secret() used to fall back to
    ADMIN_PASSWORD or ARIA_API_KEY when SESSION_SECRET was unset — reusing a
    secret meant for a different purpose to sign sessions couples unrelated
    trust boundaries (rotating one silently invalidates/leaks into the
    other). It must now use ONLY SESSION_SECRET, falling to the ephemeral
    key (not a public constant) otherwise, with a CRITICAL-level warning."""
    monkeypatch.setattr(auth.settings, "SESSION_SECRET", None, raising=False)
    monkeypatch.setattr(
        auth.settings, "ADMIN_PASSWORD", "totally-different-admin-secret", raising=False
    )
    monkeypatch.setattr(auth.settings, "ARIA_API_KEY", "totally-different-api-key", raising=False)
    auth._warned_ephemeral = False

    import logging

    with caplog.at_level(logging.CRITICAL, logger="aria.auth"):
        secret = auth._secret()

    assert secret != b"totally-different-admin-secret"
    assert secret != b"totally-different-api-key"
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)


def test_secret_uses_session_secret_when_configured(monkeypatch):
    monkeypatch.setattr(auth.settings, "SESSION_SECRET", "the-real-session-secret", raising=False)
    assert auth._secret() == b"the-real-session-secret"


def test_oauth_state_roundtrip_and_binding():
    state = auth.make_state()
    # valid when the callback state matches the cookie we set
    assert auth.check_state(state, state) is True
    # signature-only (no cookie) still validates the signature+freshness
    assert auth.check_state(state) is True
    # a different cookie value (CSRF / mismatched browser) is rejected
    assert auth.check_state(state, auth.make_state()) is False
    # tampered / empty
    assert auth.check_state(None, None) is False
    assert auth.check_state("x.y", "x.y") is False


def test_oauth_state_expiry(monkeypatch):
    state = auth.make_state()
    monkeypatch.setattr(auth.time, "time", lambda: time.time() + auth.STATE_MAX_AGE + 10)
    assert auth.check_state(state, state) is False
