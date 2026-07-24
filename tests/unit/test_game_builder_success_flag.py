"""Regression test: GameBuilder._pack_zip() hardcoded "success": True
regardless of whether the underlying AI generation actually produced real
game code. _generate_files() silently falls back to
"# TODO"/"# Error generating" stub content for every file whenever
get_ai_client() raises or the AI call fails/returns unsuccessfully — none of
that propagated to the top-level success flag. Callers like
apps/core/cognition/aria_mind.py (`if r.get("success") and r.get("zip_bytes"):`)
trusted this blindly and told the user "Juego generado" even when every
file inside was just an empty stub.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.tools.game_builder import GameBuilder

pytestmark = pytest.mark.asyncio


async def test_create_game_reports_failure_when_ai_client_unavailable():
    builder = GameBuilder()

    with patch(
        "apps.core.tools.ai_client.get_ai_client", side_effect=RuntimeError("no client")
    ):
        result = await builder.create_game("My Game", genre="arcade", engine="pygame")

    assert result["success"] is False
    assert "error" in result
    assert result["zip_bytes"]


async def test_create_game_reports_failure_when_every_ai_call_fails():
    builder = GameBuilder()
    fake_client = MagicMock()
    fake_resp = MagicMock()
    fake_resp.success = False
    fake_resp.content = ""
    fake_client.complete = AsyncMock(return_value=fake_resp)

    with patch("apps.core.tools.ai_client.get_ai_client", return_value=fake_client):
        result = await builder.create_game("My Game", genre="arcade", engine="pygame")

    assert result["success"] is False
    assert len(result["generation_warnings"]) > 0


async def test_create_game_reports_success_when_ai_calls_succeed():
    builder = GameBuilder()
    fake_client = MagicMock()
    fake_resp = MagicMock()
    fake_resp.success = True
    fake_resp.content = "print('real generated code')"
    fake_client.complete = AsyncMock(return_value=fake_resp)

    with patch("apps.core.tools.ai_client.get_ai_client", return_value=fake_client):
        result = await builder.create_game("My Game", genre="arcade", engine="pygame")

    assert result["success"] is True
    assert "generation_warnings" not in result
