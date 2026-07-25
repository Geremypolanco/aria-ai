"""Regression test: ARIA gave a hedging, evasive non-answer ("the question
is subjective...") to a straightforward question instead of committing to a
real answer, despite SYSTEM_TEMPLATE already saying not to hedge. Root
cause: two prompts that run on real, non-trivial fractions of ARIA's replies
— _reason()'s FAST-model fallback (fires whenever complete_json() can't
produce parseable JSON) and SYNTHESIS_SYSTEM (used for the majority of
tool-based replies) — never inherited SYSTEM_TEMPLATE's "SOUND SHARP, NOT
GENERIC" anti-hedging/specificity rules in the first place. Both now carry a
condensed version of those rules.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_mind import SYNTHESIS_SYSTEM, AriaMind
from apps.core.tools.ai_client import AIProvider, AIResponse


@pytest.mark.asyncio
async def test_reason_fallback_system_prompt_has_anti_hedging_rule():
    mind = AriaMind()
    fake_ai = AsyncMock()
    fake_ai.complete_json = AsyncMock(return_value={})
    fake_ai.complete = AsyncMock(
        return_value=AIResponse(
            content="a direct answer",
            provider=AIProvider.ANTHROPIC,
            model="fast",
            success=True,
        )
    )

    with patch.object(mind, "_ai_client", return_value=fake_ai):
        result = await mind._reason("Cuáles son las top 10 mejores AIs?", [], {}, [], [])

    assert result == {"tool": None, "reply": "a direct answer"}
    fake_ai.complete.assert_awaited_once()
    system_prompt = fake_ai.complete.call_args.kwargs["system"]
    assert "don't hedge" in system_prompt.lower() or "commit to a specific" in system_prompt.lower()


def test_synthesis_system_has_anti_hedging_rule():
    lowered = SYNTHESIS_SYSTEM.lower()
    assert "don't hedge" in lowered
    assert "be specific" in lowered


def test_synthesis_system_preserves_failure_handling_paragraph():
    assert "NEVER quote or paraphrase the raw error" in SYNTHESIS_SYSTEM
