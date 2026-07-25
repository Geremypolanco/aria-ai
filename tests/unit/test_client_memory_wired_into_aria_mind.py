"""Regression test: ClientMemory (apps/memory/client/) — a complete CRM
implementation (profiles, sentiment-tagged interaction history, segmentation,
personalized offers) with its own singleton getter — had zero live callers.
Sixth batch from the full-repo dead-code audit.

Distinct from AudienceSegmenter (anonymous ad targeting) and
LeadEngine/LinkedInOutreach (prospects not yet clients) — this tracks known,
named customers you already have a relationship with.

Wired into aria_mind.py's tool dispatcher as: upsert_client_profile,
record_client_interaction, segment_client, personalize_client_offer,
client_memory_dashboard.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, not by calling the engine directly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.core.tools.ai_client import AIProvider, AIResponse
from apps.memory.client.client_memory import ClientMemory

pytestmark = pytest.mark.asyncio


class _FakeCache:
    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ttl_seconds=3600):
        self._store[key] = value
        return True


def _fake_ai_response(content: str) -> AIResponse:
    return AIResponse(content=content, provider=AIProvider.ANTHROPIC, model="fast", success=True)


@pytest.fixture(autouse=True)
def _patch_cache():
    with patch("apps.memory.client.client_memory.get_cache", return_value=_FakeCache()):
        yield


async def test_upsert_client_profile_reachable_from_tool_dispatch():
    memory = ClientMemory()
    with patch("apps.memory.client.client_memory.get_client_memory", return_value=memory):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "upsert_client_profile",
            {"name": "Jane Doe", "email": "jane@acme.com", "company": "Acme Yoga"},
        )

    assert media == {}
    assert "Jane Doe" in obs
    assert "jane@acme.com" in obs


async def test_upsert_client_profile_requires_name_and_email():
    mind = AriaMind()
    obs, media = await mind._execute_tool("upsert_client_profile", {"name": "Jane"})

    assert media == {}
    assert "email" in obs.lower()


async def test_record_client_interaction_reachable_from_tool_dispatch():
    memory = ClientMemory()
    fake_ai = AsyncMock()
    fake_ai.complete = AsyncMock(return_value=_fake_ai_response("positive"))
    with (
        patch("apps.memory.client.client_memory.get_client_memory", return_value=memory),
        patch("apps.memory.client.client_memory.get_ai_client", return_value=fake_ai),
    ):
        mind = AriaMind()
        profile = await memory.upsert_profile("Jane Doe", "jane@acme.com")
        obs, media = await mind._execute_tool(
            "record_client_interaction",
            {
                "profile_id": profile.profile_id,
                "interaction_type": "purchase",
                "summary": "Bought the premium plan, very happy",
                "value_usd": 199.0,
            },
        )

    assert media == {}
    assert "purchase" in obs.lower()
    assert "positive" in obs
    assert "$199.00" in obs


async def test_record_client_interaction_requires_profile_and_type():
    mind = AriaMind()
    obs, media = await mind._execute_tool("record_client_interaction", {})

    assert media == {}
    assert "profile_id" in obs.lower()


async def test_segment_client_reachable_from_tool_dispatch():
    memory = ClientMemory()
    with patch("apps.memory.client.client_memory.get_client_memory", return_value=memory):
        mind = AriaMind()
        profile = await memory.upsert_profile("Jane Doe", "jane@acme.com")
        obs, media = await mind._execute_tool("segment_client", {"profile_id": profile.profile_id})

    assert media == {}
    assert "Segment:" in obs


async def test_personalize_client_offer_reachable_from_tool_dispatch():
    memory = ClientMemory()
    fake_ai = AsyncMock()
    fake_ai.complete = AsyncMock(return_value=_fake_ai_response("Upsell to the premium plan"))
    with (
        patch("apps.memory.client.client_memory.get_client_memory", return_value=memory),
        patch("apps.memory.client.client_memory.get_ai_client", return_value=fake_ai),
    ):
        mind = AriaMind()
        profile = await memory.upsert_profile("Jane Doe", "jane@acme.com")
        obs, media = await mind._execute_tool(
            "personalize_client_offer",
            {
                "profile_id": profile.profile_id,
                "available_products": ["starter_plan", "premium_plan"],
            },
        )

    assert media == {}
    assert "Recommended" in obs


async def test_client_memory_dashboard_empty_state():
    memory = ClientMemory()
    with patch("apps.memory.client.client_memory.get_client_memory", return_value=memory):
        mind = AriaMind()
        obs, media = await mind._execute_tool("client_memory_dashboard", {})

    assert media == {}
    assert "no client profiles" in obs.lower()


async def test_client_memory_dashboard_reachable_from_tool_dispatch():
    memory = ClientMemory()
    with patch("apps.memory.client.client_memory.get_client_memory", return_value=memory):
        mind = AriaMind()
        profile = await memory.upsert_profile("Jane Doe", "jane@acme.com")
        memory._profiles[0]["total_spent_usd"] = 1500.0
        memory._profiles[0]["purchase_count"] = 12
        await mind._execute_tool("segment_client", {"profile_id": profile.profile_id})
        obs, media = await mind._execute_tool("client_memory_dashboard", {})

    assert media == {}
    assert "Client memory" in obs
    assert "VIP" in obs
    assert "Jane Doe" in obs
