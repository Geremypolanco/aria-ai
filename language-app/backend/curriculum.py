"""Curriculum: the language-agnostic skill tree (Duolingo-style path) plus the
prompt templates used to have the HF model generate the actual target-language
content for a given topic, level, and user (Rosetta-Stone-style immersion at
the early levels, free conversation practice from B1 onward).

The topic list itself is language-agnostic — the LLM produces the target-language
vocabulary/sentences/questions at request time, tailored to the learner's native
language, interests, and past mistakes. This is what lets one curriculum serve
any language pair instead of hand-authoring word lists per language.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import CEFRLevel, ExerciseType, Unit

# (topic, description_native placeholder key) per level, in learning order.
_TOPICS_BY_LEVEL: dict[CEFRLevel, list[str]] = {
    CEFRLevel.A1: [
        "Greetings & introductions",
        "Numbers & counting",
        "Family",
        "Food & drink",
        "Colors & shapes",
        "Everyday objects",
        "Days & time",
    ],
    CEFRLevel.A2: [
        "Daily routines",
        "Shopping",
        "Directions & places in town",
        "Weather",
        "Hobbies",
        "Past tense: simple stories",
        "Making plans",
    ],
    CEFRLevel.B1: [
        "Travel & transportation",
        "Health & the body",
        "Work & school",
        "Opinions & preferences",
        "Describing people",
        "Telling a past experience",
        "Free conversation: small talk",
    ],
    CEFRLevel.B2: [
        "News & current events",
        "Emotions & relationships",
        "Giving advice",
        "Hypotheticals",
        "Debating opinions",
        "Free conversation: everyday problems",
    ],
    CEFRLevel.C1: [
        "Idioms & colloquialisms",
        "Nuanced arguments",
        "Professional communication",
        "Humor & wordplay",
        "Free conversation: abstract topics",
    ],
    CEFRLevel.C2: [
        "Regional accents & slang",
        "Literary & rhetorical language",
        "Rapid native-speed conversation",
        "Free conversation: any topic, native pace",
    ],
    CEFRLevel.NATIVE: [
        "Open conversation practice",
    ],
}

# Exercise mix per level — early levels lean on image/audio immersion
# (Rosetta Stone), later levels lean on translation, production, and free
# conversation (Duolingo's later skill tree + real dialogue practice).
_EXERCISE_MIX: dict[CEFRLevel, list[ExerciseType]] = {
    CEFRLevel.A1: [
        ExerciseType.IMAGE_MATCH,
        ExerciseType.IMAGE_MATCH,
        ExerciseType.LISTEN_TYPE,
        ExerciseType.MULTIPLE_CHOICE,
        ExerciseType.SPEAK_REPEAT,
    ],
    CEFRLevel.A2: [
        ExerciseType.IMAGE_MATCH,
        ExerciseType.TRANSLATE_TO_TARGET,
        ExerciseType.TRANSLATE_TO_NATIVE,
        ExerciseType.FILL_BLANK,
        ExerciseType.SPEAK_REPEAT,
    ],
    CEFRLevel.B1: [
        ExerciseType.TRANSLATE_TO_TARGET,
        ExerciseType.FILL_BLANK,
        ExerciseType.MULTIPLE_CHOICE,
        ExerciseType.SPEAK_REPEAT,
        ExerciseType.FREE_CONVERSATION_PROMPT,
    ],
    CEFRLevel.B2: [
        ExerciseType.TRANSLATE_TO_TARGET,
        ExerciseType.FILL_BLANK,
        ExerciseType.FREE_CONVERSATION_PROMPT,
        ExerciseType.FREE_CONVERSATION_PROMPT,
    ],
    CEFRLevel.C1: [
        ExerciseType.FILL_BLANK,
        ExerciseType.FREE_CONVERSATION_PROMPT,
        ExerciseType.FREE_CONVERSATION_PROMPT,
    ],
    CEFRLevel.C2: [
        ExerciseType.FREE_CONVERSATION_PROMPT,
        ExerciseType.FREE_CONVERSATION_PROMPT,
    ],
    CEFRLevel.NATIVE: [ExerciseType.FREE_CONVERSATION_PROMPT],
}


def units_for_level(level: CEFRLevel) -> list[Unit]:
    topics = _TOPICS_BY_LEVEL.get(level, [])
    return [
        Unit(
            id=f"{level.value}-{i}",
            topic=topic,
            level=level,
            order=i,
            title_native=topic,
            description_native=f"{level.value} unit: {topic}",
        )
        for i, topic in enumerate(topics)
    ]


def all_units() -> list[Unit]:
    units: list[Unit] = []
    for level in CEFRLevel:
        units.extend(units_for_level(level))
    return units


def get_unit(unit_id: str) -> Unit | None:
    for unit in all_units():
        if unit.id == unit_id:
            return unit
    return None


def exercise_mix_for(level: CEFRLevel) -> list[ExerciseType]:
    return _EXERCISE_MIX.get(level, [ExerciseType.FREE_CONVERSATION_PROMPT])


@dataclass
class LessonRequest:
    unit: Unit
    native_lang: str
    target_lang: str
    interests: list[str]
    recent_mistakes: list[str]  # target-language words/phrases the user got wrong recently


def build_exercise_generation_prompt(req: LessonRequest) -> str:
    """Builds the instruction sent to the HF chat model to produce a JSON batch
    of exercises for this unit, personalized to the learner."""
    mix = exercise_mix_for(req.unit.level)
    types_list = ", ".join(t.value for t in mix)
    interests = ", ".join(req.interests) if req.interests else "everyday life"
    mistakes = (
        f"The learner recently struggled with: {', '.join(req.recent_mistakes)}. "
        "Weave 1-2 of these back in for extra practice."
        if req.recent_mistakes
        else ""
    )
    show_translation = "Include the native-language translation." if req.unit.level.uses_translation else (
        "Do NOT include any native-language translation — this level is pure immersion: "
        "teach meaning only through the image_prompt and example sentence context."
    )

    return f"""You are a curriculum designer for a language-learning app, similar in
methodology to Duolingo and Rosetta Stone. Generate a JSON array of exactly {len(mix)}
exercises for a learner studying {req.target_lang} (native language: {req.native_lang}),
at CEFR level {req.unit.level.value}, on the topic "{req.unit.topic}".

Personalize the example sentences and vocabulary choices around the learner's
interests where natural: {interests}. {mistakes}

Exercise types to use, in this order: {types_list}.
{show_translation}

Return ONLY a JSON array. Each element must have these exact fields:
- "type": one of {[t.value for t in ExerciseType]}
- "prompt": the instruction shown to the learner, written in {req.native_lang} for
  levels below B1, or in {req.target_lang} for B1+ (to build immersion)
- "target_text": the key word/phrase/sentence in {req.target_lang}
- "native_text": the translation in {req.native_lang} (empty string if translations
  are disabled for this level)
- "options": array of 3-4 answer choices in {req.target_lang} (only for
  multiple_choice and image_match; empty array otherwise)
- "correct_answer": the correct answer string
- "image_prompt": a short, concrete visual description (in English, for an image
  generator) illustrating target_text — required for image_match, optional/empty
  otherwise
- "audio_text": the {req.target_lang} text that should be spoken aloud (usually
  same as target_text)
- "vocab_key": a short lowercase slug identifying this vocabulary item, stable
  across repeats (e.g. "greetings.hello")

Respond with raw JSON only, no markdown fences, no commentary."""


def build_conversation_system_prompt(
    target_lang: str, native_lang: str, level: CEFRLevel, interests: list[str]
) -> str:
    interests_s = ", ".join(interests) if interests else "general topics"
    level_note = (
        "Use only very simple, high-frequency vocabulary and short sentences. "
        "If the learner writes in their native language, gently reply with the "
        f"{target_lang} equivalent and encourage them to repeat it."
        if level.rank <= 1
        else "Use natural, level-appropriate vocabulary and correct mistakes gently by "
        "restating the corrected sentence before continuing the conversation."
        if level.rank <= 3
        else "Speak at a natural native pace with idioms and nuance appropriate to an "
        "advanced/native speaker, still noting any errors briefly."
    )
    return f"""You are a warm, patient, native-speaking conversation partner for a
language learner practicing {target_lang} in a live voice-call-style session.
The learner's native language is {native_lang}. Their level is {level.value}.
Their interests include: {interests_s} — steer small talk toward these when natural.

Rules:
- Reply primarily in {target_lang}.
- {level_note}
- Keep replies conversational and short (1-3 sentences), like a real spoken exchange,
  and always end with a question or prompt so the conversation keeps flowing.
- If the learner made a language mistake, include a one-line gentle correction
  prefixed with "Correction:" in {native_lang}, then continue in {target_lang}.
"""
