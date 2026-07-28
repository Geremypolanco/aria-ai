"""
apps/core/memory/rls_client.py — an optional, additive per-user Supabase
client that makes Postgres Row-Level Security a REAL, DB-enforced isolation
boundary for the memory tables, instead of the defense-in-depth-only policy
documented in database/user_memory_schema.sql.

Why this exists: the app's normal Supabase client
(apps/core/memory/supabase_client.py) authenticates with the SERVICE ROLE
key, which BYPASSES Row-Level Security by Postgres/Supabase design — no RLS
policy can constrain it, no matter what it says. And PostgREST (what
supabase-py's REST client talks to) is stateless per request with no
session continuity, so session-variable tricks like
`SET LOCAL app.current_user_id` never take effect against a
connection-pooled REST backend either.

The one mechanism that actually works for this app's custom, cookie-based
identity (there is no Supabase Auth integration) is: sign a JWT with the
project's real SUPABASE_JWT_SECRET, claim `role: authenticated` and the
caller's email, and present it as a Bearer token alongside the ANON key
(never the service-role key, which would defeat the point). RLS policies
then check the JWT's claims via
`current_setting('request.jwt.claims', true)::json ->> 'email'` — see the
updated policy in database/user_memory_schema.sql.

This module is entirely additive and OFF by default: without both
SUPABASE_ANON_KEY and SUPABASE_JWT_SECRET configured, is_configured() is
False and callers fall back to today's already-shipped, already-tested
service-role client — no regression risk to the existing memory system.
"""

from __future__ import annotations

import logging
import time

from apps.core.config import settings

logger = logging.getLogger("aria.rls_client")

# Short-lived and signed fresh per request/client — never cached or reused
# across users, so there's no window where a stale token could authorize
# the wrong caller.
_JWT_TTL_SECONDS = 300


def is_configured() -> bool:
    return bool(
        getattr(settings, "SUPABASE_URL", "")
        and getattr(settings, "SUPABASE_ANON_KEY", "")
        and getattr(settings, "SUPABASE_JWT_SECRET", "")
    )


def _sign_user_jwt(user_id: str) -> str:
    """Builds a Supabase-compatible JWT scoping every subsequent PostgREST
    request made with it to `user_id` alone, per the RLS policy's claim
    check."""
    import jwt

    now = int(time.time())
    payload = {
        "role": "authenticated",
        "email": user_id,
        "sub": user_id,
        "aud": "authenticated",
        "iat": now,
        "exp": now + _JWT_TTL_SECONDS,
    }
    return jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")


def get_rls_client(user_id: str):
    """Returns a fresh Supabase client (anon key + a JWT scoped to
    `user_id`) whose queries Postgres RLS will actually enforce, or None if
    RLS isn't configured or client construction fails for any reason —
    callers must fall back to the service-role client
    (apps/core/memory/supabase_client.py) in either case, since every query
    site already filters by user_id explicitly and doesn't depend on RLS to
    be correct."""
    user_id = (user_id or "").strip().lower()
    if not user_id or not is_configured():
        return None
    try:
        from supabase import create_client

        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
        token = _sign_user_jwt(user_id)
        client.postgrest.auth(token)
        return client
    except Exception as exc:
        logger.warning("[RLS] get_rls_client() failed, caller falls back: %s", exc)
        return None
