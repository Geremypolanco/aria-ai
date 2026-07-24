"""Regression test: StyleEngine (apps/creative/style/style_engine.py) — a
complete implementation (niche-seeded style profiles, directional evolution,
cliché detection, cross-content consistency audit) with its own singleton
getter — had zero live callers, same pattern as the other audited-but-
disconnected modules wired in earlier this session.

Wired into aria_mind.py's tool dispatcher as: create_style_profile,
evolve_style, check_content_novelty, audit_style_consistency.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, not by calling the engine directly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.creative.style.style_engine import StyleEngine

pytestmark = pytest.mark.asyncio


class _FakeCache:
    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ttl_seconds=3600):
        self._store[key] = value
        return True


@pytest.fixture(autouse=True)
def _patch_cache():
    fake_cache = _FakeCache()
    with patch("apps.creative.style.style_engine.get_cache", return_value=fake_cache):
        yield


async def test_create_style_profile_reachable_from_tool_dispatch():
    engine = StyleEngine()
    with patch("apps.creative.style.style_engine.get_style_engine", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "create_style_profile", {"name": "Fitness Launch", "niche": "fitness"}
        )

    assert media == {}
    assert "Fitness Launch" in obs
    assert "energetic" in obs.lower()


async def test_create_style_profile_requires_name():
    engine = StyleEngine()
    with patch("apps.creative.style.style_engine.get_style_engine", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool("create_style_profile", {})

    assert media == {}
    assert "name" in obs.lower()


async def test_evolve_style_reachable_from_tool_dispatch():
    engine = StyleEngine()
    with patch("apps.creative.style.style_engine.get_style_engine", return_value=engine):
        mind = AriaMind()
        obs, _ = await mind._execute_tool(
            "create_style_profile", {"name": "Fitness Launch", "niche": "fitness"}
        )
        profile_id = obs.split("`")[1]
        obs2, media2 = await mind._execute_tool(
            "evolve_style", {"profile_id": profile_id, "direction": "minimal"}
        )

    assert media2 == {}
    assert "Evolved" in obs2
    assert "minimal" in obs2.lower()


async def test_evolve_style_unknown_profile():
    engine = StyleEngine()
    with patch("apps.creative.style.style_engine.get_style_engine", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "evolve_style", {"profile_id": "does-not-exist", "direction": "bolder"}
        )

    assert media == {}
    assert "not found" in obs.lower()


async def test_check_content_novelty_reachable_from_tool_dispatch():
    engine = StyleEngine()
    with patch("apps.creative.style.style_engine.get_style_engine", return_value=engine):
        mind = AriaMind()
        obs, _ = await mind._execute_tool(
            "create_style_profile", {"name": "Tech Launch", "niche": "tech"}
        )
        profile_id = obs.split("`")[1]
        obs2, media2 = await mind._execute_tool(
            "check_content_novelty",
            {"profile_id": profile_id, "content": "This is a real game-changer, a true paradigm shift."},
        )

    assert media2 == {}
    assert "Novelty score" in obs2
    assert "game-changer" in obs2


async def test_audit_style_consistency_reachable_from_tool_dispatch():
    engine = StyleEngine()
    with patch("apps.creative.style.style_engine.get_style_engine", return_value=engine):
        mind = AriaMind()
        obs, _ = await mind._execute_tool(
            "create_style_profile", {"name": "Tech Launch", "niche": "tech"}
        )
        profile_id = obs.split("`")[1]
        obs2, media2 = await mind._execute_tool(
            "audit_style_consistency",
            {
                "profile_id": profile_id,
                "contents": [
                    "However, this product is therefore superior.",
                    "lol ngl this is gonna be huge tbh",
                ],
            },
        )

    assert media2 == {}
    assert "Consistency score" in obs2
    assert "Mixed formal and casual" in obs2
