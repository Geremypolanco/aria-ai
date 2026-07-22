"""
auth_accounts.py — Email + password accounts for ARIA.

Lets ANY user create a real account (name + email + password) and sign straight
into the dashboard — no waitlist, no "GitHub only". This is the change that makes
ARIA actually usable by non-developers.

Passwords are hashed with PBKDF2-HMAC-SHA256 + a per-user salt (stdlib, no deps).
Accounts persist in the shared cache (Redis/Upstash). OAuth login (Google/GitHub)
keeps working alongside this — both end in the same signed session cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time

logger = logging.getLogger("aria.accounts")

_ACCOUNT_KEY = "aria:account:{email}"
_PBKDF2_ITERATIONS = 200_000
# Accounts don't expire; use a very long TTL to match the cache's set() contract.
_ACCOUNT_TTL = 3650 * 24 * 3600


def _norm(email: str) -> str:
    return (email or "").strip().lower()


def valid_email(email: str) -> bool:
    email = _norm(email)
    return "@" in email and "." in email.split("@")[-1] and len(email) <= 254


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
    return salt, dk.hex()


def _password_ok(password: str, salt: str, expected_hex: str) -> bool:
    _, got = hash_password(password or "", salt)
    return hmac.compare_digest(got, expected_hex or "")


async def _cache():
    from apps.core.memory.redis_client import get_cache

    return get_cache()


async def get_account(email: str) -> dict | None:
    try:
        raw = await (await _cache()).get(_ACCOUNT_KEY.format(email=_norm(email)))
        if raw:
            return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:  # noqa: BLE001
        pass
    return None


async def account_exists(email: str) -> bool:
    return (await get_account(email)) is not None


async def create_account(email: str, password: str, name: str = "") -> tuple[bool, str]:
    """Create an account. Returns (ok, error_message). error is '' on success."""
    email = _norm(email)
    if not valid_email(email):
        return False, "Enter a valid email address."
    if len(password or "") < 8:
        return False, "Password must be at least 8 characters."
    # Fast-path check (avoids the PBKDF2 cost for the common case), but the
    # real guarantee against a duplicate-signup race is the atomic write below
    # — two concurrent requests for the same email must not let the second
    # silently overwrite the first's password hash.
    if await account_exists(email):
        return False, "An account with this email already exists — try signing in."
    salt, pwhash = hash_password(password)
    record = {
        "email": email,
        "name": (name or "").strip()[:80],
        "salt": salt,
        "pwhash": pwhash,
        "created": int(time.time()),
    }
    try:
        created = await (await _cache()).set_if_not_exists(
            _ACCOUNT_KEY.format(email=email), json.dumps(record), ttl_seconds=_ACCOUNT_TTL
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[accounts] create persist failed for %s: %s", email, exc)
        return False, "Sign-up is temporarily unavailable — please try again in a moment."
    if not created:
        return False, "An account with this email already exists — try signing in."
    logger.info("[accounts] created %s", email)
    return True, ""


async def verify_credentials(email: str, password: str) -> dict | None:
    """Return a profile dict on valid credentials, else None."""
    acc = await get_account(email)
    if not acc:
        return None
    if _password_ok(password or "", acc.get("salt", ""), acc.get("pwhash", "")):
        return {"email": acc["email"], "name": acc.get("name", ""), "provider": "email"}
    return None
