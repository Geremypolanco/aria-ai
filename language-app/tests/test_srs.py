from backend import db, srs
from backend.models import CEFRLevel


def _make_user(user_id="u1", level=CEFRLevel.A1):
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO users
               (id, display_name, native_lang, target_lang, level, interests, xp, streak_days,
                hearts, created_at, last_active_date)
               VALUES (?, 'Test', 'en', 'es', ?, '[]', 0, 0, 5, ?, '2000-01-01')""",
            (user_id, level.value, db.now_iso()),
        )


def test_schedule_review_progresses_intervals_on_success():
    _make_user()
    first = srs.schedule_review("u1", "greetings.hello", quality=4)
    assert first["repetitions"] == 1
    assert first["interval_days"] == 1

    second = srs.schedule_review("u1", "greetings.hello", quality=4)
    assert second["repetitions"] == 2
    assert second["interval_days"] == 3

    third = srs.schedule_review("u1", "greetings.hello", quality=5)
    assert third["repetitions"] == 3
    assert third["interval_days"] > 3


def test_schedule_review_resets_on_failure():
    _make_user()
    srs.schedule_review("u1", "greetings.hello", quality=5)
    failed = srs.schedule_review("u1", "greetings.hello", quality=1)
    assert failed["repetitions"] == 0
    assert failed["interval_days"] == 0.25


def test_grade_to_quality():
    assert srs.grade_to_quality(correct=False) == 1
    assert srs.grade_to_quality(correct=True, attempts_before_correct=0) == 5
    assert srs.grade_to_quality(correct=True, attempts_before_correct=3) == 3


def test_recent_mistakes_orders_by_mistake_count():
    _make_user()
    srs.schedule_review("u1", "a.word", quality=1)
    srs.schedule_review("u1", "a.word", quality=1)
    srs.schedule_review("u1", "b.word", quality=1)
    mistakes = srs.recent_mistakes("u1")
    assert mistakes[0] == "a.word"


def test_record_lesson_result_awards_xp_and_streak():
    _make_user()
    result = srs.record_lesson_result("u1", "A1-0", score=1.0)
    assert result["xp_gained"] == 30
    assert result["streak_days"] == 1
    assert result["mastered"] is True


def test_record_lesson_result_levels_up_after_enough_mastered_units():
    _make_user()
    from backend.curriculum import units_for_level

    unit_ids = [u.id for u in units_for_level(CEFRLevel.A1)]
    result = None
    for unit_id in unit_ids[: srs.UNITS_TO_UNLOCK_NEXT_LEVEL]:
        result = srs.record_lesson_result("u1", unit_id, score=1.0)
    assert result["leveled_up"] == CEFRLevel.A2.value


def test_lose_heart_floors_at_zero():
    _make_user()
    for _ in range(10):
        hearts = srs.lose_heart("u1")
    assert hearts == 0
