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
