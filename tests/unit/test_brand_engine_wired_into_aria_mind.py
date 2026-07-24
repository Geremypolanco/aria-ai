"""Regression test: BrandEngine (apps/branding/identity/brand_engine.py) — a
complete, working persistent brand-identity manager (color palette,
typography, voice/tone, and a real consistency-scoring algorithm) — had zero
live callers, same pattern as RDWing before it (see
test_rd_wing_wired_into_aria_mind.py). Now wired into aria_mind.py's tool
dispatcher as create_brand, check_brand_consistency, and list_brands, so
ARIA can keep generated content consistent with a brand the user defines
once instead of drifting per-request.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, not by calling BrandEngine directly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.branding.identity.brand_engine import BrandEngine, BrandTone
from apps.core.cognition.aria_mind import AriaMind

pytestmark = pytest.mark.asyncio


class _FakeCache:
    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ttl_seconds=3600):
        self._store[key] = value
        return True


@pytest.fixture
def engine():
    return BrandEngine()


@pytest.fixture(autouse=True)
def _patch_cache():
    fake = _FakeCache()
    with patch("apps.branding.identity.brand_engine.get_cache", return_value=fake):
        yield fake


async def test_create_brand_reachable_from_tool_dispatch(engine):
    with patch("apps.branding.identity.brand_engine.get_brand_engine", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "create_brand",
            {"name": "Aurora Botanicals", "niche": "beauty", "tone": "luxurious"},
        )

    assert media == {}
    assert "Aurora Botanicals" in obs
    assert "luxurious" in obs
    brands = await engine.list_brands()
    assert len(brands) == 1
    assert brands[0].voice.tone == BrandTone.LUXURIOUS


async def test_create_brand_requires_name_and_niche(engine):
    with patch("apps.branding.identity.brand_engine.get_brand_engine", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool("create_brand", {"name": "X"})

    assert media == {}
    assert "niche" in obs.lower()
    assert await engine.list_brands() == []


async def test_create_brand_falls_back_to_professional_on_invalid_tone(engine):
    with patch("apps.branding.identity.brand_engine.get_brand_engine", return_value=engine):
        mind = AriaMind()
        await mind._execute_tool(
            "create_brand", {"name": "Y", "niche": "tech", "tone": "not-a-real-tone"}
        )

    brands = await engine.list_brands()
    assert brands[0].voice.tone == BrandTone.PROFESSIONAL


async def test_check_brand_consistency_flags_avoided_words(engine):
    profile = await engine.create_brand("Y", "tech", BrandTone.MINIMALIST)
    profile.voice.avoid_words = ["cheap"]
    await engine._persist()

    with patch("apps.branding.identity.brand_engine.get_brand_engine", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "check_brand_consistency",
            {"brand_id": profile.brand_id, "content": "This is a cheap solution for everyone."},
        )

    assert media == {}
    assert "avoided word" in obs.lower()


async def test_list_brands_reflects_dispatcher_created_brands(engine):
    with patch("apps.branding.identity.brand_engine.get_brand_engine", return_value=engine):
        mind = AriaMind()
        await mind._execute_tool("create_brand", {"name": "Z", "niche": "fitness", "tone": "bold"})
        obs, media = await mind._execute_tool("list_brands", {})

    assert media == {}
    assert "Z" in obs
    assert "bold" in obs
