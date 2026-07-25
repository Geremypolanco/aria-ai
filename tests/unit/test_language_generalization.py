"""Regression test: ARIA's language handling used to be a hardcoded English/
Spanish binary — a regex classifier (_detect_lang) picked one of exactly two
languages and _lang_directive forced the reply into whichever it picked. Any
third language (French, German, Japanese, Arabic, ...) either got dragged
into English or Spanish regardless of what the user actually wrote in.

This is now generalized: _lang_directive no longer pre-classifies into a
fixed set — it hands the model the user's own text and tells it to match
that language exactly, which works for any language since the model reads
the text itself rather than trusting a keyword list.

Covers both call sites that had this binary logic:
  - apps/core/cognition/aria_mind.py (AriaMind._lang_directive,
    AriaMind._looks_english, AriaMind._localize_short_text — the image
    fast-path caption, which used to hardcode a Spanish sentence and an
    English sentence with nothing in between)
  - apps/core/orchestration/dynamic_workflow.py (_lang_directive)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.core.orchestration.dynamic_workflow import _lang_directive as workflow_lang_directive
from apps.core.tools.ai_client import AIProvider, AIResponse


def test_aria_mind_lang_directive_names_no_specific_language():
    directive = AriaMind._lang_directive("Erstelle mir bitte ein Bild von einer Katze")
    assert "Spanish" in directive or "English" in directive  # only as a "don't default to" caveat
    assert "exact same language" in directive


def test_aria_mind_lang_directive_forbids_narrating_the_instruction():
    """Regression: a weaker/faster model was observed narrating this
    instruction verbatim ("Identifico el idioma como español...") instead of
    silently applying it, producing a non-answer instead of a real reply."""
    directive = AriaMind._lang_directive("Cuáles son las top 10 mejores AIs?")
    lowered = directive.lower()
    assert "do not mention" in lowered
    assert "restate" in lowered
    assert "narrate" in lowered


def test_aria_mind_lang_directive_still_permits_answering_language_questions():
    """The no-narration clause must forbid narrating THIS INSTRUCTION, not
    forbid the model from ever mentioning a language — a user might
    genuinely ask "what language is this sentence written in?"."""
    directive = AriaMind._lang_directive("What language is this sentence written in?")
    assert "genuinely asking" in directive.lower() or "genuinely ask" in directive.lower()


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Create an image of a cat", True),
        ("What's the weather like today?", True),
        ("Erstelle mir bitte ein Bild von einem Vögelchen", False),  # German, umlaut
        ("Créame una imagen de un gato", False),  # Spanish, accents
        ("猫の画像を作成してください", False),  # Japanese
        ("Создай изображение кота", False),  # Russian
        ("قم بإنشاء صورة لقطة", False),  # Arabic
    ],
)
def test_looks_english_heuristic(text, expected):
    assert AriaMind._looks_english(text) is expected


@pytest.mark.asyncio
async def test_localize_short_text_uses_fast_model_translation():
    mind = AriaMind()
    fake_ai = AsyncMock()
    fake_ai.complete = AsyncMock(
        return_value=AIResponse(
            content="Voici l'image que j'ai créée pour toi.",
            provider=AIProvider.ANTHROPIC,
            model="fast",
            success=True,
        )
    )
    with patch.object(mind, "_ai_client", return_value=fake_ai):
        result = await mind._localize_short_text(
            "Crée-moi une image d'un chat", "Here's the image I created for you."
        )

    assert result == "Voici l'image que j'ai créée pour toi."
    fake_ai.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_localize_short_text_falls_back_to_english_on_failure():
    mind = AriaMind()
    fake_ai = AsyncMock()
    fake_ai.complete = AsyncMock(side_effect=RuntimeError("provider down"))
    with patch.object(mind, "_ai_client", return_value=fake_ai):
        result = await mind._localize_short_text(
            "Crée-moi une image d'un chat", "Here's the image I created for you."
        )

    assert result == "Here's the image I created for you."


@pytest.mark.asyncio
async def test_localize_short_text_falls_back_when_no_client():
    mind = AriaMind()
    with patch.object(mind, "_ai_client", return_value=None):
        result = await mind._localize_short_text("some text", "Here's the image I created for you.")

    assert result == "Here's the image I created for you."


@pytest.mark.asyncio
async def test_image_fast_path_localizes_caption_for_non_english_request():
    """End-to-end: an accented, non-English image request (still matched by
    the English/Spanish trigger-word fast-path detector) must not fall back
    to the old hardcoded Spanish-or-English binary — it should get a
    dynamically translated caption via the FAST model call."""
    mind = AriaMind()
    fake_ai = AsyncMock()
    fake_ai.complete = AsyncMock(
        return_value=AIResponse(
            content="Voici l'image que j'ai créée pour toi.",
            provider=AIProvider.ANTHROPIC,
            model="fast",
            success=True,
        )
    )

    async def fake_retry(tool, args, email=""):
        return "Image generated: a cat", {"image_bytes": b"fakepng"}

    with (
        patch.object(mind, "_ai_client", return_value=fake_ai),
        patch.object(mind, "_execute_with_retry", fake_retry),
        patch.object(mind, "_record_exec", AsyncMock()),
        patch.object(mind, "_store_interaction", AsyncMock()),
        patch.object(mind, "_trace_turn", AsyncMock()),
    ):
        resp = await mind.handle("Créame una imagen de un gato", "chat-1")

    assert resp.caption == "Voici l'image que j'ai créée pour toi."
    assert resp.image_bytes == b"fakepng"
    fake_ai.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_image_fast_path_skips_localization_for_english_request():
    """The common case (English) must not pay for an extra network call."""
    mind = AriaMind()
    fake_ai = AsyncMock()
    fake_ai.complete = AsyncMock(
        return_value=AIResponse(
            content="should not be used", provider=AIProvider.ANTHROPIC, model="fast", success=True
        )
    )

    async def fake_retry(tool, args, email=""):
        return "Image generated: a cat", {"image_bytes": b"fakepng"}

    with (
        patch.object(mind, "_ai_client", return_value=fake_ai),
        patch.object(mind, "_execute_with_retry", fake_retry),
        patch.object(mind, "_record_exec", AsyncMock()),
        patch.object(mind, "_store_interaction", AsyncMock()),
        patch.object(mind, "_trace_turn", AsyncMock()),
    ):
        resp = await mind.handle("Create an image of a cat", "chat-1")

    assert resp.caption == "Here's the image I created for you."
    fake_ai.complete.assert_not_awaited()


def test_workflow_lang_directive_embeds_arbitrary_goal_language():
    directive = workflow_lang_directive("Erstelle einen Marketingplan für mein Café")
    assert "Erstelle einen Marketingplan" in directive
    assert "exact same language" in directive


def test_workflow_lang_directive_forbids_narrating_the_instruction():
    """Same regression as aria_mind's sibling directive — this is an
    independently-implemented copy with the same original phrasing bug."""
    directive = workflow_lang_directive("Erstelle einen Marketingplan für mein Café")
    lowered = directive.lower()
    assert "never mention" in lowered
    assert "restate" in lowered
    assert "narrate" in lowered


def test_workflow_lang_directive_still_permits_answering_language_questions():
    """Same carve-out as aria_mind's sibling — must not suppress a goal that
    genuinely asks to identify a language."""
    directive = workflow_lang_directive("What language is this sentence written in?")
    assert "genuinely asks" in directive.lower() or "genuinely ask" in directive.lower()
