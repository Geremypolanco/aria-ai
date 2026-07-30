"""Google Sign-In endpoints: kick off the OAuth flow, handle the callback,
expose the current session to the frontend, and sign out.

Also ships a `/auth/dev-login` escape hatch for running/testing without real
Google credentials — see `config.Settings.dev_login_enabled` for exactly when
it's available (off by default the moment real credentials are configured).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from .. import auth, db
from ..config import settings

router = APIRouter(tags=["auth"])


@router.get("/auth/google/login")
async def google_login() -> RedirectResponse:
    if not settings.google_configured:
        raise HTTPException(status_code=503, detail="Google Sign-In is not configured on this deployment")
    state = auth.make_state()
    resp = RedirectResponse(auth.google_authorize_url(state), status_code=307)
    resp.set_cookie(
        auth.STATE_COOKIE,
        state,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=auth.STATE_MAX_AGE,
    )
    return resp


@router.get("/auth/google/callback")
async def google_callback(request: Request) -> RedirectResponse:
    cookie_state = request.cookies.get(auth.STATE_COOKIE)
    if not auth.check_state(request.query_params.get("state"), cookie_state):
        return RedirectResponse("/?auth_error=state", status_code=303)

    code = request.query_params.get("code")
    if not code:
        return RedirectResponse("/?auth_error=nocode", status_code=303)

    profile = await auth.google_exchange(code)
    if not profile:
        return RedirectResponse("/?auth_error=google", status_code=303)

    with db.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email=?", (profile["email"],))
        existing = cur.fetchone()

    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(auth.STATE_COOKIE)

    if existing:
        resp.set_cookie(
            auth.SESSION_COOKIE,
            auth.sign_session(existing["id"], profile["email"]),
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            max_age=auth.SESSION_MAX_AGE,
        )
    else:
        resp.set_cookie(
            auth.PENDING_COOKIE,
            auth.sign_pending(profile["email"], profile["name"], profile["picture"]),
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            max_age=auth.PENDING_MAX_AGE,
        )
    return resp


@router.get("/api/session")
def get_session_status(request: Request) -> dict:
    session = auth.get_session(request)
    if session:
        return {"authenticated": True, "user_id": session["user_id"], "email": session["email"]}

    pending = auth.verify_pending(request.cookies.get(auth.PENDING_COOKIE))
    if pending:
        return {
            "authenticated": False,
            "pending": True,
            "email": pending["email"],
            "name": pending["name"],
            "picture": pending["picture"],
        }

    return {"authenticated": False, "pending": False, "dev_login_enabled": settings.dev_login_enabled}


@router.post("/auth/logout")
def logout() -> RedirectResponse:
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(auth.SESSION_COOKIE)
    resp.delete_cookie(auth.PENDING_COOKIE)
    resp.delete_cookie(auth.STATE_COOKIE)
    return resp


@router.get("/auth/dev-login")
def dev_login(email: str = Query(...), name: str = Query("")) -> RedirectResponse:
    """Simulates a completed Google login for local development/tests. Only
    reachable when `settings.dev_login_enabled` is true (see config.py) —
    disabled automatically once real GOOGLE_CLIENT_ID/SECRET are set, unless
    explicitly re-enabled via LINGUA_ALLOW_DEV_LOGIN=1."""
    if not settings.dev_login_enabled:
        raise HTTPException(status_code=404, detail="Not found")

    email = email.strip().lower()
    with db.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email=?", (email,))
        existing = cur.fetchone()

    resp = RedirectResponse("/", status_code=303)
    if existing:
        resp.set_cookie(
            auth.SESSION_COOKIE,
            auth.sign_session(existing["id"], email),
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            max_age=auth.SESSION_MAX_AGE,
        )
    else:
        resp.set_cookie(
            auth.PENDING_COOKIE,
            auth.sign_pending(email, name, ""),
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            max_age=auth.PENDING_MAX_AGE,
        )
    return resp
