"""Regression test: ContentOperator.run_once()'s per-channel "publish" step
recorded tool=None for every single publish, always — publish() builds each
result dict with an "action" key (the Zapier action name), but the step()
call read r.get("tool"), a key that's never set. The whole point of this
observability trail (per the module docstring: "which tools did it call")
is defeated if that field is silently always None.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.tools.content_operator import ContentOperator

pytestmark = pytest.mark.asyncio


async def test_publish_step_records_the_actual_action_used():
    op = ContentOperator.__new__(ContentOperator)
    op.content = AsyncMock()
    op.mcp = AsyncMock()

    with patch.object(
        ContentOperator,
        "generate_creative",
        AsyncMock(
            return_value={
                "success": True,
                "hook": "hook",
                "caption": "caption",
                "image_prompt": "prompt",
                "reasoning": "",
                "research_used": 0,
                "research_error": None,
                "sources": [],
            }
        ),
    ), patch.object(
        ContentOperator,
        "produce_image",
        AsyncMock(return_value={"success": True, "image_url": "https://img/x.png"}),
    ), patch.object(
        ContentOperator,
        "publish",
        AsyncMock(
            return_value=[
                {
                    "channel": "instagram",
                    "action": "publish_media_v2",
                    "params_keys": ["media", "caption"],
                    "success": True,
                    "error": None,
                    "response": "ok",
                }
            ]
        ),
    ), patch.object(ContentOperator, "_save", AsyncMock()):
        record = await op.run_once({"name": "TestBrand"}, channels=["instagram"])

    publish_step = next(s for s in record["steps"] if s["step"] == "publish:instagram")
    assert publish_step["tool"] == "publish_media_v2"
