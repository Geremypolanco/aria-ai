"""Tests for apps/core/memory/rls_client.py — the optional JWT-signed,
anon-key Supabase client that makes Postgres RLS a real, DB-enforced
isolation boundary for the memory tables (see database/user_memory_schema.sql
and apps/core/memory/user_facts.py's _client_for()).

Core things under test:
  - is_configured() is False unless SUPABASE_URL, SUPABASE_ANON_KEY, and
    SUPABASE_JWT_SECRET are ALL set — this is what keeps the feature off by
    default (no regression risk to the existing service-role-only path).
  - The signed JWT carries the caller's email as both `email` and `sub`,
    `role: authenticated`, and a short expiry — decodable with the same
    secret it was signed with, and NOT with a different one.
  - get_rls_client() returns None (never raises) whenever RLS isn't
    configured, no user_id is given, or client construction fails for any
    reason — every caller of this must have a safe fallback path.
  - When configured, get_rls_client() builds a client with the ANON key
    (never the service-role key) and calls postgrest.auth(<token>) so the
    JWT rides on every subsequent request.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import jwt as pyjwt

from apps.core.memory import rls_client


def _configured_settings(**overrides):
    base = dict(
        SUPABASE_URL="https://fake.supabase.co",
        SUPABASE_ANON_KEY="fake-anon-key",
        SUPABASE_JWT_SECRET="fake-jwt-secret",
    )
    base.update(overrides)
    return patch.multiple("apps.core.memory.rls_client.settings", **base)


def test_is_configured_false_by_default():
    with patch.multiple(
        "apps.core.memory.rls_client.settings",
        SUPABASE_URL="",
        SUPABASE_ANON_KEY="",
        SUPABASE_JWT_SECRET="",
    ):
        assert rls_client.is_configured() is False


def test_is_configured_false_when_only_anon_key_set():
    with _configured_settings(SUPABASE_JWT_SECRET=""):
        assert rls_client.is_configured() is False


def test_is_configured_false_when_only_jwt_secret_set():
    with _configured_settings(SUPABASE_ANON_KEY=""):
        assert rls_client.is_configured() is False


def test_is_configured_true_when_all_three_set():
    with _configured_settings():
        assert rls_client.is_configured() is True


def test_sign_user_jwt_carries_the_users_email_and_expires_soon():
    with _configured_settings():
        token = rls_client._sign_user_jwt("user-a@example.com")
        decoded = pyjwt.decode(
            token, "fake-jwt-secret", algorithms=["HS256"], audience="authenticated"
        )

    assert decoded["email"] == "user-a@example.com"
    assert decoded["sub"] == "user-a@example.com"
    assert decoded["role"] == "authenticated"
    assert decoded["exp"] - decoded["iat"] == rls_client._JWT_TTL_SECONDS


def test_sign_user_jwt_is_not_decodable_with_the_wrong_secret():
    with _configured_settings():
        token = rls_client._sign_user_jwt("user-a@example.com")

    import pytest

    with pytest.raises(pyjwt.InvalidSignatureError):
        pyjwt.decode(
            token, "some-other-secret", algorithms=["HS256"], audience="authenticated"
        )


def test_get_rls_client_returns_none_when_not_configured():
    with patch.multiple(
        "apps.core.memory.rls_client.settings",
        SUPABASE_URL="",
        SUPABASE_ANON_KEY="",
        SUPABASE_JWT_SECRET="",
    ):
        assert rls_client.get_rls_client("user-a@example.com") is None


def test_get_rls_client_returns_none_without_a_user_id():
    with _configured_settings():
        assert rls_client.get_rls_client("") is None
        assert rls_client.get_rls_client(None) is None


def test_get_rls_client_builds_client_with_anon_key_and_signed_jwt():
    fake_client = MagicMock()
    with (
        _configured_settings(),
        patch("supabase.create_client", return_value=fake_client) as fake_create_client,
    ):
        result = rls_client.get_rls_client("USER-A@example.com  ")

    assert result is fake_client
    fake_create_client.assert_called_once_with("https://fake.supabase.co", "fake-anon-key")
    fake_client.postgrest.auth.assert_called_once()
    (token,), _ = fake_client.postgrest.auth.call_args
    decoded = pyjwt.decode(token, "fake-jwt-secret", algorithms=["HS256"], audience="authenticated")
    # Email is normalized (stripped/lowercased) before it ever becomes a claim.
    assert decoded["email"] == "user-a@example.com"


def test_get_rls_client_returns_none_and_does_not_raise_on_unexpected_error():
    with (
        _configured_settings(),
        patch("supabase.create_client", side_effect=RuntimeError("boom")),
    ):
        assert rls_client.get_rls_client("user-a@example.com") is None
