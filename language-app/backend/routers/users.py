"""User profile / onboarding endpoints."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..models import CEFRLevel, UserProfile

router = APIRouter(prefix="/api/users", tags=["users"])


class CreateUserRequest(BaseModel):
    display_name: str
    native_lang: str
    target_lang: str
    level: CEFRLevel = CEFRLevel.A1
    interests: list[str] = Field(default_factory=list)


@router.post("", response_model=UserProfile)
def create_user(payload: CreateUserRequest) -> UserProfile:
    user_id = uuid.uuid4().hex[:12]
    now = db.now_iso()
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO users
               (id, display_name, native_lang, target_lang, level, interests, xp, streak_days,
                hearts, created_at, last_active_date)
               VALUES (?, ?, ?, ?, ?, ?, 0, 0, 5, ?, ?)""",
            (
                user_id,
                payload.display_name,
                payload.native_lang,
                payload.target_lang,
                payload.level.value,
                json.dumps(payload.interests),
                now,
                db.today_str(),
            ),
        )
    return get_user(user_id)


@router.get("/{user_id}", response_model=UserProfile)
def get_user(user_id: str) -> UserProfile:
    with db.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE id=?", (user_id,))
        row = db.row_to_dict(cur.fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserProfile(**row)


class UpdateUserRequest(BaseModel):
    interests: list[str] | None = None
    level: CEFRLevel | None = None


@router.patch("/{user_id}", response_model=UserProfile)
def update_user(user_id: str, payload: UpdateUserRequest) -> UserProfile:
    get_user(user_id)  # 404s if missing
    with db.cursor() as cur:
        if payload.interests is not None:
            cur.execute("UPDATE users SET interests=? WHERE id=?", (json.dumps(payload.interests), user_id))
        if payload.level is not None:
            cur.execute("UPDATE users SET level=? WHERE id=?", (payload.level.value, user_id))
    return get_user(user_id)
