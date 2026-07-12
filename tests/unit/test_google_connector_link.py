"""
Tests for the Google/YouTube connector optimization (part B): these connectors
reuse the already-registered /auth/google/callback so the owner doesn't have to
register a separate connector redirect URI (the cause of redirect_uri_mismatch).
Critically, the normal Google *login* path must stay unchanged when the
aria_glink cookie is absent.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from apps.core import auth
from apps.core.config import settings
from apps.core.main import app

EMAIL = "glink@aria.test"


@pytest.fixture
def client():
    return TestClient(app)


def _auth_cookie():
    return {auth.USER_COOKIE: auth.sign_user(EMAIL, "G", "google")}


@pytest.fixture(autouse=True)
def _google_creds(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "gid.apps", raising=False)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "gsecret", raising=False)
    yield


def test_google_connect_reuses_login_callback(client):
    r = client.get("/connectors/google/connect", cookies=_auth_cookie(), follow_redirects=False)
    assert r.status_code == 307
    loc = r.headers["location"]
    assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    # redirect_uri must be the REGISTERED login callback, not /connectors/google/callback
    assert "%2Fauth%2Fgoogle%2Fcallback" in loc
    assert "%2Fconnectors%2Fgoogle%2Fcallback" not in loc
    setc = " ".join(r.headers.get_list("set-cookie"))
    assert "aria_glink=google" in setc


def test_youtube_connect_requests_youtube_scope(client):
    r = client.get("/connectors/youtube/connect", cookies=_auth_cookie(), follow_redirects=False)
    assert r.status_code == 307
    assert "youtube" in r.headers["location"]
    assert "aria_glink=youtube" in " ".join(r.headers.get_list("set-cookie"))


def test_callback_with_glink_stores_connector_token(client, mock_redis_patched):
    state = auth.make_state()
    from apps.core.connectors import oauth_hub as hub

    with patch.object(
        auth, "google_token_exchange", new=AsyncMock(return_value={"access_token": "AT", "refresh_token": "RT"})
    ):
        client.cookies.set(auth.OAUTH_STATE_COOKIE, state)
        client.cookies.set("aria_glink", "google")
        client.cookies.set(auth.USER_COOKIE, auth.sign_user(EMAIL, "G", "google"))
        r = client.get(
            f"/auth/google/callback?code=abc&state={state}", follow_redirects=False
        )
    assert r.status_code == 303
    assert "conn=google&s=connected" in r.headers["location"]
    import asyncio

    tok = asyncio.get_event_loop().run_until_complete(hub.get_token(EMAIL, "google"))
    assert tok and tok["access_token"] == "AT"


def test_callback_without_glink_is_still_login(client):
    """Regression guard: no aria_glink cookie → the original login path runs."""
    state = auth.make_state()
    with patch.object(
        auth, "google_exchange", new=AsyncMock(return_value={"email": EMAIL, "name": "G", "provider": "google"})
    ):
        client.cookies.set(auth.OAUTH_STATE_COOKIE, state)
        r = client.get(f"/auth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/app"  # logged in, not a connector redirect
