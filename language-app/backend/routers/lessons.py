"""Adaptive lesson delivery: skill path, exercise generation, answer grading."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth, db, srs
from ..curriculum import LessonRequest, all_units, get_unit
from ..hf_client import hf_client
from ..models import CEFRLevel, Exercise
from .users import get_user_by_id_or_404

router = APIRouter(prefix="/api/lessons", tags=["lessons"])


class UnitNode(BaseModel):
    id: str
    topic: str
    level: CEFRLevel
    order: int
    state: str  # "locked" | "available" | "mastered"
    best_score: float = 0.0


@router.get("/{user_id}/path", response_model=list[UnitNode])
def get_path(user_id: str, session: dict = Depends(auth.require_owner)) -> list[UnitNode]:
    user = get_user_by_id_or_404(user_id)
    with db.cursor() as cur:
        cur.execute("SELECT unit_id, best_score, mastered FROM unit_mastery WHERE user_id=?", (user_id,))
        mastery = {r["unit_id"]: r for r in cur.fetchall()}

    nodes: list[UnitNode] = []
    for unit in all_units():
        m = mastery.get(unit.id)
        best = m["best_score"] if m else 0.0
        if m and m["mastered"]:
            state = "mastered"
        elif unit.level.rank < user.level.rank:
            state = "mastered"  # fully passed levels show as complete
        elif unit.level.rank > user.level.rank:
            state = "locked"
        else:
            state = "available"
        nodes.append(
            UnitNode(id=unit.id, topic=unit.topic, level=unit.level, order=unit.order, state=state, best_score=best)
        )
    return nodes


@router.get("/{user_id}/unit/{unit_id}", response_model=list[Exercise])
async def get_lesson_exercises(
    user_id: str, unit_id: str, session: dict = Depends(auth.require_owner)
) -> list[Exercise]:
    user = get_user_by_id_or_404(user_id)
    unit = get_unit(unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="Unit not found")
    if unit.level.rank > user.level.rank:
        raise HTTPException(status_code=403, detail="Unit is locked")

    req = LessonRequest(
        unit=unit,
        native_lang=user.native_lang,
        target_lang=user.target_lang,
        interests=user.interests,
        recent_mistakes=srs.recent_mistakes(user_id),
    )
    return await hf_client.generate_exercises(req)


class AnswerRequest(BaseModel):
    vocab_key: str = ""
    correct: bool
    attempts_before_correct: int = 0


class AnswerResult(BaseModel):
    hearts: int
    srs: dict = Field(default_factory=dict)


@router.post("/{user_id}/answer", response_model=AnswerResult)
def submit_answer(user_id: str, payload: AnswerRequest, session: dict = Depends(auth.require_owner)) -> AnswerResult:
    get_user_by_id_or_404(user_id)
    hearts = None
    if not payload.correct:
        hearts = srs.lose_heart(user_id)

    schedule = {}
    if payload.vocab_key:
        quality = srs.grade_to_quality(payload.correct, payload.attempts_before_correct)
        schedule = srs.schedule_review(user_id, payload.vocab_key, quality)

    if hearts is None:
        with db.cursor() as cur:
            cur.execute("SELECT hearts FROM users WHERE id=?", (user_id,))
            hearts = cur.fetchone()["hearts"]

    return AnswerResult(hearts=hearts, srs=schedule)


class CompleteLessonRequest(BaseModel):
    unit_id: str
    score: float  # 0.0 - 1.0


@router.post("/{user_id}/complete")
def complete_lesson(user_id: str, payload: CompleteLessonRequest, session: dict = Depends(auth.require_owner)) -> dict:
    get_user_by_id_or_404(user_id)
    srs.regen_hearts_if_due(user_id)
    return srs.record_lesson_result(user_id, payload.unit_id, max(0.0, min(1.0, payload.score)))
