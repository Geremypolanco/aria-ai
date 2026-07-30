"""Domain models for Lingua: users, curriculum units, exercises, progress."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class CEFRLevel(StrEnum):
    """Common European Framework levels, plus NATIVE as the final rung."""

    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"
    C2 = "C2"
    NATIVE = "NATIVE"

    @property
    def rank(self) -> int:
        return list(CEFRLevel).index(self)

    @property
    def next(self) -> "CEFRLevel":
        levels = list(CEFRLevel)
        idx = levels.index(self)
        return levels[min(idx + 1, len(levels) - 1)]

    @property
    def uses_translation(self) -> bool:
        """Rosetta-Stone style: A1 is pure immersion (image+audio+target text, no
        translation shown). From A2 on we start surfacing translations/explanations."""
        return self.rank > 0

    @property
    def allows_free_conversation(self) -> bool:
        return self.rank >= list(CEFRLevel).index(CEFRLevel.B1)


class ExerciseType(StrEnum):
    IMAGE_MATCH = "image_match"  # Rosetta-Stone style: pick the image for the target word/audio
    LISTEN_TYPE = "listen_type"  # hear audio, type what you heard
    TRANSLATE_TO_TARGET = "translate_to_target"
    TRANSLATE_TO_NATIVE = "translate_to_native"
    MULTIPLE_CHOICE = "multiple_choice"
    SPEAK_REPEAT = "speak_repeat"  # record yourself repeating a phrase (STT-graded)
    FILL_BLANK = "fill_blank"
    FREE_CONVERSATION_PROMPT = "free_conversation_prompt"


class VocabItem(BaseModel):
    target_text: str
    native_text: str
    image_prompt: str
    example_sentence_target: str
    example_sentence_native: str


class Exercise(BaseModel):
    id: str
    type: ExerciseType
    prompt: str
    target_text: str
    native_text: str = ""
    options: list[str] = Field(default_factory=list)
    correct_answer: str
    image_prompt: str = ""
    audio_text: str = ""
    vocab_key: str = ""


class Unit(BaseModel):
    id: str
    topic: str
    level: CEFRLevel
    order: int
    title_native: str
    description_native: str


class UserProfile(BaseModel):
    id: str
    display_name: str
    native_lang: str
    target_lang: str
    level: CEFRLevel = CEFRLevel.A1
    interests: list[str] = Field(default_factory=list)
    xp: int = 0
    streak_days: int = 0
    hearts: int = 5
    created_at: str = ""
    last_active_date: str = ""


class AnswerSubmission(BaseModel):
    exercise_id: str
    unit_id: str
    vocab_key: str = ""
    given_answer: str
    correct: bool


class ProgressSnapshot(BaseModel):
    user_id: str
    xp: int
    streak_days: int
    hearts: int
    level: CEFRLevel
    due_reviews: int
    units_mastered: int
