"""Phase 11 tests — Memory Extensions (ClientMemory).

(EconomicMemoryStore and WorkflowMemory were removed along with their dead
source modules — see the memory-system dead-code cleanup commit.)
"""

from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(
    content="1. Focus on highest ROI channels\n2. Repeat what works\n3. Track all experiments",
    json_result=None,
):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    # complete_json() isn't just complete() with a different name on this mock —
    # callers that use it directly need it to be awaitable on its own. json_result
    # defaults to {} to mirror what real complete_json() returns when the model's
    # output isn't valid JSON.
    ai.complete_json = AsyncMock(return_value=json_result if json_result is not None else {})
    return ai


# ── Client Memory ─────────────────────────────────────────────────────────────


class TestClientMemory:
    @pytest.fixture
    def memory(self):
        with patch("apps.memory.client.client_memory.get_cache", return_value=_mock_cache()):
            with patch(
                "apps.memory.client.client_memory.get_ai_client", return_value=_mock_ai("positive")
            ):
                from apps.memory.client.client_memory import ClientMemory

                return ClientMemory()

    @pytest.mark.asyncio
    async def test_upsert_profile_returns_profile(self, memory):
        from apps.memory.client.client_memory import ClientProfile

        profile = await memory.upsert_profile("Alice", "alice@example.com", "TechCorp")
        assert isinstance(profile, ClientProfile)
        assert profile.profile_id

    @pytest.mark.asyncio
    async def test_upsert_same_email_updates_profile(self, memory):
        await memory.upsert_profile("Alice", "alice@test.com", "OldCorp")
        await memory.upsert_profile("Alice Updated", "alice@test.com", "NewCorp")
        assert len(memory._profiles) == 1
        assert memory._profiles[0]["company"] == "NewCorp"

    @pytest.mark.asyncio
    async def test_record_interaction_returns_interaction(self, memory):
        from apps.memory.client.client_memory import ClientInteraction

        profile = await memory.upsert_profile("Bob", "bob@test.com")
        interaction = await memory.record_interaction(
            profile.profile_id, "purchase", "Bought Plan A", value_usd=99.0
        )
        assert isinstance(interaction, ClientInteraction)
        assert interaction.interaction_id

    @pytest.mark.asyncio
    async def test_record_interaction_has_sentiment(self, memory):
        profile = await memory.upsert_profile("Carol", "carol@test.com")
        interaction = await memory.record_interaction(
            profile.profile_id, "support", "Great service!", value_usd=0.0
        )
        assert interaction.sentiment in ("positive", "neutral", "negative")

    @pytest.mark.asyncio
    async def test_purchase_updates_total_spent(self, memory):
        profile = await memory.upsert_profile("Dave", "dave@test.com")
        await memory.record_interaction(
            profile.profile_id, "purchase", "Bought item", value_usd=150.0
        )
        updated = next(p for p in memory._profiles if p["profile_id"] == profile.profile_id)
        assert updated["total_spent_usd"] == 150.0

    @pytest.mark.asyncio
    async def test_segment_client_vip_for_high_spenders(self, memory):
        profile = await memory.upsert_profile("Eve", "eve@test.com")
        for _ in range(11):
            await memory.record_interaction(
                profile.profile_id, "purchase", "Purchased", value_usd=100.0
            )
        segment = await memory.segment_client(profile.profile_id)
        assert segment == "vip"

    @pytest.mark.asyncio
    async def test_segment_client_standard_for_new(self, memory):
        profile = await memory.upsert_profile("Frank", "frank@test.com")
        segment = await memory.segment_client(profile.profile_id)
        assert segment == "standard"

    @pytest.mark.asyncio
    async def test_personalize_offer_uses_real_ai_pick_when_valid(self):
        """Regression: personalize_offer used to ask the AI to "pick best
        offer" but then always hardcoded available_products[0] regardless of
        what the AI actually picked — the AI's structured recommendation was
        completely ignored, only its free-text reasoning was used."""
        with patch("apps.memory.client.client_memory.get_cache", return_value=_mock_cache()):
            with patch(
                "apps.memory.client.client_memory.get_ai_client",
                return_value=_mock_ai(
                    json_result={
                        "recommended_product": "basic_plan",
                        "offer": "20% first-month discount",
                        "reasoning": "Client is price-sensitive based on history",
                    }
                ),
            ):
                from apps.memory.client.client_memory import ClientMemory

                memory = ClientMemory()
                profile = await memory.upsert_profile("Grace2", "grace2@test.com")
                offer = await memory.personalize_offer(
                    profile.profile_id, ["premium_plan", "basic_plan"]
                )

        assert offer["recommended_product"] == "basic_plan"
        assert offer["offer"] == "20% first-month discount"

    @pytest.mark.asyncio
    async def test_personalize_offer_ignores_hallucinated_product(self):
        """A recommended_product that isn't one of the given products (a
        hallucination) must fall back to the safe default, not recommend
        something that doesn't exist."""
        with patch("apps.memory.client.client_memory.get_cache", return_value=_mock_cache()):
            with patch(
                "apps.memory.client.client_memory.get_ai_client",
                return_value=_mock_ai(
                    json_result={"recommended_product": "made_up_plan", "offer": "50% off"}
                ),
            ):
                from apps.memory.client.client_memory import ClientMemory

                memory = ClientMemory()
                profile = await memory.upsert_profile("Grace3", "grace3@test.com")
                offer = await memory.personalize_offer(
                    profile.profile_id, ["premium_plan", "basic_plan"]
                )

        assert offer["recommended_product"] == "premium_plan"

    @pytest.mark.asyncio
    async def test_personalize_offer_returns_dict(self, memory):
        profile = await memory.upsert_profile("Grace", "grace@test.com")
        offer = await memory.personalize_offer(profile.profile_id, ["premium_plan", "basic_plan"])
        assert "recommended_product" in offer
        assert "offer" in offer

    def test_get_profile_by_email(self, memory):
        import asyncio

        asyncio.run(memory.upsert_profile("Hank", "hank@test.com", "Corp"))
        result = memory.get_profile("hank@test.com")
        assert result is not None
        assert result["name"] == "Hank"

    def test_vip_clients_returns_vip_only(self, memory):
        memory._profiles = [
            {"profile_id": "p1", "segment": "vip"},
            {"profile_id": "p2", "segment": "standard"},
            {"profile_id": "p3", "segment": "vip"},
        ]
        vips = memory.vip_clients()
        assert len(vips) == 2
        assert all(p["segment"] == "vip" for p in vips)

    def test_at_risk_clients_includes_churned(self, memory):
        memory._profiles = [
            {"profile_id": "p1", "segment": "at_risk"},
            {"profile_id": "p2", "segment": "churned"},
            {"profile_id": "p3", "segment": "vip"},
        ]
        at_risk = memory.at_risk_clients()
        assert len(at_risk) == 2

    def test_client_memory_summary_has_required_keys(self, memory):
        summary = memory.client_memory_summary()
        assert "total_profiles" in summary
        assert "total_interactions" in summary
        assert "by_segment" in summary
        assert "vip_count" in summary
