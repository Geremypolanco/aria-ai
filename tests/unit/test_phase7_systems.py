"""
Phase 7 tests — Strategic Economic Intelligence.
Covers: TrendAnalyzer, CompetitorMonitor, DemandScorer, OpportunityFinder,
ContentQualityEngine, EngagementPredictor, ViralityEngine, EconomicLearner,
ConversionLearner, PersonaEngine, BehaviorAnalyzer, PersuasionEngine,
PriorityEngine, LeverageAnalyzer, StrategicForecaster, StyleEngine,
DifferentiationEngine, CreativeIdentityManager, OperationsManager,
ExecutiveDashboard, CashflowEngine, BusinessAnalytics.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Shared mock helpers ────────────────────────────────────────────────────────

def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content="AI response"):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


# ══════════════════════════════════════════════════════════════════════════════
# 1. TREND ANALYZER
# ══════════════════════════════════════════════════════════════════════════════

class TestTrendAnalyzer:
    @pytest.fixture
    def analyzer(self):
        with patch("apps.market.trends.trend_analyzer.get_cache", return_value=_mock_cache()):
            with patch("apps.market.trends.trend_analyzer.get_ai_client", return_value=_mock_ai()):
                from apps.market.trends.trend_analyzer import TrendAnalyzer
                return TrendAnalyzer()

    @pytest.mark.asyncio
    async def test_analyze_niche(self, analyzer):
        report = await analyzer.analyze_niche("AI tools", ["youtube", "twitter"])
        assert report.niche == "AI tools"
        assert isinstance(report.signals, list)
        assert isinstance(report.top_keywords, list)
        assert isinstance(report.emerging_topics, list)

    @pytest.mark.asyncio
    async def test_detect_emerging(self, analyzer):
        topics = await analyzer.detect_emerging("ecommerce")
        assert isinstance(topics, list)

    @pytest.mark.asyncio
    async def test_forecast_trend(self, analyzer):
        result = await analyzer.forecast_trend("AI automation", days=30)
        assert "keyword" in result
        assert "direction" in result
        assert result["direction"] in ("up", "down", "stable")
        assert 0.0 <= result.get("confidence", 0) <= 1.0

    @pytest.mark.asyncio
    async def test_trending_now(self, analyzer):
        signals = await analyzer.trending_now()
        assert isinstance(signals, list)

    def test_summary(self, analyzer):
        s = analyzer.summary()
        assert "niches_tracked" in s


# ══════════════════════════════════════════════════════════════════════════════
# 2. COMPETITOR MONITOR
# ══════════════════════════════════════════════════════════════════════════════

class TestCompetitorMonitor:
    @pytest.fixture
    def monitor(self):
        with patch("apps.market.competition.competitor_monitor.get_cache", return_value=_mock_cache()):
            with patch("apps.market.competition.competitor_monitor.get_ai_client", return_value=_mock_ai()):
                from apps.market.competition.competitor_monitor import CompetitorMonitor
                return CompetitorMonitor()

    @pytest.mark.asyncio
    async def test_add_competitor(self, monitor):
        profile = await monitor.add_competitor("Acme Corp", "acme.com", "saas")
        assert profile.competitor_id
        assert profile.name == "Acme Corp"
        assert profile.domain == "acme.com"

    @pytest.mark.asyncio
    async def test_analyze_competitor(self, monitor):
        profile = await monitor.add_competitor("Rival Inc", "rival.com", "ecommerce")
        result = await monitor.analyze_competitor(profile.competitor_id)
        assert result is not None

    @pytest.mark.asyncio
    async def test_find_gaps(self, monitor):
        await monitor.add_competitor("Gap Co", "gap.com", "content")
        gaps = await monitor.find_gaps("content")
        assert isinstance(gaps, list)

    @pytest.mark.asyncio
    async def test_competitive_landscape(self, monitor):
        await monitor.add_competitor("Player A", "a.com", "tech")
        landscape = await monitor.competitive_landscape("tech")
        assert "total_competitors" in landscape

    def test_summary(self, monitor):
        assert isinstance(monitor.summary(), dict)


# ══════════════════════════════════════════════════════════════════════════════
# 3. DEMAND SCORER
# ══════════════════════════════════════════════════════════════════════════════

class TestDemandScorer:
    @pytest.fixture
    def scorer(self):
        with patch("apps.market.demand.demand_scorer.get_cache", return_value=_mock_cache()):
            with patch("apps.market.demand.demand_scorer.get_ai_client", return_value=_mock_ai()):
                from apps.market.demand.demand_scorer import DemandScorer
                return DemandScorer()

    @pytest.mark.asyncio
    async def test_score_keyword(self, scorer):
        score = await scorer.score_keyword("best AI tools", "tech")
        assert score.keyword == "best AI tools"
        assert 0 <= score.demand_score <= 100
        assert 0 <= score.supply_score <= 100
        assert 0 <= score.opportunity_score <= 100

    @pytest.mark.asyncio
    async def test_score_batch(self, scorer):
        keywords = ["buy AI software", "AI review", "how to use ChatGPT"]
        results = await scorer.score_batch(keywords, "tech")
        assert len(results) == 3
        # Sorted by opportunity_score desc
        scores = [r.opportunity_score for r in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_top_opportunities(self, scorer):
        await scorer.score_keyword("affiliate marketing", "marketing")
        opps = await scorer.top_opportunities("marketing", limit=5)
        assert isinstance(opps, list)

    @pytest.mark.asyncio
    async def test_detect_underserved(self, scorer):
        await scorer.score_keyword("best passive income", "finance")
        keywords = await scorer.detect_underserved("finance")
        assert isinstance(keywords, list)

    def test_summary(self, scorer):
        s = scorer.summary()
        assert "total_scored" in s


# ══════════════════════════════════════════════════════════════════════════════
# 4. OPPORTUNITY FINDER
# ══════════════════════════════════════════════════════════════════════════════

class TestOpportunityFinder:
    @pytest.fixture
    def finder(self):
        with patch("apps.market.opportunities.opportunity_finder.get_cache", return_value=_mock_cache()):
            with patch("apps.market.opportunities.opportunity_finder.get_ai_client", return_value=_mock_ai()):
                from apps.market.opportunities.opportunity_finder import OpportunityFinder
                return OpportunityFinder()

    @pytest.mark.asyncio
    async def test_find_opportunities(self, finder):
        opps = await finder.find_opportunities("AI productivity", budget_usd=500.0)
        assert len(opps) >= 1
        for o in opps:
            assert o.opp_id
            assert o.total_score >= 0
            assert o.estimated_monthly_revenue_usd >= 0

    @pytest.mark.asyncio
    async def test_rank_by_roi(self, finder):
        opps = await finder.find_opportunities("dropshipping", budget_usd=1000.0)
        ranked = await finder.rank_by_roi(opps)
        assert len(ranked) == len(opps)

    @pytest.mark.asyncio
    async def test_quick_wins(self, finder):
        wins = await finder.quick_wins("content creation")
        assert isinstance(wins, list)
        assert all(w.time_to_first_revenue_days <= 14 for w in wins)

    def test_summary(self, finder):
        assert isinstance(finder.summary(), dict)


# ══════════════════════════════════════════════════════════════════════════════
# 5. CONTENT QUALITY ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class TestContentQualityEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.content.intelligence.content_quality_engine.get_cache", return_value=_mock_cache()):
            with patch("apps.content.intelligence.content_quality_engine.get_ai_client", return_value=_mock_ai()):
                from apps.content.intelligence.content_quality_engine import ContentQualityEngine
                return ContentQualityEngine()

    @pytest.mark.asyncio
    async def test_analyze_returns_report(self, engine):
        content = "Did you know that 95% of marketers fail? Here's the shocking truth about AI tools that actually work. Step 1: Start with data. Step 2: Test everything. Buy now before the price increases!"
        report = await engine.analyze(content, platform="linkedin")
        assert report.content_id
        assert report.overall_score >= 0
        assert report.grade in ("A", "B", "C", "D", "F")
        assert isinstance(report.dimensions, list)
        assert len(report.dimensions) > 0

    @pytest.mark.asyncio
    async def test_analyze_low_quality(self, engine):
        report = await engine.analyze("ok content", platform="blog")
        assert report.grade in ("C", "D", "F")

    @pytest.mark.asyncio
    async def test_score_hook(self, engine):
        result = await engine.score_hook("You won't believe what happened to my Shopify store last month")
        assert "score" in result
        assert 0 <= result["score"] <= 10

    @pytest.mark.asyncio
    async def test_analyze_batch(self, engine):
        contents = ["Short content", "Longer detailed content with numbers 5 and questions? Buy now!"]
        reports = await engine.analyze_batch(contents, platform="twitter")
        assert len(reports) == 2
        # Sorted by overall_score desc
        assert reports[0].overall_score >= reports[1].overall_score

    @pytest.mark.asyncio
    async def test_improvement_roadmap(self, engine):
        roadmap = await engine.improvement_roadmap("Generic content here.", platform="blog")
        assert isinstance(roadmap, list)
        assert len(roadmap) >= 1

    def test_summary(self, engine):
        s = engine.summary()
        assert "total_analyzed" in s


# ══════════════════════════════════════════════════════════════════════════════
# 6. ENGAGEMENT PREDICTOR
# ══════════════════════════════════════════════════════════════════════════════

class TestEngagementPredictor:
    @pytest.fixture
    def predictor(self):
        with patch("apps.content.scoring.engagement_predictor.get_ai_client", return_value=_mock_ai()):
            from apps.content.scoring.engagement_predictor import EngagementPredictor
            return EngagementPredictor()

    @pytest.mark.asyncio
    async def test_predict_twitter(self, predictor):
        pred = await predictor.predict("Check out these 5 AI hacks! #AI", "twitter", 5000)
        assert pred.platform == "twitter"
        assert 0 <= pred.predicted_engagement_rate <= 1
        assert pred.predicted_views >= 0
        assert 0 <= pred.viral_probability <= 1

    @pytest.mark.asyncio
    async def test_predict_tiktok_higher_engagement(self, predictor):
        twitter_pred = await predictor.predict("content", "twitter", 1000)
        tiktok_pred = await predictor.predict("content", "tiktok", 1000)
        assert tiktok_pred.predicted_engagement_rate > twitter_pred.predicted_engagement_rate

    @pytest.mark.asyncio
    async def test_compare_variations(self, predictor):
        variations = [
            "5 secrets to double your income",
            "income tips",
            "How I made $10K? The shocking truth revealed!",
        ]
        results = await predictor.compare_variations(variations, "youtube")
        assert len(results) == 3
        assert results[0]["rank"] == 1

    @pytest.mark.asyncio
    async def test_best_time_to_post(self, predictor):
        time_str = await predictor.best_time_to_post("instagram")
        assert isinstance(time_str, str)
        assert len(time_str) > 0


# ══════════════════════════════════════════════════════════════════════════════
# 7. VIRALITY ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class TestViralityEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.content.virality.virality_engine.get_ai_client", return_value=_mock_ai("Alt title 1\nAlt title 2\nAlt title 3")):
            from apps.content.virality.virality_engine import ViralityEngine
            return ViralityEngine()

    @pytest.mark.asyncio
    async def test_analyze_viral_content(self, engine):
        content = "The SHOCKING secret nobody tells you about passive income — only 3 spots left!"
        analysis = await engine.analyze(content, "youtube")
        assert 0 <= analysis.virality_score <= 1
        assert isinstance(analysis.patterns_detected, list)
        assert analysis.emotional_trigger

    @pytest.mark.asyncio
    async def test_analyze_detects_patterns(self, engine):
        from apps.content.virality.virality_engine import ViralPattern
        content = "SHOCKING: How I made $5000 — limited time only!"
        analysis = await engine.analyze(content)
        assert len(analysis.patterns_detected) >= 1

    @pytest.mark.asyncio
    async def test_optimize_title(self, engine):
        alternatives = await engine.optimize_title("How to make money online", "youtube")
        assert isinstance(alternatives, list)
        assert len(alternatives) >= 1

    @pytest.mark.asyncio
    async def test_predict_shares(self, engine):
        result = await engine.predict_shares("Amazing content that goes viral!", 10000)
        assert "predicted_shares" in result
        assert "viral_threshold" in result
        assert 0 <= result.get("probability_viral", 0) <= 1

    @pytest.mark.asyncio
    async def test_audience_fatigue_check(self, engine):
        history = [
            "SHOCKING secret revealed!",
            "You won't believe this SHOCKING news!",
            "SHOCKING truth about AI — revealed!",
        ]
        result = await engine.audience_fatigue_check(history)
        assert "fatigue_detected" in result
        assert "diversity_score" in result


# ══════════════════════════════════════════════════════════════════════════════
# 8. ECONOMIC LEARNER
# ══════════════════════════════════════════════════════════════════════════════

class TestEconomicLearner:
    @pytest.fixture
    def learner(self):
        with patch("apps.learning.economics.economic_learner.get_cache", return_value=_mock_cache()):
            from apps.learning.economics.economic_learner import EconomicLearner
            return EconomicLearner()

    @pytest.mark.asyncio
    async def test_record_outcome(self, learner):
        from apps.learning.economics.economic_learner import CampaignOutcome
        outcome = CampaignOutcome(
            campaign_id="c1", name="Black Friday", channel="email",
            spend_usd=500.0, revenue_usd=2000.0, conversions=40,
            impressions=10000, clicks=400, outcome_date=time.time(), tags=["email"],
        )
        await learner.record_outcome(outcome)
        assert len(learner._outcomes) == 1

    @pytest.mark.asyncio
    async def test_analyze_channels(self, learner):
        from apps.learning.economics.economic_learner import CampaignOutcome
        for i, ch in enumerate(["email", "social", "email"]):
            await learner.record_outcome(CampaignOutcome(
                campaign_id=f"c{i}", name=f"Campaign {i}", channel=ch,
                spend_usd=100.0, revenue_usd=300.0 + i*50, conversions=10,
                impressions=1000, clicks=100, outcome_date=time.time(), tags=[],
            ))
        insights = await learner.analyze_channels()
        assert len(insights) >= 1
        assert all(i.avg_roi > 0 for i in insights)

    @pytest.mark.asyncio
    async def test_best_channels(self, learner):
        from apps.learning.economics.economic_learner import CampaignOutcome
        await learner.record_outcome(CampaignOutcome(
            campaign_id="x1", name="X", channel="paid_search",
            spend_usd=200.0, revenue_usd=1000.0, conversions=20,
            impressions=5000, clicks=200, outcome_date=time.time(), tags=[],
        ))
        channels = await learner.best_channels(top_k=3)
        assert isinstance(channels, list)

    @pytest.mark.asyncio
    async def test_predict_roi(self, learner):
        pred = await learner.predict_roi("email", 500.0)
        assert "predicted_revenue_usd" in pred
        assert "confidence" in pred

    @pytest.mark.asyncio
    async def test_learning_report(self, learner):
        report = await learner.learning_report()
        assert "total_campaigns" in report
        assert "avg_roi" in report

    def test_summary(self, learner):
        assert isinstance(learner.summary(), dict)


# ══════════════════════════════════════════════════════════════════════════════
# 9. CONVERSION LEARNER
# ══════════════════════════════════════════════════════════════════════════════

class TestConversionLearner:
    @pytest.fixture
    def learner(self):
        with patch("apps.learning.conversion.conversion_learner.get_cache", return_value=_mock_cache()):
            from apps.learning.conversion.conversion_learner import ConversionLearner
            return ConversionLearner()

    @pytest.mark.asyncio
    async def test_record_event(self, learner):
        from apps.learning.conversion.conversion_learner import ConversionEvent
        ev = ConversionEvent(
            event_id="e1", session_id="s1", stage="awareness",
            converted=False, time_to_convert_seconds=0.0,
            channel="organic", device="mobile", value_usd=0.0,
            timestamp=time.time(), metadata={},
        )
        await learner.record(ev)
        assert len(learner._events) == 1

    @pytest.mark.asyncio
    async def test_funnel_analysis(self, learner):
        from apps.learning.conversion.conversion_learner import ConversionEvent
        stages = ["awareness", "consideration", "purchase"]
        for i, stage in enumerate(stages * 3):
            await learner.record(ConversionEvent(
                event_id=f"e{i}", session_id=f"s{i}", stage=stage,
                converted=(stage == "purchase"), time_to_convert_seconds=60.0,
                channel="email", device="desktop", value_usd=50.0 if stage == "purchase" else 0.0,
                timestamp=time.time(), metadata={},
            ))
        insights = await learner.funnel_analysis()
        assert isinstance(insights, list)

    @pytest.mark.asyncio
    async def test_identify_friction_points(self, learner):
        points = await learner.identify_friction_points()
        assert isinstance(points, list)

    @pytest.mark.asyncio
    async def test_conversion_forecast(self, learner):
        forecast = await learner.conversion_forecast(100, current_cvr=0.02)
        assert "required_visitors" in forecast
        assert forecast["required_visitors"] >= 100

    def test_summary(self, learner):
        assert isinstance(learner.summary(), dict)


# ══════════════════════════════════════════════════════════════════════════════
# 10. PERSONA ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class TestPersonaEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.psychology.personas.persona_engine.get_cache", return_value=_mock_cache()):
            with patch("apps.psychology.personas.persona_engine.get_ai_client", return_value=_mock_ai()):
                from apps.psychology.personas.persona_engine import PersonaEngine
                return PersonaEngine()

    @pytest.mark.asyncio
    async def test_create_persona(self, engine):
        from apps.psychology.personas.persona_engine import PersonaArchetype
        persona = await engine.create_persona("AI tools", PersonaArchetype.ACHIEVER, "Alex")
        assert persona.persona_id
        assert persona.archetype == PersonaArchetype.ACHIEVER
        assert persona.primary_pain
        assert persona.primary_desire

    @pytest.mark.asyncio
    async def test_get_persona(self, engine):
        from apps.psychology.personas.persona_engine import PersonaArchetype
        persona = await engine.create_persona("ecommerce", PersonaArchetype.OPTIMIZER)
        fetched = await engine.get_persona(persona.persona_id)
        assert fetched is not None
        assert fetched.persona_id == persona.persona_id

    @pytest.mark.asyncio
    async def test_list_personas(self, engine):
        from apps.psychology.personas.persona_engine import PersonaArchetype
        await engine.create_persona("tech", PersonaArchetype.EXPLORER)
        await engine.create_persona("tech", PersonaArchetype.SOCIALIZER)
        personas = await engine.list_personas()
        assert len(personas) >= 2

    @pytest.mark.asyncio
    async def test_match_content_to_persona(self, engine):
        from apps.psychology.personas.persona_engine import PersonaArchetype
        persona = await engine.create_persona("fitness", PersonaArchetype.ACHIEVER)
        result = await engine.match_content_to_persona(
            "10 proven ways to maximize your results and achieve peak performance",
            persona.persona_id,
        )
        assert "match_score" in result
        assert 0 <= result["match_score"] <= 1

    @pytest.mark.asyncio
    async def test_generate_niche_personas(self, engine):
        from apps.psychology.personas.persona_engine import PersonaArchetype
        personas = await engine.generate_niche_personas("dropshipping", count=3)
        assert len(personas) >= 1

    def test_summary(self, engine):
        assert isinstance(engine.summary(), dict)


# ══════════════════════════════════════════════════════════════════════════════
# 11. BEHAVIOR ANALYZER
# ══════════════════════════════════════════════════════════════════════════════

class TestBehaviorAnalyzer:
    @pytest.fixture
    def analyzer(self):
        with patch("apps.psychology.behavior.behavior_analyzer.get_cache", return_value=_mock_cache()):
            from apps.psychology.behavior.behavior_analyzer import BehaviorAnalyzer
            return BehaviorAnalyzer()

    @pytest.mark.asyncio
    async def test_analyze_user(self, analyzer):
        actions = [
            {"type": "view", "product": "Widget A"},
            {"type": "add_to_cart", "product": "Widget A"},
            {"type": "view", "product": "Widget B"},
        ]
        profile = await analyzer.analyze_user("user_001", actions)
        assert profile.user_id == "user_001"
        assert 0 <= profile.intent_score <= 1
        assert isinstance(profile.next_best_action, str)

    @pytest.mark.asyncio
    async def test_predict_churn(self, analyzer):
        await analyzer.analyze_user("user_002", [{"type": "refund"}, {"type": "view"}])
        result = await analyzer.predict_churn("user_002")
        assert "churn_probability" in result
        assert 0 <= result["churn_probability"] <= 1

    @pytest.mark.asyncio
    async def test_buying_intent_score(self, analyzer):
        await analyzer.analyze_user("user_003", [{"type": "add_to_cart"}, {"type": "purchase"}])
        score = await analyzer.buying_intent_score("user_003")
        assert 0 <= score <= 1

    @pytest.mark.asyncio
    async def test_segment_users(self, analyzer):
        await analyzer.analyze_user("u1", [{"type": "add_to_cart"}])
        await analyzer.analyze_user("u2", [{"type": "view"}])
        segments = await analyzer.segment_users(["u1", "u2"])
        assert isinstance(segments, dict)
        assert "high_intent" in segments or "new" in segments

    def test_summary(self, analyzer):
        assert isinstance(analyzer.summary(), dict)


# ══════════════════════════════════════════════════════════════════════════════
# 12. PERSUASION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class TestPersuasionEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.psychology.conversion.persuasion_engine.get_ai_client", return_value=_mock_ai("Buy now — only 3 left!")):
            from apps.psychology.conversion.persuasion_engine import PersuasionEngine
            return PersuasionEngine()

    @pytest.mark.asyncio
    async def test_recommend_tactics(self, engine):
        tactics = await engine.recommend_tactics("ecommerce product launch", "desire")
        assert isinstance(tactics, list)
        assert len(tactics) >= 1
        assert all(t.estimated_cvr_lift > 0 for t in tactics)

    @pytest.mark.asyncio
    async def test_generate_copy(self, engine):
        from apps.psychology.conversion.persuasion_engine import PersuasionPrinciple
        copy = await engine.generate_copy(PersuasionPrinciple.SCARCITY, "AI Tool Pro", "marketers")
        assert isinstance(copy, str)
        assert len(copy) > 0

    @pytest.mark.asyncio
    async def test_score_copy(self, engine):
        result = await engine.score_copy("Only 3 spots left! Join 5000+ customers who trust us. Expert-approved.")
        assert "persuasion_score" in result
        assert 0 <= result["persuasion_score"] <= 1
        assert "principles_detected" in result

    @pytest.mark.asyncio
    async def test_optimize_cta(self, engine):
        from apps.psychology.conversion.persuasion_engine import PersuasionPrinciple
        variations = await engine.optimize_cta("Click here", PersuasionPrinciple.SCARCITY)
        assert isinstance(variations, list)
        assert len(variations) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# 13. PRIORITY ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class TestPriorityEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.strategy.prioritization.priority_engine.get_cache", return_value=_mock_cache()):
            from apps.strategy.prioritization.priority_engine import PriorityEngine
            return PriorityEngine()

    @pytest.mark.asyncio
    async def test_add_action(self, engine):
        from apps.strategy.prioritization.priority_engine import StrategyAction
        action = StrategyAction(
            action_id="a1", title="Launch SEO blog", description="Start content",
            category="content", estimated_roi=3.0, effort_score=4.0,
            time_to_result_days=30, leverage_score=0.7, compounding=True, dependencies=[],
        )
        result = await engine.add_action(action)
        assert result.priority_score > 0

    @pytest.mark.asyncio
    async def test_rank_actions_sorted(self, engine):
        from apps.strategy.prioritization.priority_engine import StrategyAction
        low = StrategyAction(action_id="l1", title="Low ROI", description="", category="content",
                             estimated_roi=0.5, effort_score=9.0, time_to_result_days=90,
                             leverage_score=0.1, compounding=False, dependencies=[])
        high = StrategyAction(action_id="h1", title="High ROI", description="", category="seo",
                              estimated_roi=10.0, effort_score=2.0, time_to_result_days=7,
                              leverage_score=0.9, compounding=True, dependencies=[])
        ranked = await engine.rank_actions([low, high])
        assert ranked[0].title == "High ROI"

    @pytest.mark.asyncio
    async def test_top_priorities(self, engine):
        from apps.strategy.prioritization.priority_engine import StrategyAction
        for i in range(7):
            await engine.add_action(StrategyAction(
                action_id=f"a{i}", title=f"Action {i}", description="", category="content",
                estimated_roi=float(i), effort_score=5.0, time_to_result_days=30,
                leverage_score=0.5, compounding=False, dependencies=[],
            ))
        top = await engine.top_priorities(limit=5)
        assert len(top) == 5

    @pytest.mark.asyncio
    async def test_quick_wins(self, engine):
        from apps.strategy.prioritization.priority_engine import StrategyAction
        await engine.add_action(StrategyAction(
            action_id="qw1", title="Quick Win", description="", category="content",
            estimated_roi=2.0, effort_score=2.0, time_to_result_days=7,
            leverage_score=0.6, compounding=False, dependencies=[],
        ))
        await engine.add_action(StrategyAction(
            action_id="slow1", title="Slow Action", description="", category="seo",
            estimated_roi=5.0, effort_score=8.0, time_to_result_days=60,
            leverage_score=0.5, compounding=True, dependencies=[],
        ))
        wins = await engine.quick_wins()
        assert all(a.effort_score <= 3 and a.time_to_result_days <= 14 for a in wins)

    def test_summary(self, engine):
        assert isinstance(engine.summary(), dict)


# ══════════════════════════════════════════════════════════════════════════════
# 14. LEVERAGE ANALYZER
# ══════════════════════════════════════════════════════════════════════════════

class TestLeverageAnalyzer:
    @pytest.fixture
    def analyzer(self):
        from apps.strategy.leverage.leverage_analyzer import LeverageAnalyzer
        return LeverageAnalyzer()

    @pytest.mark.asyncio
    async def test_identify_leverage_points(self, analyzer):
        metrics = {
            "traffic": 5000,
            "conversion_rate": 0.01,
            "avg_order_value": 45.0,
            "retention_rate": 0.35,
            "referral_rate": 0.02,
        }
        points = await analyzer.identify_leverage_points(metrics)
        assert len(points) >= 1
        assert all(p.leverage_multiplier >= 1 for p in points)

    @pytest.mark.asyncio
    async def test_bottleneck_analysis(self, analyzer):
        metrics = {"traffic": 100, "conversion_rate": 0.005, "avg_order_value": 30.0, "retention_rate": 0.8, "referral_rate": 0.1}
        result = await analyzer.bottleneck_analysis(metrics)
        assert "primary_bottleneck" in result
        assert "estimated_revenue_lift_pct" in result

    @pytest.mark.asyncio
    async def test_constraint_removal_plan(self, analyzer):
        plan = await analyzer.constraint_removal_plan("conversion_rate")
        assert isinstance(plan, list)
        assert len(plan) >= 1
        assert all("action" in step for step in plan)

    @pytest.mark.asyncio
    async def test_simulate_improvement(self, analyzer):
        metrics = {"traffic": 1000, "conversion_rate": 0.02, "avg_order_value": 50.0, "retention_rate": 0.5, "referral_rate": 0.05}
        result = await analyzer.simulate_improvement(metrics, "conversion_rate", 0.5)
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════════════════════
# 15. STRATEGIC FORECASTER
# ══════════════════════════════════════════════════════════════════════════════

class TestStrategicForecaster:
    @pytest.fixture
    def forecaster(self):
        with patch("apps.strategy.forecasting.strategic_forecaster.get_cache", return_value=_mock_cache()):
            from apps.strategy.forecasting.strategic_forecaster import StrategicForecaster
            return StrategicForecaster()

    @pytest.mark.asyncio
    async def test_exponential_forecast(self, forecaster):
        from apps.strategy.forecasting.strategic_forecaster import GrowthModel
        scenario = await forecaster.forecast(1000.0, 0.1, months=12, model=GrowthModel.EXPONENTIAL)
        assert scenario.scenario_id
        assert len(scenario.projections) == 12  # months 1..12
        assert scenario.projections[-1]["revenue_usd"] > scenario.projections[0]["revenue_usd"]

    @pytest.mark.asyncio
    async def test_linear_forecast(self, forecaster):
        from apps.strategy.forecasting.strategic_forecaster import GrowthModel
        scenario = await forecaster.forecast(500.0, 0.05, months=6, model=GrowthModel.LINEAR)
        assert len(scenario.projections) >= 6

    @pytest.mark.asyncio
    async def test_compare_scenarios(self, forecaster):
        from apps.strategy.forecasting.strategic_forecaster import GrowthModel
        s1 = await forecaster.forecast(1000.0, 0.05, months=12, model=GrowthModel.LINEAR, name="conservative")
        s2 = await forecaster.forecast(1000.0, 0.20, months=12, model=GrowthModel.EXPONENTIAL, name="aggressive")
        result = await forecaster.compare_scenarios([s1, s2])
        assert "best_12m_revenue" in result
        assert "recommended" in result

    @pytest.mark.asyncio
    async def test_stress_test(self, forecaster):
        from apps.strategy.forecasting.strategic_forecaster import GrowthModel
        base = await forecaster.forecast(2000.0, 0.1, months=12, model=GrowthModel.EXPONENTIAL)
        stressed = await forecaster.stress_test(base, shock_month=6, shock_pct=0.3)
        assert stressed.total_projected_revenue < base.total_projected_revenue

    def test_summary(self, forecaster):
        assert isinstance(forecaster.summary(), dict)


# ══════════════════════════════════════════════════════════════════════════════
# 16. STYLE ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class TestStyleEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.creative.style.style_engine.get_cache", return_value=_mock_cache()):
            from apps.creative.style.style_engine import StyleEngine
            return StyleEngine()

    @pytest.mark.asyncio
    async def test_create_profile(self, engine):
        profile = await engine.create_profile("TechBrand", "tech")
        assert profile.profile_id
        assert profile.name == "TechBrand"
        assert isinstance(profile.dimensions, dict)

    @pytest.mark.asyncio
    async def test_evolve_style(self, engine):
        profile = await engine.create_profile("FashionBrand", "fashion")
        evolved = await engine.evolve_style(profile.profile_id, direction="bolder")
        assert evolved is not None
        assert evolved.evolution_count >= 1

    @pytest.mark.asyncio
    async def test_check_novelty(self, engine):
        profile = await engine.create_profile("Brand X", "health")
        result = await engine.check_novelty(profile.profile_id, "Revolutionary game-changing seamless solution!")
        assert "novelty_score" in result
        assert "detected_cliches" in result

    @pytest.mark.asyncio
    async def test_style_consistency_audit(self, engine):
        profile = await engine.create_profile("Consistent Brand", "finance")
        result = await engine.style_consistency_audit(
            profile.profile_id,
            ["Professional tone here.", "Also professional and clear.", "Direct and authoritative."],
        )
        assert "consistency_score" in result

    def test_summary(self, engine):
        assert isinstance(engine.summary(), dict)


# ══════════════════════════════════════════════════════════════════════════════
# 17. DIFFERENTIATION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class TestDifferentiationEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.creative.differentiation.differentiation_engine.get_ai_client", return_value=_mock_ai("Try: 'Specifically designed for X'")):
            from apps.creative.differentiation.differentiation_engine import DifferentiationEngine
            return DifferentiationEngine()

    @pytest.mark.asyncio
    async def test_analyze_generic_content(self, engine):
        from apps.creative.differentiation.differentiation_engine import GenericityRisk
        content = "In today's fast-paced world, our cutting-edge innovative solution is a game-changer that leverages synergies."
        report = await engine.analyze(content)
        assert report.genericity_score > 0
        assert report.risk_level in (GenericityRisk.HIGH, GenericityRisk.CRITICAL, GenericityRisk.MEDIUM)

    @pytest.mark.asyncio
    async def test_analyze_unique_content(self, engine):
        from apps.creative.differentiation.differentiation_engine import GenericityRisk
        content = "In Q3 2024, my Shopify store hit $47K using a 3-step product bundling strategy nobody talks about."
        report = await engine.analyze(content)
        assert report.risk_level in (GenericityRisk.LOW, GenericityRisk.MEDIUM)

    @pytest.mark.asyncio
    async def test_purge_generic(self, engine):
        content = "This game-changer is a cutting-edge innovative solution."
        result = await engine.purge_generic(content)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_generate_unique_angle(self, engine):
        angles = await engine.generate_unique_angle("passive income", "finance")
        assert isinstance(angles, list)
        assert len(angles) >= 1

    @pytest.mark.asyncio
    async def test_audience_fatigue_risk(self, engine):
        history = ["SHOCKING: game-changer!", "game-changer revealed!", "Another game-changer"]
        result = await engine.audience_fatigue_risk(history)
        assert "fatigue_risk" in result
        assert "overused_patterns" in result


# ══════════════════════════════════════════════════════════════════════════════
# 18. CREATIVE IDENTITY MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class TestCreativeIdentityManager:
    @pytest.fixture
    def manager(self):
        with patch("apps.creative.identity.creative_identity.get_cache", return_value=_mock_cache()):
            with patch("apps.creative.identity.creative_identity.get_ai_client", return_value=_mock_ai()):
                from apps.creative.identity.creative_identity import CreativeIdentityManager
                return CreativeIdentityManager()

    @pytest.mark.asyncio
    async def test_create_identity(self, manager):
        identity = await manager.create_identity("TechBrand", "tech")
        assert identity.identity_id
        assert identity.brand_name == "TechBrand"
        assert identity.voice_signature
        assert isinstance(identity.content_archetypes, list)

    @pytest.mark.asyncio
    async def test_refresh_identity(self, manager):
        identity = await manager.create_identity("FreshBrand", "fashion")
        refreshed = await manager.refresh_identity(identity.identity_id, "more playful")
        assert refreshed is not None
        assert len(refreshed.evolution_history) >= 1

    @pytest.mark.asyncio
    async def test_get_identity(self, manager):
        identity = await manager.create_identity("GetBrand", "health")
        fetched = await manager.get_identity(identity.identity_id)
        assert fetched is not None
        assert fetched.brand_name == "GetBrand"

    @pytest.mark.asyncio
    async def test_apply_identity(self, manager):
        identity = await manager.create_identity("ApplyBrand", "finance")
        result = await manager.apply_identity(identity.identity_id, "Generic content here")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_summary(self, manager):
        assert isinstance(manager.summary(), dict)


# ══════════════════════════════════════════════════════════════════════════════
# 22. OPERATIONS MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class TestOperationsManager:
    @pytest.fixture
    def manager(self):
        with patch("apps.business.operations.operations_manager.get_cache", return_value=_mock_cache()):
            from apps.business.operations.operations_manager import OperationsManager
            return OperationsManager()

    @pytest.mark.asyncio
    async def test_record_metric(self, manager):
        metric = await manager.record_metric("revenue_usd", 3500.0, 5000.0, "USD", "finance")
        assert metric.metric_id
        assert metric.value == 3500.0
        assert metric.target == 5000.0

    @pytest.mark.asyncio
    async def test_kpi_dashboard(self, manager):
        await manager.record_metric("conversion_rate", 0.025, 0.03, "%", "marketing")
        await manager.record_metric("churn_rate", 0.05, 0.03, "%", "retention")
        dash = await manager.kpi_dashboard()
        assert isinstance(dash, dict)

    @pytest.mark.asyncio
    async def test_operational_health(self, manager):
        await manager.record_metric("revenue", 8000.0, 10000.0, "USD", "finance")
        await manager.record_metric("cac", 45.0, 50.0, "USD", "marketing")
        health = await manager.operational_health()
        assert "overall_health_score" in health
        assert 0 <= health["overall_health_score"] <= 1

    @pytest.mark.asyncio
    async def test_optimization_opportunities(self, manager):
        await manager.record_metric("email_cvr", 0.01, 0.05, "%", "email")
        opps = await manager.optimization_opportunities()
        assert isinstance(opps, list)

    def test_summary(self, manager):
        assert isinstance(manager.summary(), dict)


# ══════════════════════════════════════════════════════════════════════════════
# 23. EXECUTIVE DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

class TestExecutiveDashboard:
    @pytest.fixture
    def dashboard(self):
        with patch("apps.business.executive.executive_dashboard.get_cache", return_value=_mock_cache()):
            from apps.business.executive.executive_dashboard import ExecutiveDashboard
            return ExecutiveDashboard()

    @pytest.mark.asyncio
    async def test_generate_snapshot(self, dashboard):
        snapshot = await dashboard.generate_snapshot("weekly", {
            "revenue_usd": 5000.0, "revenue_growth_pct": 0.15,
            "customer_count": 120, "customer_growth_pct": 0.10,
            "avg_order_value": 42.0, "conversion_rate": 0.025,
            "churn_rate": 0.05, "net_profit_usd": 1500.0,
            "top_channels": ["email", "organic"],
        })
        assert snapshot.snapshot_id
        assert snapshot.revenue_usd == 5000.0
        assert isinstance(snapshot.alerts, list)

    @pytest.mark.asyncio
    async def test_snapshot_alerts_churn(self, dashboard):
        snapshot = await dashboard.generate_snapshot("weekly", {
            "revenue_usd": 1000.0, "churn_rate": 0.15,
            "conversion_rate": 0.02, "revenue_growth_pct": -0.1,
        })
        assert any("churn" in a.lower() or "revenue" in a.lower() for a in snapshot.alerts)

    @pytest.mark.asyncio
    async def test_weekly_report(self, dashboard):
        report = await dashboard.weekly_report()
        assert isinstance(report, dict)

    @pytest.mark.asyncio
    async def test_board_summary(self, dashboard):
        await dashboard.generate_snapshot("weekly", {"revenue_usd": 3000.0})
        summary = await dashboard.board_summary()
        assert isinstance(summary, dict)

    @pytest.mark.asyncio
    async def test_strategic_alerts(self, dashboard):
        await dashboard.generate_snapshot("weekly", {"churn_rate": 0.2, "conversion_rate": 0.005})
        alerts = await dashboard.strategic_alerts()
        assert isinstance(alerts, list)

    def test_summary(self, dashboard):
        assert isinstance(dashboard.summary(), dict)


# ══════════════════════════════════════════════════════════════════════════════
# 24. CASHFLOW ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class TestCashflowEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.business.finance.cashflow_engine.get_cache", return_value=_mock_cache()):
            from apps.business.finance.cashflow_engine import CashflowEngine
            return CashflowEngine()

    @pytest.mark.asyncio
    async def test_record_income(self, engine):
        entry = await engine.record("income", 2000.0, "shopify_sales", "Monthly revenue")
        assert entry.entry_id
        assert entry.type == "income"
        assert entry.amount_usd == 2000.0

    @pytest.mark.asyncio
    async def test_record_expense(self, engine):
        entry = await engine.record("expense", 500.0, "ads", "Facebook ads")
        assert entry.type == "expense"

    @pytest.mark.asyncio
    async def test_current_balance(self, engine):
        await engine.record("income", 3000.0, "sales")
        await engine.record("expense", 800.0, "marketing")
        balance = await engine.current_balance()
        assert abs(balance - 2200.0) < 0.01

    @pytest.mark.asyncio
    async def test_monthly_summary(self, engine):
        await engine.record("income", 1500.0, "shopify")
        summary = await engine.monthly_summary(months_back=3)
        assert isinstance(summary, list)

    @pytest.mark.asyncio
    async def test_forecast_cashflow(self, engine):
        await engine.record("income", 2000.0, "sales", recurring=True, frequency_days=30)
        await engine.record("expense", 400.0, "tools", recurring=True, frequency_days=30)
        forecast = await engine.forecast_cashflow(months_ahead=3)
        assert len(forecast) == 3
        assert all("projected_net" in f for f in forecast)

    @pytest.mark.asyncio
    async def test_runway_months(self, engine):
        await engine.record("income", 5000.0, "sales")
        runway = await engine.runway_months(monthly_burn_usd=1000.0)
        assert runway >= 0

    @pytest.mark.asyncio
    async def test_optimization_tips(self, engine):
        tips = await engine.optimization_tips()
        assert isinstance(tips, list)
        assert len(tips) >= 1

    def test_summary(self, engine):
        assert isinstance(engine.summary(), dict)


# ══════════════════════════════════════════════════════════════════════════════
# 25. BUSINESS ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

class TestBusinessAnalytics:
    @pytest.fixture
    def analytics(self):
        # yield (not return) so the mocked cache stays active for the whole test —
        # otherwise the real process-shared cache leaks events across tests and the
        # count-based assertions below become order-dependent / flaky.
        with patch("apps.business.analytics.business_analytics.get_cache", return_value=_mock_cache()):
            from apps.business.analytics.business_analytics import BusinessAnalytics
            yield BusinessAnalytics()

    @pytest.mark.asyncio
    async def test_track_event(self, analytics):
        event = await analytics.track("page_view", {"page": "/product"}, user_id="u1")
        assert event.event_id
        assert event.event_type == "page_view"

    @pytest.mark.asyncio
    async def test_funnel_analysis(self, analytics):
        for _ in range(100):
            await analytics.track("visit", {}, user_id="u1")
        for _ in range(40):
            await analytics.track("add_to_cart", {}, user_id="u1")
        for _ in range(10):
            await analytics.track("purchase", {"amount": 50.0}, user_id="u1")
        funnel = await analytics.funnel(["visit", "add_to_cart", "purchase"])
        assert len(funnel) == 3
        assert funnel[0]["count"] >= funnel[1]["count"]

    @pytest.mark.asyncio
    async def test_top_events(self, analytics):
        await analytics.track("click", {})
        await analytics.track("click", {})
        await analytics.track("purchase", {"amount": 99.0})
        top = await analytics.top_events(limit=5)
        assert isinstance(top, list)
        assert top[0]["count"] >= top[-1]["count"]

    @pytest.mark.asyncio
    async def test_diagnostics(self, analytics):
        await analytics.track("view", {})
        diag = await analytics.diagnostics()
        assert "total_events" in diag
        assert diag["data_health"] in ("good", "sparse", "empty")

    def test_summary(self, analytics):
        assert isinstance(analytics.summary(), dict)
