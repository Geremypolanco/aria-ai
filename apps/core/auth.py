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
import logging
import secrets
import time
import urllib.parse

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.auth")

USER_COOKIE = "aria_user"
OAUTH_STATE_COOKIE = "aria_oauth_state"

# Max session age (30 days) — tokens older than this are rejected.
SESSION_MAX_AGE = 60 * 60 * 24 * 30
# OAuth state is short-lived (10 minutes) to bound the CSRF window.
STATE_MAX_AGE = 600

# Ephemeral per-process signing key used ONLY when no real secret is configured.
# This replaces the previous hardcoded public constant, which allowed anyone to
# forge session cookies. An ephemeral key means sessions don't survive a restart
# or span multiple instances, but it is never publicly known.
_EPHEMERAL_SECRET = secrets.token_hex(32)
_warned_ephemeral = False


def _secret() -> bytes:
    """HMAC key for signing sessions + OAuth state.

    Preference: SESSION_SECRET → ADMIN_PASSWORD → ARIA_API_KEY → ephemeral.
    Never falls back to a public constant.
    """
    configured = (
        getattr(settings, "SESSION_SECRET", None)
        or getattr(settings, "ADMIN_PASSWORD", None)
        or getattr(settings, "ARIA_API_KEY", None)
    )
    if configured:
        return configured.encode()
    global _warned_ephemeral
    if not _warned_ephemeral:
        logger.warning(
            "No SESSION_SECRET/ADMIN_PASSWORD/ARIA_API_KEY set — using an ephemeral "
            "per-process session key. Sessions will not persist across restarts or "
            "multiple instances. Set SESSION_SECRET in production."
        )
        _warned_ephemeral = True
    return _EPHEMERAL_SECRET.encode()


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
        data = json.loads(base64.urlsafe_b64decode(b.encode()).decode())
        # Reject expired sessions (defence against forever-valid / stolen cookies).
        issued = int(data.get("t", 0))
        if issued <= 0 or (time.time() - issued) > SESSION_MAX_AGE:
            return None
        return data
    except Exception:
        return None


def make_state() -> str:
    """A signed, timestamped one-time state value for OAuth CSRF protection.

    The same value is also stored in a short-lived cookie and compared on
    callback (`check_state`), binding the flow to the initiating browser.
    """
    r = f"{secrets.token_urlsafe(12)}:{int(time.time())}"
    sig = hmac.new(_secret(), r.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{r}.{sig}"


def check_state(state: str | None, cookie_state: str | None = None) -> bool:
    """Validate the OAuth state: signature, freshness, and browser binding."""
    if not state or "." not in state:
        return False
    try:
        r, sig = state.rsplit(".", 1)
        if not hmac.compare_digest(
            sig, hmac.new(_secret(), r.encode(), hashlib.sha256).hexdigest()[:16]
        ):
            return False
        # freshness
        ts = int(r.rsplit(":", 1)[1])
        if (time.time() - ts) > STATE_MAX_AGE:
            return False
        # browser binding: the callback state must match the cookie we set
        return cookie_state is None or hmac.compare_digest(state, cookie_state)
    except Exception:
        return False


# ── provider config ────────────────────────────────────────────────────────


def google_enabled() -> bool:
    return bool(getattr(settings, "GOOGLE_CLIENT_ID", None))


def github_enabled() -> bool:
    return bool(getattr(settings, "GITHUB_CLIENT_ID", None))


def google_authorize_url(state: str) -> str | None:
    if not google_enabled():
        return None
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": f"{_base()}/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)


def github_authorize_url(state: str) -> str | None:
    if not github_enabled():
        return None
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": f"{_base()}/auth/github/callback",
        "scope": "read:user user:email",
        "state": state,
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
