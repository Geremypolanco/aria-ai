"""Google Sign-In + signed, stateless sessions for Lingua.

Independent implementation from ARIA's own login (apps/core/auth.py) — no
shared secret, cookie names, or OAuth client. Register this redirect URI in
Google Cloud Console for Lingua's own OAuth client:

    {LINGUA_PUBLIC_BASE_URL}/auth/google/callback

Sessions are a signed cookie (HMAC-SHA256), so no server-side session store
is needed — consistent with this app's SQLite-only, dependency-light design.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.parse

import httpx
from fastapi import HTTPException, Request

from .config import settings

SESSION_COOKIE = "lingua_session"
PENDING_COOKIE = "lingua_pending"
STATE_COOKIE = "lingua_oauth_state"

SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
PENDING_MAX_AGE = 60 * 30  # 30 minutes to finish onboarding after first Google login
STATE_MAX_AGE = 600  # 10 minutes, bounds the OAuth CSRF window


def _secret() -> bytes:
    return settings.session_secret.encode()


def _sign(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"))
    b = base64.urlsafe_b64encode(raw.encode()).decode()
    sig = hmac.new(_secret(), b.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{b}.{sig}"


def _unsign(token: str | None, max_age: int) -> dict | None:
    if not token or "." not in token:
        return None
    try:
        b, sig = token.rsplit(".", 1)
        expected = hmac.new(_secret(), b.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(b.encode()).decode())
        issued = int(data.get("t", 0))
        if issued <= 0 or (time.time() - issued) > max_age:
            return None
        return data
    except Exception:
        return None


# ── session (full profile exists) ───────────────────────────────────────────


def sign_session(user_id: str, email: str) -> str:
    return _sign({"user_id": user_id, "email": email, "t": int(time.time())})


def verify_session(token: str | None) -> dict | None:
    return _unsign(token, SESSION_MAX_AGE)


# ── pending (Google identity confirmed, onboarding not finished yet) ───────


def sign_pending(email: str, name: str, picture: str) -> str:
    return _sign({"email": email, "name": name, "picture": picture, "t": int(time.time())})


def verify_pending(token: str | None) -> dict | None:
    return _unsign(token, PENDING_MAX_AGE)


# ── OAuth CSRF state ─────────────────────────────────────────────────────────


def make_state() -> str:
    r = f"{secrets.token_urlsafe(12)}:{int(time.time())}"
    sig = hmac.new(_secret(), r.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{r}.{sig}"


def check_state(state: str | None, cookie_state: str | None) -> bool:
    if not state or "." not in state:
        return False
    try:
        r, sig = state.rsplit(".", 1)
        expected = hmac.new(_secret(), r.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected):
            return False
        ts = int(r.rsplit(":", 1)[1])
        if (time.time() - ts) > STATE_MAX_AGE:
            return False
        return cookie_state is not None and hmac.compare_digest(state, cookie_state)
    except Exception:
        return False


# ── Google OAuth ─────────────────────────────────────────────────────────────


def google_authorize_url(state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": f"{settings.public_base_url}/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)


async def google_exchange(code: str) -> dict | None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": f"{settings.public_base_url}/auth/google/callback",
                "grant_type": "authorization_code",
            },
        )
        if token_res.status_code != 200:
            return None
        access_token = token_res.json().get("access_token")
        if not access_token:
            return None
        info_res = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if info_res.status_code != 200:
            return None
        info = info_res.json()
        email = info.get("email")
        if not email:
            return None
        return {"email": email.lower(), "name": info.get("name", ""), "picture": info.get("picture", "")}


# ── FastAPI auth dependencies ────────────────────────────────────────────────


def get_session(request: Request) -> dict | None:
    return verify_session(request.cookies.get(SESSION_COOKIE))


def require_session(request: Request) -> dict:
    session = get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Sign in with Google first")
    return session


def require_owner(user_id: str, request: Request) -> dict:
    """Route dependency for `/{user_id}`-shaped endpoints: the signed-in
    session must belong to the same user whose data is being requested."""
    session = require_session(request)
    if session["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not your profile")
    return session
