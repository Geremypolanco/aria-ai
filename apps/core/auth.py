"""
auth.py — User OAuth login (Google + GitHub) and signed, stateless user sessions.

Users sign in with Google or GitHub and get their own limited dashboard (/app),
separate from the owner-only admin control panel (/admin). Sessions are a signed
cookie (HMAC), so no server-side session store is required.

Register these redirect URIs in the OAuth apps:
  Google: {BASE}/auth/google/callback
  GitHub: {BASE}/auth/github/callback
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

from apps.core.config import settings

USER_COOKIE = "aria_user"


def _secret() -> bytes:
    return (
        getattr(settings, "ADMIN_PASSWORD", None)
        or getattr(settings, "ARIA_API_KEY", None)
        or "aria-session-fallback"
    ).encode()


def _base() -> str:
    return (getattr(settings, "ARIA_BASE_URL", None) or "https://aria-ai.fly.dev").rstrip("/")


# ── signed user session ────────────────────────────────────────────────────


def sign_user(email: str, name: str = "", provider: str = "") -> str:
    payload = json.dumps(
        {"email": email, "name": name, "provider": provider, "t": int(time.time())},
        separators=(",", ":"),
    )
    b = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(_secret(), b.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{b}.{sig}"


def verify_user(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    try:
        b, sig = token.split(".", 1)
        expected = hmac.new(_secret(), b.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            return None
        return json.loads(base64.urlsafe_b64decode(b.encode()).decode())
    except Exception:
        return None


def _make_state() -> str:
    r = secrets.token_urlsafe(12)
    sig = hmac.new(_secret(), r.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{r}.{sig}"


def check_state(state: str | None) -> bool:
    if not state or "." not in state:
        return False
    try:
        r, sig = state.split(".", 1)
        return hmac.compare_digest(
            sig, hmac.new(_secret(), r.encode(), hashlib.sha256).hexdigest()[:16]
        )
    except Exception:
        return False


# ── provider config ────────────────────────────────────────────────────────


def google_enabled() -> bool:
    return bool(getattr(settings, "GOOGLE_CLIENT_ID", None))


def github_enabled() -> bool:
    return bool(getattr(settings, "GITHUB_CLIENT_ID", None))


def google_authorize_url() -> str | None:
    if not google_enabled():
        return None
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": f"{_base()}/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": _make_state(),
        "access_type": "online",
        "prompt": "select_account",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)


def github_authorize_url() -> str | None:
    if not github_enabled():
        return None
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": f"{_base()}/auth/github/callback",
        "scope": "read:user user:email",
        "state": _make_state(),
    }
    return "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode(params)


# ── token exchange → user profile ──────────────────────────────────────────


async def google_exchange(code: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            tok = await c.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": f"{_base()}/auth/google/callback",
                    "grant_type": "authorization_code",
                },
            )
            access = tok.json().get("access_token") if tok.status_code == 200 else None
            if not access:
                return None
            ui = await c.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access}"},
            )
            if ui.status_code != 200:
                return None
            d = ui.json()
            return {"email": d.get("email", ""), "name": d.get("name", ""), "provider": "google"}
    except Exception:
        return None


async def github_exchange(code: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            tok = await c.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "code": code,
                    "client_id": settings.GITHUB_CLIENT_ID,
                    "client_secret": settings.GITHUB_CLIENT_SECRET,
                    "redirect_uri": f"{_base()}/auth/github/callback",
                },
            )
            access = tok.json().get("access_token") if tok.status_code == 200 else None
            if not access:
                return None
            h = {"Authorization": f"Bearer {access}", "Accept": "application/json"}
            u = await c.get("https://api.github.com/user", headers=h)
            if u.status_code != 200:
                return None
            ud = u.json()
            email = ud.get("email")
            if not email:
                em = await c.get("https://api.github.com/user/emails", headers=h)
                if em.status_code == 200 and em.json():
                    emails = em.json()
                    email = next(
                        (e["email"] for e in emails if e.get("primary")), emails[0].get("email")
                    )
            return {
                "email": email or "",
                "name": ud.get("name") or ud.get("login", ""),
                "provider": "github",
            }
    except Exception:
        return None


async def remember_user(profile: dict) -> None:
    """Best-effort persistence of the user (email) for later plan/billing work."""
    try:
        from apps.core.memory.redis_client import get_cache

        await get_cache().rpush("aria:users", json.dumps(profile, ensure_ascii=False))
    except Exception:
        pass
