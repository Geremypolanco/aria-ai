"""Dashboard data: XP, streak, hearts, due reviews, mastered units."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import auth, db, srs
from ..models import ProgressSnapshot
from .users import get_user_by_id_or_404

router = APIRouter(prefix="/api/progress", tags=["progress"])


@router.get("/{user_id}", response_model=ProgressSnapshot)
def get_progress(user_id: str, session: dict = Depends(auth.require_owner)) -> ProgressSnapshot:
    user = get_user_by_id_or_404(user_id)
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM unit_mastery WHERE user_id=? AND mastered=1", (user_id,))
        mastered = cur.fetchone()["c"]
    return ProgressSnapshot(
        user_id=user_id,
        xp=user.xp,
        streak_days=user.streak_days,
        hearts=user.hearts,
        level=user.level,
        due_reviews=srs.due_review_count(user_id),
        units_mastered=mastered,
    )
