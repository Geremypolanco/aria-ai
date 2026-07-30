"""User profile / onboarding endpoints — identity comes from Google Sign-In,
not client-supplied data. A profile can only be created for the email that
just completed the Google OAuth flow (see routers/auth.py), and can only be
read/updated by the session that owns it.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import auth, db
from ..config import settings
from ..models import CEFRLevel, UserProfile

router = APIRouter(prefix="/api/users", tags=["users"])


def get_user_by_id_or_404(user_id: str) -> UserProfile:
    """Plain data fetch, no auth check — used internally by other routers
    whose own route already enforced ownership via `auth.require_owner`."""
    with db.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE id=?", (user_id,))
        row = db.row_to_dict(cur.fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserProfile(**row)


def _set_session_cookie(response: Response, user_id: str, email: str) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.sign_session(user_id, email),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=auth.SESSION_MAX_AGE,
    )


class CreateUserRequest(BaseModel):
    display_name: str = ""
    native_lang: str
    target_lang: str
    level: CEFRLevel = CEFRLevel.A1
    interests: list[str] = Field(default_factory=list)


@router.post("", response_model=UserProfile)
def create_user(payload: CreateUserRequest, request: Request, response: Response) -> UserProfile:
    pending = auth.verify_pending(request.cookies.get(auth.PENDING_COOKIE))
    if not pending:
        raise HTTPException(status_code=401, detail="Sign in with Google first")
    email = pending["email"]

    with db.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email=?", (email,))
        existing = cur.fetchone()
    if existing:
        # Already onboarded on another device/tab — just re-establish the session.
        _set_session_cookie(response, existing["id"], email)
        response.delete_cookie(auth.PENDING_COOKIE)
        return get_user_by_id_or_404(existing["id"])

    user_id = uuid.uuid4().hex[:12]
    now = db.now_iso()
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO users
               (id, email, display_name, native_lang, target_lang, level, interests, xp, streak_days,
                hearts, created_at, last_active_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 5, ?, ?)""",
            (
                user_id,
                email,
                payload.display_name.strip() or pending.get("name") or "Learner",
                payload.native_lang,
                payload.target_lang,
                payload.level.value,
                json.dumps(payload.interests),
                now,
                db.today_str(),
            ),
        )

    _set_session_cookie(response, user_id, email)
    response.delete_cookie(auth.PENDING_COOKIE)
    return get_user_by_id_or_404(user_id)


@router.get("/me", response_model=UserProfile)
def get_me(session: dict = Depends(auth.require_session)) -> UserProfile:
    return get_user_by_id_or_404(session["user_id"])


@router.get("/{user_id}", response_model=UserProfile)
def get_user(user_id: str, session: dict = Depends(auth.require_owner)) -> UserProfile:
    return get_user_by_id_or_404(user_id)


class UpdateUserRequest(BaseModel):
    interests: list[str] | None = None
    level: CEFRLevel | None = None


@router.patch("/{user_id}", response_model=UserProfile)
def update_user(
    user_id: str, payload: UpdateUserRequest, session: dict = Depends(auth.require_owner)
) -> UserProfile:
    with db.cursor() as cur:
        if payload.interests is not None:
            cur.execute("UPDATE users SET interests=? WHERE id=?", (json.dumps(payload.interests), user_id))
        if payload.level is not None:
            cur.execute("UPDATE users SET level=? WHERE id=?", (payload.level.value, user_id))
    return get_user_by_id_or_404(user_id)
