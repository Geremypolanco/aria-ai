"""Adaptive spaced-repetition scheduling (SM-2 family) and unit-mastery/leveling
logic — the core of "adapts to the user" instead of a fixed static course.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from . import db
from .models import CEFRLevel

MASTERY_SCORE_THRESHOLD = 0.8  # avg correctness required to consider a unit mastered
UNITS_TO_UNLOCK_NEXT_LEVEL = 3  # mastered units at current level before leveling up
MAX_HEARTS = 5
HEART_REGEN_MINUTES = 30


def grade_to_quality(correct: bool, attempts_before_correct: int = 0) -> int:
    """Maps a boolean result to an SM-2 quality score (0-5)."""
    if not correct:
        return 1
    return max(3, 5 - attempts_before_correct)


def schedule_review(user_id: str, vocab_key: str, quality: int) -> dict:
    """SM-2 update for a single vocabulary item. Returns the new schedule row."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT ease_factor, interval_days, repetitions, mistake_count "
            "FROM vocab_progress WHERE user_id=? AND vocab_key=?",
            (user_id, vocab_key),
        )
        row = cur.fetchone()
        ease = row["ease_factor"] if row else 2.5
        interval = row["interval_days"] if row else 0.0
        reps = row["repetitions"] if row else 0
        mistakes = row["mistake_count"] if row else 0

        if quality < 3:
            reps = 0
            interval = 0.25  # revisit within the same/next session (~6h)
            mistakes += 1
        else:
            if reps == 0:
                interval = 1
            elif reps == 1:
                interval = 3
            else:
                interval = round(interval * ease, 2)
            reps += 1

        ease = max(1.3, ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
        due_at = (datetime.now(UTC) + timedelta(days=interval)).isoformat()

        cur.execute(
            """
            INSERT INTO vocab_progress
                (user_id, vocab_key, ease_factor, interval_days, repetitions, due_at, last_result, mistake_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, vocab_key) DO UPDATE SET
                ease_factor=excluded.ease_factor,
                interval_days=excluded.interval_days,
                repetitions=excluded.repetitions,
                due_at=excluded.due_at,
                last_result=excluded.last_result,
                mistake_count=excluded.mistake_count
            """,
            (user_id, vocab_key, ease, interval, reps, due_at, "correct" if quality >= 3 else "incorrect", mistakes),
        )
        return {
            "vocab_key": vocab_key,
            "ease_factor": ease,
            "interval_days": interval,
            "repetitions": reps,
            "due_at": due_at,
        }


def due_review_keys(user_id: str, limit: int = 10) -> list[str]:
    with db.cursor() as cur:
        cur.execute(
            "SELECT vocab_key FROM vocab_progress WHERE user_id=? AND due_at<=? "
            "ORDER BY due_at ASC LIMIT ?",
            (user_id, datetime.now(UTC).isoformat(), limit),
        )
        return [r["vocab_key"] for r in cur.fetchall()]


def due_review_count(user_id: str) -> int:
    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM vocab_progress WHERE user_id=? AND due_at<=?",
            (user_id, datetime.now(UTC).isoformat()),
        )
        return cur.fetchone()["c"]


def recent_mistakes(user_id: str, limit: int = 5) -> list[str]:
    with db.cursor() as cur:
        cur.execute(
            "SELECT vocab_key FROM vocab_progress WHERE user_id=? AND mistake_count>0 "
            "ORDER BY mistake_count DESC, due_at ASC LIMIT ?",
            (user_id, limit),
        )
        return [r["vocab_key"] for r in cur.fetchall()]


def record_lesson_result(user_id: str, unit_id: str, score: float) -> dict:
    """Records a completed lesson, updates mastery, and awards XP/streak/hearts.
    Returns a summary the API can hand straight back to the client."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO lesson_history (user_id, unit_id, score, completed_at) VALUES (?,?,?,?)",
            (user_id, unit_id, score, db.now_iso()),
        )
        cur.execute(
            "SELECT best_score, attempts FROM unit_mastery WHERE user_id=? AND unit_id=?",
            (user_id, unit_id),
        )
        row = cur.fetchone()
        best = max(score, row["best_score"]) if row else score
        attempts = (row["attempts"] if row else 0) + 1
        mastered = 1 if best >= MASTERY_SCORE_THRESHOLD else 0
        cur.execute(
            """
            INSERT INTO unit_mastery (user_id, unit_id, best_score, attempts, mastered)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, unit_id) DO UPDATE SET
                best_score=excluded.best_score, attempts=excluded.attempts, mastered=excluded.mastered
            """,
            (user_id, unit_id, best, attempts, mastered),
        )

        xp_gain = round(10 + score * 20)
        cur.execute("SELECT xp, streak_days, hearts, last_active_date, level FROM users WHERE id=?", (user_id,))
        u = cur.fetchone()
        new_xp = u["xp"] + xp_gain
        today = db.today_str()
        streak = u["streak_days"]
        if u["last_active_date"] != today:
            yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
            streak = streak + 1 if u["last_active_date"] == yesterday else 1

        cur.execute(
            "UPDATE users SET xp=?, streak_days=?, last_active_date=? WHERE id=?",
            (new_xp, streak, today, user_id),
        )

        leveled_up = _maybe_level_up(cur, user_id, CEFRLevel(u["level"]))

        return {
            "xp_gained": xp_gain,
            "xp_total": new_xp,
            "streak_days": streak,
            "mastered": bool(mastered),
            "leveled_up": leveled_up,
        }


def _maybe_level_up(cur, user_id: str, current_level: CEFRLevel) -> str | None:
    from .curriculum import units_for_level

    unit_ids = [u.id for u in units_for_level(current_level)]
    if not unit_ids:
        return None
    placeholders = ",".join("?" for _ in unit_ids)
    cur.execute(
        f"SELECT COUNT(*) AS c FROM unit_mastery WHERE user_id=? AND mastered=1 AND unit_id IN ({placeholders})",
        (user_id, *unit_ids),
    )
    mastered_count = cur.fetchone()["c"]
    if mastered_count >= min(UNITS_TO_UNLOCK_NEXT_LEVEL, len(unit_ids)):
        next_level = current_level.next
        if next_level != current_level:
            cur.execute("UPDATE users SET level=? WHERE id=?", (next_level.value, user_id))
            return next_level.value
    return None


def lose_heart(user_id: str) -> int:
    with db.cursor() as cur:
        cur.execute("SELECT hearts FROM users WHERE id=?", (user_id,))
        hearts = max(0, cur.fetchone()["hearts"] - 1)
        cur.execute("UPDATE users SET hearts=? WHERE id=?", (hearts, user_id))
        return hearts


def regen_hearts_if_due(user_id: str) -> int:
    """Refills hearts to full the first time a user is seen on a new calendar day —
    a simplified stand-in for Duolingo's slow per-heart timer regeneration."""
    with db.cursor() as cur:
        cur.execute("SELECT hearts, last_active_date FROM users WHERE id=?", (user_id,))
        row = cur.fetchone()
        hearts = row["hearts"]
        today = db.today_str()
        if hearts < MAX_HEARTS and row["last_active_date"] != today:
            hearts = MAX_HEARTS
            cur.execute("UPDATE users SET hearts=? WHERE id=?", (hearts, user_id))
        return hearts
