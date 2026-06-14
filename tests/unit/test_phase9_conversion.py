"""
Phase 9 tests — Quiz/Lead Capture + Retargeting + Audience Segmentation.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content="Q1: Budget?\nOptions: A) Under $50 B) $50-150 C) $150+\nTag: budget"):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


# ── Quiz Engine ───────────────────────────────────────────────────────────────

class TestQuizEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.conversion.quiz.quiz_engine.get_cache", return_value=_mock_cache()):
            with patch("apps.conversion.quiz.quiz_engine.get_ai_client", return_value=_mock_ai()):
                from apps.conversion.quiz.quiz_engine import QuizEngine
                return QuizEngine()

    @pytest.mark.asyncio
    async def test_create_quiz_returns_product_quiz(self, engine):
        from apps.conversion.quiz.quiz_engine import ProductQuiz
        quiz = await engine.create_quiz("fitness")
        assert isinstance(quiz, ProductQuiz)
        assert quiz.quiz_id

    @pytest.mark.asyncio
    async def test_quiz_has_questions(self, engine):
        quiz = await engine.create_quiz("skincare")
        assert isinstance(quiz.questions, list)
        assert len(quiz.questions) >= 1

    @pytest.mark.asyncio
    async def test_quiz_has_intro_text(self, engine):
        quiz = await engine.create_quiz("tech")
        assert isinstance(quiz.intro_text, str)

    @pytest.mark.asyncio
    async def test_quiz_has_result_segments(self, engine):
        quiz = await engine.create_quiz("home decor")
        assert isinstance(quiz.result_segments, dict)

    @pytest.mark.asyncio
    async def test_process_response_returns_quiz_result(self, engine):
        from apps.conversion.quiz.quiz_engine import QuizResult
        quiz = await engine.create_quiz("fitness")
        result = await engine.process_response(
            quiz.quiz_id, "session-123", {"q1": "A"}, email="test@example.com"
        )
        assert isinstance(result, QuizResult)

    @pytest.mark.asyncio
    async def test_lead_score_between_0_and_1(self, engine):
        quiz = await engine.create_quiz("nutrition")
        result = await engine.process_response(quiz.quiz_id, "sess-1", {"q1": "B"})
        assert 0.0 <= result.lead_score <= 1.0

    @pytest.mark.asyncio
    async def test_email_increases_lead_score(self, engine):
        quiz = await engine.create_quiz("wellness")
        r_no_email = await engine.process_response(quiz.quiz_id, "sess-a", {"q1": "A"})
        r_with_email = await engine.process_response(quiz.quiz_id, "sess-b", {"q1": "A"}, email="x@y.com")
        assert r_with_email.lead_score >= r_no_email.lead_score

    @pytest.mark.asyncio
    async def test_quiz_analytics_returns_dict(self, engine):
        quiz = await engine.create_quiz("beauty")
        await engine.process_response(quiz.quiz_id, "s1", {"q1": "A"})
        stats = engine.quiz_analytics(quiz.quiz_id)
        assert isinstance(stats, dict)
        assert "total_responses" in stats

    @pytest.mark.asyncio
    async def test_list_quizzes_returns_list(self, engine):
        await engine.create_quiz("travel")
        result = engine.list_quizzes()
        assert isinstance(result, list)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_get_quiz_returns_dict(self, engine):
        quiz = await engine.create_quiz("cooking")
        found = await engine.get_quiz(quiz.quiz_id)
        assert found is not None
        assert found["quiz_id"] == quiz.quiz_id


# ── Lead Scorer ───────────────────────────────────────────────────────────────

class TestLeadScorer:
    @pytest.fixture
    def scorer(self):
        with patch("apps.conversion.quiz.lead_scorer.get_cache", return_value=_mock_cache()):
            from apps.conversion.quiz.lead_scorer import LeadScorer
            return LeadScorer()

    @pytest.mark.asyncio
    async def test_score_lead_returns_lead_profile(self, scorer):
        from apps.conversion.quiz.lead_scorer import LeadProfile
        lead = await scorer.score_lead("test@example.com", "quiz")
        assert isinstance(lead, LeadProfile)
        assert lead.lead_id

    @pytest.mark.asyncio
    async def test_premium_segment_higher_ltv(self, scorer):
        premium = await scorer.score_lead("p@x.com", "quiz", quiz_segment="premium")
        budget = await scorer.score_lead("b@x.com", "quiz", quiz_segment="budget")
        assert premium.ltv_estimate >= budget.ltv_estimate

    @pytest.mark.asyncio
    async def test_hot_leads_high_probability(self, scorer):
        for i in range(3):
            lead = await scorer.score_lead(f"user{i}@x.com", "quiz",
                                           behaviors=["add_to_cart", "viewed_pricing"],
                                           quiz_segment="premium")
        hot = scorer.hot_leads()
        assert isinstance(hot, list)

    @pytest.mark.asyncio
    async def test_leads_by_segment(self, scorer):
        await scorer.score_lead("a@x.com", "quiz", quiz_segment="beginner")
        await scorer.score_lead("b@x.com", "quiz", quiz_segment="premium")
        by_seg = scorer.leads_by_segment()
        assert isinstance(by_seg, dict)

    @pytest.mark.asyncio
    async def test_lead_funnel_report(self, scorer):
        await scorer.score_lead("r@x.com", "quiz")
        report = scorer.lead_funnel_report()
        assert "projected_revenue" in report
        assert "total_leads" in report

    @pytest.mark.asyncio
    async def test_enrich_lead_updates_behaviors(self, scorer):
        lead = await scorer.score_lead("e@x.com", "organic")
        enriched = await scorer.enrich_lead(lead.lead_id, ["add_to_cart"], purchase_value=99.0)
        assert enriched is not None


# ── Email Capture Engine ──────────────────────────────────────────────────────

class TestEmailCaptureEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.conversion.email.email_capture.get_cache", return_value=_mock_cache()):
            from apps.conversion.email.email_capture import EmailCaptureEngine
            return EmailCaptureEngine()

    @pytest.mark.asyncio
    async def test_capture_returns_event(self, engine):
        from apps.conversion.email.email_capture import EmailCaptureEvent
        event = await engine.capture("test@example.com", "quiz")
        assert isinstance(event, EmailCaptureEvent)
        assert event.event_id

    @pytest.mark.asyncio
    async def test_klaviyo_not_synced_without_key(self, engine):
        event = await engine.capture("no@key.com", "popup")
        assert event.klaviyo_synced is False

    @pytest.mark.asyncio
    async def test_capture_stats_returns_dict(self, engine):
        await engine.capture("a@b.com", "organic")
        stats = engine.capture_stats()
        assert "total_captures" in stats
        assert stats["total_captures"] >= 1

    @pytest.mark.asyncio
    async def test_recent_captures_returns_list(self, engine):
        await engine.capture("x@y.com", "quiz")
        recent = engine.recent_captures(limit=5)
        assert isinstance(recent, list)

    @pytest.mark.asyncio
    async def test_capture_records_source(self, engine):
        await engine.capture("s@t.com", "quiz_funnel")
        stats = engine.capture_stats()
        assert "by_source" in stats


# ── Retargeting Engine ────────────────────────────────────────────────────────

class TestRetargetingEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.ads.retargeting.retargeting_engine.get_cache", return_value=_mock_cache()):
            with patch("apps.ads.retargeting.retargeting_engine.get_ai_client", return_value=_mock_ai("You left it behind! 10% off today.")):
                from apps.ads.retargeting.retargeting_engine import RetargetingEngine
                return RetargetingEngine()

    @pytest.mark.asyncio
    async def test_create_audience_returns_audience(self, engine):
        from apps.ads.retargeting.retargeting_engine import RetargetingAudience
        aud = await engine.create_audience("Cart Abandoners", "cart_abandoners", ["u1", "u2"])
        assert isinstance(aud, RetargetingAudience)
        assert aud.audience_id

    @pytest.mark.asyncio
    async def test_create_campaign_returns_campaign(self, engine):
        from apps.ads.retargeting.retargeting_engine import RetargetingCampaign, RetargetingAudience
        aud = await engine.create_audience("Viewers", "product_viewers", ["u1"])
        campaign = await engine.create_campaign(aud, "AI Tool Pro", 50.0, "meta")
        assert isinstance(campaign, RetargetingCampaign)

    @pytest.mark.asyncio
    async def test_ctr_calculation(self, engine):
        from apps.ads.retargeting.retargeting_engine import RetargetingCampaign, RetargetingAudience
        aud = await engine.create_audience("Seg", "purchasers", ["u1"])
        camp = await engine.create_campaign(aud, "Product", 30.0)
        await engine.record_metrics(camp.campaign_id, impressions=1000, clicks=30)
        # Reload from internal state
        for c in engine._campaigns:
            if c.get("campaign_id") == camp.campaign_id:
                from apps.ads.retargeting.retargeting_engine import RetargetingCampaign
                rc = RetargetingCampaign(**{k: v for k, v in c.items()
                                           if k in RetargetingCampaign.__dataclass_fields__})
                assert abs(rc.ctr() - 0.03) < 0.001
                break

    @pytest.mark.asyncio
    async def test_roas_calculation(self, engine):
        from apps.ads.retargeting.retargeting_engine import RetargetingCampaign, RetargetingAudience
        aud = await engine.create_audience("Seg2", "cart_abandoners", ["u2"])
        camp = await engine.create_campaign(aud, "Product2", 25.0)
        await engine.record_metrics(camp.campaign_id, spend=100.0, revenue=300.0)
        for c in engine._campaigns:
            if c.get("campaign_id") == camp.campaign_id:
                from apps.ads.retargeting.retargeting_engine import RetargetingCampaign
                rc = RetargetingCampaign(**{k: v for k, v in c.items()
                                           if k in RetargetingCampaign.__dataclass_fields__})
                assert rc.roas() == 3.0
                break

    @pytest.mark.asyncio
    async def test_optimize_budget_returns_recommendations(self, engine):
        from apps.ads.retargeting.retargeting_engine import RetargetingCampaign, RetargetingAudience
        aud = await engine.create_audience("OB", "product_viewers", ["u3"])
        camp = await engine.create_campaign(aud, "Product3", 20.0)
        from apps.ads.retargeting.retargeting_engine import RetargetingCampaign as RC
        recs = await engine.optimize_budget([RC(
            campaign_id=camp.campaign_id, name="test",
            audience_id=aud.audience_id, audience_type="product_viewers",
            ad_copy="test", headline="test", budget_daily_usd=50.0,
            platform="meta", spend_usd=100.0, revenue_usd=400.0,
        )])
        assert isinstance(recs, list)

    @pytest.mark.asyncio
    async def test_cart_abandonment_sequence_returns_3_ads(self, engine):
        items = [{"product_id": "p1", "title": "Product", "price": 49.99}]
        sequence = await engine.cart_abandonment_sequence(items, "user123")
        assert isinstance(sequence, list)
        assert len(sequence) == 3

    @pytest.mark.asyncio
    async def test_campaign_analytics_returns_dict(self, engine):
        stats = engine.campaign_analytics()
        assert "total_campaigns" in stats
        assert "avg_roas" in stats

    @pytest.mark.asyncio
    async def test_top_performing_campaigns(self, engine):
        result = engine.top_performing_campaigns(limit=5)
        assert isinstance(result, list)


# ── Audience Segmenter ────────────────────────────────────────────────────────

class TestAudienceSegmenter:
    @pytest.fixture
    def segmenter(self):
        with patch("apps.ads.audiences.audience_segmenter.get_cache", return_value=_mock_cache()):
            with patch("apps.ads.audiences.audience_segmenter.get_ai_client",
                       return_value=_mock_ai("entrepreneurship\nonline business\npassive income")):
                from apps.ads.audiences.audience_segmenter import AudienceSegmenter
                return AudienceSegmenter()

    @pytest.mark.asyncio
    async def test_create_segment_returns_audience(self, segmenter):
        from apps.ads.audiences.audience_segmenter import AudienceSegment
        seg = await segmenter.create_segment("High Intent Buyers", {"intent": "purchase"})
        assert isinstance(seg, AudienceSegment)
        assert seg.segment_id

    @pytest.mark.asyncio
    async def test_suggest_lookalike_larger_audience(self, segmenter):
        seed = await segmenter.create_segment("Seed", {"intent": "buy"})
        seed.user_count = 1000
        lookalike = await segmenter.suggest_lookalike(seed, similarity_pct=0.02)
        assert lookalike.user_count > seed.user_count

    @pytest.mark.asyncio
    async def test_generate_interest_targeting_returns_list(self, segmenter):
        interests = await segmenter.generate_interest_targeting("AI tools", "marketing")
        assert isinstance(interests, list)
        assert len(interests) >= 3

    @pytest.mark.asyncio
    async def test_cac_estimate_returns_dict(self, segmenter):
        seg = await segmenter.create_segment("Buyers", {"age": "25-45"})
        result = segmenter.cac_estimate(seg, product_price=99.0, expected_cvr=0.02)
        assert "cpc" in result
        assert "cac" in result
        assert "profitable" in result

    @pytest.mark.asyncio
    async def test_segment_analytics_returns_dict(self, segmenter):
        await segmenter.create_segment("Test", {})
        stats = segmenter.segment_analytics()
        assert "total_segments" in stats
        assert stats["total_segments"] >= 1

    @pytest.mark.asyncio
    async def test_exclusion_audiences_returns_list(self, segmenter):
        exclusions = segmenter.generate_exclusion_audiences()
        assert isinstance(exclusions, list)
        assert len(exclusions) >= 3
