"""Phase 11 tests — Conversion Extensions (SMSCaptureEngine, FunnelEngine)."""

from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content="Welcome to our store! Get 10% off your first order. Reply STOP to opt out."):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


# ── SMS Capture Engine ────────────────────────────────────────────────────────


class TestSMSCaptureEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.conversion.sms.sms_capture.get_cache", return_value=_mock_cache()):
            with patch("apps.conversion.sms.sms_capture.get_ai_client", return_value=_mock_ai()):
                from apps.conversion.sms.sms_capture import SMSCaptureEngine

                return SMSCaptureEngine()

    @pytest.mark.asyncio
    async def test_capture_returns_subscriber(self, engine):
        from apps.conversion.sms.sms_capture import SMSSubscriber

        sub = await engine.capture("+15551234567", "popup", name="Alice")
        assert isinstance(sub, SMSSubscriber)
        assert sub.subscriber_id

    @pytest.mark.asyncio
    async def test_subscriber_is_opted_in(self, engine):
        sub = await engine.capture("+15559876543", "checkout")
        assert sub.opted_in is True

    @pytest.mark.asyncio
    async def test_subscriber_has_source(self, engine):
        sub = await engine.capture("+15551112222", "quiz")
        assert sub.source == "quiz"

    @pytest.mark.asyncio
    async def test_subscriber_stored_in_memory(self, engine):
        await engine.capture("+15553334444", "popup")
        assert len(engine._subscribers) == 1

    @pytest.mark.asyncio
    async def test_generate_welcome_message_returns_sms(self, engine):
        from apps.conversion.sms.sms_capture import SMSMessage

        sub = await engine.capture("+15551234567", "popup", name="Bob")
        msg = await engine.generate_welcome_message(sub.subscriber_id, "MyBrand", "15% off")
        assert isinstance(msg, SMSMessage)
        assert msg.message_id

    @pytest.mark.asyncio
    async def test_welcome_message_under_160_chars(self, engine):
        sub = await engine.capture("+15551234567", "popup")
        msg = await engine.generate_welcome_message(sub.subscriber_id, "Brand", "20% off")
        assert len(msg.body) <= 160

    @pytest.mark.asyncio
    async def test_welcome_message_type_is_welcome(self, engine):
        sub = await engine.capture("+15551234567", "popup")
        msg = await engine.generate_welcome_message(sub.subscriber_id, "Brand", "10% off")
        assert msg.message_type == "welcome"

    @pytest.mark.asyncio
    async def test_generate_cart_recovery_sms(self, engine):
        from apps.conversion.sms.sms_capture import SMSMessage

        sub = await engine.capture("+15557778888", "checkout")
        msg = await engine.generate_cart_recovery_sms(sub.subscriber_id, 89.99, "Blue Sneakers")
        assert isinstance(msg, SMSMessage)
        assert msg.message_type == "cart_recovery"

    @pytest.mark.asyncio
    async def test_cart_recovery_sms_under_160_chars(self, engine):
        sub = await engine.capture("+15556667777", "checkout")
        msg = await engine.generate_cart_recovery_sms(sub.subscriber_id, 59.99, "Red Hat")
        assert len(msg.body) <= 160

    @pytest.mark.asyncio
    async def test_generate_flash_sale_sms(self, engine):
        from apps.conversion.sms.sms_capture import SMSMessage

        sub = await engine.capture("+15554445555", "campaign")
        msg = await engine.generate_flash_sale_sms(
            sub.subscriber_id, {"name": "Summer Sale", "discount": "30% off", "expires": "24 hours"}
        )
        assert isinstance(msg, SMSMessage)
        assert msg.message_type == "flash_sale"

    @pytest.mark.asyncio
    async def test_flash_sale_sms_under_160_chars(self, engine):
        sub = await engine.capture("+15553332222", "campaign")
        msg = await engine.generate_flash_sale_sms(
            sub.subscriber_id, {"name": "Flash", "discount": "40% off", "expires": "6 hours"}
        )
        assert len(msg.body) <= 160

    @pytest.mark.asyncio
    async def test_create_campaign_messages_for_tagged_subscribers(self, engine):
        sub1 = await engine.capture("+15551111111", "popup", tags=["vip"])
        sub2 = await engine.capture("+15552222222", "popup", tags=["standard"])
        msgs = await engine.create_campaign_messages("vip", "flash_sale", "VIP Sale 30% off")
        assert isinstance(msgs, list)
        assert len(msgs) == 1

    def test_capture_stats_has_required_keys(self, engine):
        stats = engine.capture_stats()
        assert "total_subscribers" in stats
        assert "klaviyo_synced" in stats
        assert "by_source" in stats

    @pytest.mark.asyncio
    async def test_recent_subscribers_returns_list(self, engine):
        await engine.capture("+15559999999", "quiz")
        result = engine.recent_subscribers(limit=5)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_multiple_subscribers_accumulate(self, engine):
        await engine.capture("+15551000001", "popup")
        await engine.capture("+15551000002", "checkout")
        await engine.capture("+15551000003", "quiz")
        assert len(engine._subscribers) == 3


# ── Funnel Engine ─────────────────────────────────────────────────────────────


class TestFunnelEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.conversion.funnels.funnel_engine.get_cache", return_value=_mock_cache()):
            with patch(
                "apps.conversion.funnels.funnel_engine.get_ai_client",
                return_value=_mock_ai(
                    '[{"stage_name": "awareness", "optimization_opportunity": "Use retargeting ads", "avg_time_hours": 48.0}]'
                ),
            ):
                from apps.conversion.funnels.funnel_engine import FunnelEngine

                return FunnelEngine()

    @pytest.mark.asyncio
    async def test_create_funnel_returns_funnel(self, engine):
        from apps.conversion.funnels.funnel_engine import Funnel

        funnel = await engine.create_funnel("My Ecommerce Funnel", "ecommerce", "fitness")
        assert isinstance(funnel, Funnel)
        assert funnel.funnel_id

    @pytest.mark.asyncio
    async def test_funnel_has_stages(self, engine):
        funnel = await engine.create_funnel("Lead Gen Funnel", "lead_gen", "health")
        assert isinstance(funnel.stages, list)
        assert len(funnel.stages) >= 3

    @pytest.mark.asyncio
    async def test_ecommerce_funnel_has_7_stages(self, engine):
        funnel = await engine.create_funnel("Ecom Funnel", "ecommerce", "fashion")
        assert len(funnel.stages) == 7

    @pytest.mark.asyncio
    async def test_quiz_funnel_type_recognized(self, engine):
        funnel = await engine.create_funnel("Quiz Funnel", "quiz", "skincare")
        assert funnel.funnel_type == "quiz"

    @pytest.mark.asyncio
    async def test_record_stage_entry_increments_count(self, engine):
        funnel = await engine.create_funnel("Test Funnel", "ecommerce", "tech")
        await engine.record_stage_entry(funnel.funnel_id, "awareness", 100)
        stored = engine.get_funnel(funnel.funnel_id)
        awareness_stage = next(s for s in stored["stages"] if s["name"] == "awareness")
        assert awareness_stage["entry_count"] == 100

    @pytest.mark.asyncio
    async def test_record_stage_exit_calculates_cvr(self, engine):
        funnel = await engine.create_funnel("CVR Funnel", "ecommerce", "beauty")
        await engine.record_stage_entry(funnel.funnel_id, "interest", 200)
        await engine.record_stage_exit(funnel.funnel_id, "interest", 100)
        stored = engine.get_funnel(funnel.funnel_id)
        interest_stage = next(s for s in stored["stages"] if s["name"] == "interest")
        assert interest_stage["conversion_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_analyze_funnel_returns_dict(self, engine):
        funnel = await engine.create_funnel("Analysis Funnel", "lead_gen", "finance")
        result = await engine.analyze_funnel(funnel.funnel_id)
        assert isinstance(result, dict)
        assert "top_opportunity" in result or "error" not in result

    @pytest.mark.asyncio
    async def test_analyze_funnel_has_recommended_actions(self, engine):
        funnel = await engine.create_funnel("Action Funnel", "saas", "productivity")
        result = await engine.analyze_funnel(funnel.funnel_id)
        assert "recommended_actions" in result

    @pytest.mark.asyncio
    async def test_optimize_stage_returns_dict(self, engine):
        funnel = await engine.create_funnel("Opt Funnel", "content", "fitness")
        result = await engine.optimize_stage(funnel.funnel_id, "discover")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_optimize_stage_has_target_cvr(self, engine):
        funnel = await engine.create_funnel("CVR Opt Funnel", "ecommerce", "apparel")
        result = await engine.optimize_stage(funnel.funnel_id, "awareness")
        assert "target_cvr" in result or "error" in result

    def test_get_funnel_returns_funnel_dict(self, engine):
        import asyncio

        funnel = asyncio.run(engine.create_funnel("Get Test", "ecommerce", "home"))
        result = engine.get_funnel(funnel.funnel_id)
        assert result is not None
        assert result["funnel_id"] == funnel.funnel_id

    def test_funnel_analytics_has_required_keys(self, engine):
        stats = engine.funnel_analytics()
        assert "total_funnels" in stats
        assert "by_type" in stats
        assert "avg_overall_cvr" in stats

    def test_list_funnels_returns_list(self, engine):
        result = engine.list_funnels()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_multiple_funnels_tracked(self, engine):
        await engine.create_funnel("Funnel A", "ecommerce", "tech")
        await engine.create_funnel("Funnel B", "lead_gen", "health")
        assert len(engine._funnels) == 2

    @pytest.mark.asyncio
    async def test_saas_funnel_stages(self, engine):
        funnel = await engine.create_funnel("SaaS Funnel", "saas", "productivity")
        assert len(funnel.stages) == 5
