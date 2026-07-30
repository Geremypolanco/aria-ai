from backend.curriculum import (
    LessonRequest,
    all_units,
    build_conversation_system_prompt,
    build_exercise_generation_prompt,
    exercise_mix_for,
    get_unit,
    units_for_level,
)
from backend.models import CEFRLevel, ExerciseType


def test_cefr_level_progression():
    assert CEFRLevel.A1.next == CEFRLevel.A2
    assert CEFRLevel.C2.next == CEFRLevel.NATIVE
    assert CEFRLevel.NATIVE.next == CEFRLevel.NATIVE  # caps out
    assert CEFRLevel.A1.uses_translation is False
    assert CEFRLevel.A2.uses_translation is True


def test_a1_uses_immersion_exercise_mix():
    mix = exercise_mix_for(CEFRLevel.A1)
    assert ExerciseType.IMAGE_MATCH in mix
    assert ExerciseType.FREE_CONVERSATION_PROMPT not in mix


def test_b1_unlocks_free_conversation():
    mix = exercise_mix_for(CEFRLevel.B1)
    assert ExerciseType.FREE_CONVERSATION_PROMPT in mix


def test_units_are_ordered_and_unique_ids():
    units = units_for_level(CEFRLevel.A1)
    assert len(units) > 0
    ids = [u.id for u in units]
    assert len(ids) == len(set(ids))
    assert [u.order for u in units] == sorted(u.order for u in units)


def test_get_unit_roundtrips_through_all_units():
    any_unit = all_units()[0]
    assert get_unit(any_unit.id).id == any_unit.id
    assert get_unit("does-not-exist") is None


def test_exercise_prompt_hides_translation_for_a1():
    unit = units_for_level(CEFRLevel.A1)[0]
    req = LessonRequest(unit=unit, native_lang="English", target_lang="Spanish", interests=[], recent_mistakes=[])
    prompt = build_exercise_generation_prompt(req)
    assert "Do NOT include any native-language translation" in prompt


def test_exercise_prompt_includes_translation_for_a2():
    unit = units_for_level(CEFRLevel.A2)[0]
    req = LessonRequest(unit=unit, native_lang="English", target_lang="Spanish", interests=[], recent_mistakes=[])
    prompt = build_exercise_generation_prompt(req)
    assert "Include the native-language translation" in prompt


def test_exercise_prompt_weaves_in_mistakes_and_interests():
    unit = units_for_level(CEFRLevel.A2)[0]
    req = LessonRequest(
        unit=unit,
        native_lang="English",
        target_lang="Spanish",
        interests=["football"],
        recent_mistakes=["greetings.hello"],
    )
    prompt = build_exercise_generation_prompt(req)
    assert "football" in prompt
    assert "greetings.hello" in prompt


def test_conversation_prompt_adapts_to_level():
    beginner = build_conversation_system_prompt("Spanish", "English", CEFRLevel.A1, [])
    advanced = build_conversation_system_prompt("Spanish", "English", CEFRLevel.C2, [])
    assert "very simple" in beginner
    assert "native pace" in advanced
