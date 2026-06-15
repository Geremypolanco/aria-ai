"""
Phase 10 tests — Workforce Divisions: Marketing, Content, Operations, Analytics.

Covers all 4 divisions with 50+ tests:
  - MarketingDivision: seo_audit, media_buy_plan, social_media_calendar,
    growth_experiment, funnel_analysis, influencer_brief,
    marketing_stats, recent_campaigns, channel_strategy
  - ContentDivision: write_blog_post, write_ad_copy, write_video_script,
    write_email_sequence, translate_content, write_landing_page,
    content_stats, recent_content, content_strategy
  - OperationsDivision: create_project_plan, research_topic, draft_support_response,
    schedule_week, update_crm_notes, process_automation_spec,
    operations_stats, recent_tasks, pending_tasks
  - AnalyticsDivision: analyze_dataset, forecast_metric, funnel_analysis,
    attribution_analysis, build_kpi_dashboard, business_intelligence_report,
    analytics_stats, recent_reports, quick_insight
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Shared mock helpers ────────────────────────────────────────────────────────

def _mock_cache():
    """In-memory cache mock — get returns None, set returns True."""
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content: str = "AI analysis complete with detailed recommendations and insights."):
    """Sync AI client mock whose .complete() is async."""
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


def _mock_ai_failed():
    """AI client mock that always returns a failed response."""
    ai = MagicMock()
    r = MagicMock()
    r.success = False
    r.content = ""
    ai.complete = AsyncMock(return_value=r)
    return ai


# ══════════════════════════════════════════════════════════════════════════════
# 1. MarketingDivision — 14 tests
# ══════════════════════════════════════════════════════════════════════════════

class TestMarketingDivision:
    """Tests for MarketingDivision."""

    @pytest.fixture
    def division(self):
        with patch(
            "apps.workforce.marketing.marketing_division.get_cache",
            return_value=_mock_cache(),
        ):
            with patch(
                "apps.workforce.marketing.marketing_division.get_ai_client",
                return_value=_mock_ai("SEO audit: Add target keywords, fix meta tags, improve page speed, build backlinks."),
            ):
                from apps.workforce.marketing.marketing_division import MarketingDivision
                return MarketingDivision()

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.workforce.marketing.marketing_division as m
        m._instance = None
        yield
        m._instance = None

    async def test_seo_audit_returns_marketing_task(self, division):
        from apps.workforce.marketing.marketing_division import MarketingTask
        result = await division.seo_audit("example.com", competitors=["competitor.com"])
        assert isinstance(result, MarketingTask)

    async def test_seo_audit_has_non_empty_output(self, division):
        result = await division.seo_audit("my-blog.com")
        assert result.output
        assert len(result.output) > 10

    async def test_seo_audit_task_id_is_8_chars(self, division):
        result = await division.seo_audit("product.com")
        assert len(result.task_id) == 8

    async def test_seo_audit_quality_score_in_valid_range(self, division):
        result = await division.seo_audit("site.com")
        assert 0.0 <= result.quality_score <= 1.0

    async def test_seo_audit_correct_task_type(self, division):
        result = await division.seo_audit("site.com")
        assert result.task_type == "seo_audit"

    async def test_media_buy_plan_returns_marketing_task(self, division):
        from apps.workforce.marketing.marketing_division import MarketingTask
        result = await division.media_buy_plan(
            product="SaaS Tool",
            budget_usd=5000.0,
            target_audience="startup founders",
        )
        assert isinstance(result, MarketingTask)

    async def test_media_buy_plan_has_budget_in_metrics(self, division):
        result = await division.media_buy_plan("App", 3000.0, "developers", ["meta"])
        assert "total_budget_usd" in result.metrics
        assert result.metrics["total_budget_usd"] == 3000.0

    async def test_social_media_calendar_returns_marketing_task(self, division):
        from apps.workforce.marketing.marketing_division import MarketingTask
        result = await division.social_media_calendar("MyBrand", "fitness")
        assert isinstance(result, MarketingTask)

    async def test_social_media_calendar_metrics_have_post_count(self, division):
        result = await division.social_media_calendar("Brand", "tech", posts_per_week=7)
        assert result.metrics.get("total_posts") == 14  # 7 * 2 weeks

    async def test_growth_experiment_returns_marketing_task(self, division):
        from apps.workforce.marketing.marketing_division import MarketingTask
        result = await division.growth_experiment(
            hypothesis="Adding social proof increases CVR by 20%",
            channel="landing_page",
            budget_usd=1000.0,
        )
        assert isinstance(result, MarketingTask)

    async def test_funnel_analysis_returns_marketing_task(self, division):
        from apps.workforce.marketing.marketing_division import MarketingTask
        stages = {"visitors": 10000, "leads": 2000, "trials": 500, "customers": 100}
        result = await division.funnel_analysis(stages)
        assert isinstance(result, MarketingTask)

    async def test_funnel_analysis_overall_cvr_in_metrics(self, division):
        stages = {"visitors": 10000, "leads": 1000}
        result = await division.funnel_analysis(stages)
        assert "overall_cvr" in result.metrics
        assert result.metrics["overall_cvr"] == pytest.approx(0.1, rel=1e-3)

    async def test_influencer_brief_returns_marketing_task(self, division):
        from apps.workforce.marketing.marketing_division import MarketingTask
        result = await division.influencer_brief("SaaS Tool", "brand awareness", 5000.0)
        assert isinstance(result, MarketingTask)

    async def test_marketing_stats_has_required_keys(self, division):
        await division.seo_audit("site.com")
        stats = division.marketing_stats()
        assert "total_tasks" in stats
        assert "by_agent_type" in stats
        assert "avg_quality_score" in stats

    async def test_recent_campaigns_returns_list(self, division):
        await division.seo_audit("site.com")
        campaigns = division.recent_campaigns(limit=5)
        assert isinstance(campaigns, list)
        assert len(campaigns) <= 5

    async def test_channel_strategy_has_required_keys(self, division):
        result = await division.channel_strategy("fitness", 10000.0)
        assert "primary_channel" in result
        assert "channel_mix" in result
        assert "expected_roas" in result
        assert "90_day_plan" in result

    async def test_marketing_stats_empty_division(self, division):
        stats = division.marketing_stats()
        assert stats["total_tasks"] == 0
        assert stats["avg_quality_score"] == 0.0

    async def test_tasks_accumulate_across_calls(self, division):
        await division.seo_audit("site1.com")
        await division.seo_audit("site2.com")
        stats = division.marketing_stats()
        assert stats["total_tasks"] == 2

    async def test_seo_audit_status_is_done(self, division):
        result = await division.seo_audit("site.com")
        assert result.status == "done"

    async def test_get_marketing_division_singleton(self):
        with patch(
            "apps.workforce.marketing.marketing_division.get_cache",
            return_value=_mock_cache(),
        ):
            with patch(
                "apps.workforce.marketing.marketing_division.get_ai_client",
                return_value=_mock_ai(),
            ):
                from apps.workforce.marketing.marketing_division import get_marketing_division
                d1 = get_marketing_division()
                d2 = get_marketing_division()
                assert d1 is d2


# ══════════════════════════════════════════════════════════════════════════════
# 2. ContentDivision — 15 tests
# ══════════════════════════════════════════════════════════════════════════════

class TestContentDivision:
    """Tests for ContentDivision."""

    @pytest.fixture
    def division(self):
        with patch(
            "apps.workforce.content.content_division.get_cache",
            return_value=_mock_cache(),
        ):
            with patch(
                "apps.workforce.content.content_division.get_ai_client",
                return_value=_mock_ai(
                    "# How to Build a SaaS\n\n"
                    "Building a SaaS requires careful planning, technical expertise, and market validation. "
                    "In this post, we explore the key steps every founder needs to take. "
                    "Start with the problem, validate with customers, then build iteratively. "
                    "The journey requires persistence but the rewards are worth it."
                ),
            ):
                from apps.workforce.content.content_division import ContentDivision
                return ContentDivision()

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.workforce.content.content_division as m
        m._instance = None
        yield
        m._instance = None

    async def test_write_blog_post_returns_content_piece(self, division):
        from apps.workforce.content.content_division import ContentPiece
        result = await division.write_blog_post("How to build a SaaS", ["saas", "startup"])
        assert isinstance(result, ContentPiece)

    async def test_write_blog_post_has_non_empty_body(self, division):
        result = await division.write_blog_post("AI tools", ["ai", "productivity"])
        assert result.body
        assert len(result.body) > 10

    async def test_write_blog_post_piece_id_is_8_chars(self, division):
        result = await division.write_blog_post("topic", ["kw"])
        assert len(result.piece_id) == 8

    async def test_write_blog_post_correct_content_type(self, division):
        result = await division.write_blog_post("topic", ["kw"])
        assert result.content_type == "blog"

    async def test_write_blog_post_readability_score_in_range(self, division):
        result = await division.write_blog_post("topic", ["kw"])
        assert 0.0 <= result.readability_score <= 1.0

    async def test_write_blog_post_conversion_score_in_range(self, division):
        result = await division.write_blog_post("topic", ["kw"])
        assert 0.0 <= result.conversion_score <= 1.0

    async def test_write_blog_post_seo_keywords_stored(self, division):
        keywords = ["saas", "startup", "growth"]
        result = await division.write_blog_post("topic", keywords)
        assert result.seo_keywords == keywords

    async def test_write_ad_copy_returns_content_piece(self, division):
        from apps.workforce.content.content_division import ContentPiece
        result = await division.write_ad_copy("SaaS Tool", "startup founders", "meta")
        assert isinstance(result, ContentPiece)

    async def test_write_ad_copy_correct_type(self, division):
        result = await division.write_ad_copy("Product", "audience")
        assert result.content_type == "ad_copy"

    async def test_write_video_script_returns_content_piece(self, division):
        from apps.workforce.content.content_division import ContentPiece
        result = await division.write_video_script("How to grow on YouTube", 90, "youtube")
        assert isinstance(result, ContentPiece)

    async def test_write_video_script_correct_content_type(self, division):
        result = await division.write_video_script("topic", 60)
        assert result.content_type == "script"

    async def test_write_email_sequence_returns_list(self, division):
        results = await division.write_email_sequence("My Product", sequence_length=3)
        assert isinstance(results, list)
        assert len(results) == 3

    async def test_write_email_sequence_all_are_content_pieces(self, division):
        from apps.workforce.content.content_division import ContentPiece
        results = await division.write_email_sequence("SaaS", sequence_length=2)
        for piece in results:
            assert isinstance(piece, ContentPiece)

    async def test_write_email_sequence_all_have_non_empty_body(self, division):
        results = await division.write_email_sequence("Product", sequence_length=3)
        for piece in results:
            assert piece.body
            assert len(piece.body) > 5

    async def test_write_email_sequence_correct_content_type(self, division):
        results = await division.write_email_sequence("Product", sequence_length=2)
        for piece in results:
            assert piece.content_type == "email"

    async def test_translate_content_returns_content_piece(self, division):
        from apps.workforce.content.content_division import ContentPiece
        result = await division.translate_content("Hello world", "Spanish")
        assert isinstance(result, ContentPiece)

    async def test_translate_content_sets_language(self, division):
        result = await division.translate_content("Hello", "French")
        assert result.language == "French"

    async def test_translate_content_correct_type(self, division):
        result = await division.translate_content("Hello", "German")
        assert result.content_type == "translation"

    async def test_write_landing_page_returns_content_piece(self, division):
        from apps.workforce.content.content_division import ContentPiece
        result = await division.write_landing_page("SaaS Tool", "startup founders", "Save 10 hours/week")
        assert isinstance(result, ContentPiece)

    async def test_write_landing_page_correct_type(self, division):
        result = await division.write_landing_page("Product", "audience", "benefit")
        assert result.content_type == "landing_page"

    async def test_content_stats_has_required_keys(self, division):
        await division.write_blog_post("topic", ["kw"])
        stats = division.content_stats()
        assert "total_pieces" in stats
        assert "by_type" in stats
        assert "avg_word_count" in stats
        assert "avg_conversion_score" in stats

    async def test_content_stats_total_pieces_matches_calls(self, division):
        await division.write_blog_post("topic1", ["kw"])
        await division.write_ad_copy("product", "audience")
        stats = division.content_stats()
        assert stats["total_pieces"] == 2

    async def test_recent_content_returns_list(self, division):
        await division.write_blog_post("topic", ["kw"])
        pieces = division.recent_content(limit=5)
        assert isinstance(pieces, list)
        assert len(pieces) <= 5

    async def test_content_strategy_has_required_keys(self, division):
        result = await division.content_strategy("MyBrand", "tech", monthly_pieces=15)
        assert "brand" in result
        assert "niche" in result
        assert "monthly_pieces" in result
        assert "content_mix" in result

    async def test_email_sequence_single_item_list(self, division):
        results = await division.write_email_sequence("Product", sequence_length=1)
        assert len(results) == 1

    async def test_get_content_division_singleton(self):
        with patch(
            "apps.workforce.content.content_division.get_cache",
            return_value=_mock_cache(),
        ):
            with patch(
                "apps.workforce.content.content_division.get_ai_client",
                return_value=_mock_ai(),
            ):
                from apps.workforce.content.content_division import get_content_division
                d1 = get_content_division()
                d2 = get_content_division()
                assert d1 is d2


# ══════════════════════════════════════════════════════════════════════════════
# 3. OperationsDivision — 12 tests
# ══════════════════════════════════════════════════════════════════════════════

class TestOperationsDivision:
    """Tests for OperationsDivision."""

    @pytest.fixture
    def division(self):
        with patch(
            "apps.workforce.operations.operations_division.get_cache",
            return_value=_mock_cache(),
        ):
            with patch(
                "apps.workforce.operations.operations_division.get_ai_client",
                return_value=_mock_ai(
                    "Project Plan:\n- Phase 1: Setup (Week 1-2)\n- Phase 2: Build (Week 3-6)\n"
                    "- Phase 3: Test (Week 7-8)\nRisks: timeline slippage, resource constraints."
                ),
            ):
                from apps.workforce.operations.operations_division import OperationsDivision
                return OperationsDivision()

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.workforce.operations.operations_division as m
        m._instance = None
        yield
        m._instance = None

    async def test_create_project_plan_returns_operations_task(self, division):
        from apps.workforce.operations.operations_division import OperationsTask
        result = await division.create_project_plan(
            "Launch SaaS",
            objectives=["Build MVP", "Get 100 users"],
            deadline_days=90,
        )
        assert isinstance(result, OperationsTask)

    async def test_create_project_plan_has_non_empty_output(self, division):
        result = await division.create_project_plan("Project X", ["obj1"], 30)
        assert result.output
        assert len(result.output) > 10

    async def test_create_project_plan_task_id_is_8_chars(self, division):
        result = await division.create_project_plan("Proj", ["obj"], 30)
        assert len(result.task_id) == 8

    async def test_create_project_plan_correct_task_type(self, division):
        result = await division.create_project_plan("Proj", ["obj"], 30)
        assert result.task_type == "project_plan"

    async def test_create_project_plan_status_is_done(self, division):
        result = await division.create_project_plan("Proj", ["obj"], 30)
        assert result.status == "done"

    async def test_research_topic_returns_operations_task(self, division):
        from apps.workforce.operations.operations_division import OperationsTask
        result = await division.research_topic("AI trends 2026")
        assert isinstance(result, OperationsTask)

    async def test_research_topic_correct_task_type(self, division):
        result = await division.research_topic("blockchain")
        assert result.task_type == "research"

    async def test_draft_support_response_returns_operations_task(self, division):
        from apps.workforce.operations.operations_division import OperationsTask
        result = await division.draft_support_response("My order never arrived.")
        assert isinstance(result, OperationsTask)

    async def test_draft_support_response_correct_type(self, division):
        result = await division.draft_support_response("Login issue")
        assert result.task_type == "support_response"

    async def test_schedule_week_returns_operations_task(self, division):
        from apps.workforce.operations.operations_division import OperationsTask
        result = await division.schedule_week(["Write report", "Client calls", "Code review"])
        assert isinstance(result, OperationsTask)

    async def test_update_crm_notes_returns_operations_task(self, division):
        from apps.workforce.operations.operations_division import OperationsTask
        result = await division.update_crm_notes(
            "John Smith",
            "Had a great discovery call. Interested in enterprise plan.",
            ["Send proposal", "Follow up in 3 days"],
        )
        assert isinstance(result, OperationsTask)

    async def test_process_automation_spec_returns_operations_task(self, division):
        from apps.workforce.operations.operations_division import OperationsTask
        result = await division.process_automation_spec(
            "When a new lead fills the contact form, send welcome email and add to CRM"
        )
        assert isinstance(result, OperationsTask)

    async def test_operations_stats_has_required_keys(self, division):
        await division.create_project_plan("Proj", ["obj"], 30)
        stats = division.operations_stats()
        assert "total_tasks" in stats
        assert "by_agent_type" in stats
        assert "avg_priority_distribution" in stats

    async def test_operations_stats_empty_returns_zeros(self, division):
        stats = division.operations_stats()
        assert stats["total_tasks"] == 0

    async def test_recent_tasks_returns_list(self, division):
        await division.research_topic("topic")
        tasks = division.recent_tasks(limit=5)
        assert isinstance(tasks, list)
        assert len(tasks) <= 5

    async def test_pending_tasks_returns_empty_for_done_tasks(self, division):
        await division.research_topic("topic")
        pending = division.pending_tasks()
        assert isinstance(pending, list)
        # All tasks are status="done" by default
        assert len(pending) == 0

    async def test_tasks_accumulate_in_stats(self, division):
        await division.research_topic("topic1")
        await division.draft_support_response("issue1")
        stats = division.operations_stats()
        assert stats["total_tasks"] == 2

    async def test_get_operations_division_singleton(self):
        with patch(
            "apps.workforce.operations.operations_division.get_cache",
            return_value=_mock_cache(),
        ):
            with patch(
                "apps.workforce.operations.operations_division.get_ai_client",
                return_value=_mock_ai(),
            ):
                from apps.workforce.operations.operations_division import get_operations_division
                d1 = get_operations_division()
                d2 = get_operations_division()
                assert d1 is d2


# ══════════════════════════════════════════════════════════════════════════════
# 4. AnalyticsDivision — 14 tests
# ══════════════════════════════════════════════════════════════════════════════

class TestAnalyticsDivision:
    """Tests for AnalyticsDivision."""

    @pytest.fixture
    def division(self):
        with patch(
            "apps.workforce.analytics.analytics_division.get_cache",
            return_value=_mock_cache(),
        ):
            with patch(
                "apps.workforce.analytics.analytics_division.get_ai_client",
                return_value=_mock_ai(
                    "- Revenue is growing at 15% MoM\n"
                    "- Customer acquisition cost is within target range\n"
                    "- Churn rate needs immediate attention\n"
                    "- Top channel is organic search with 40% of traffic\n"
                    "- Recommend increasing budget in paid social"
                ),
            ):
                from apps.workforce.analytics.analytics_division import AnalyticsDivision
                return AnalyticsDivision()

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.workforce.analytics.analytics_division as m
        m._instance = None
        yield
        m._instance = None

    async def test_analyze_dataset_returns_analytics_report(self, division):
        from apps.workforce.analytics.analytics_division import AnalyticsReport
        result = await division.analyze_dataset(
            {"revenue": 50000, "users": 1200, "churn": 0.05},
            "What is driving revenue growth?",
        )
        assert isinstance(result, AnalyticsReport)

    async def test_analyze_dataset_report_id_is_8_chars(self, division):
        result = await division.analyze_dataset({"metric": 100}, "What is the trend?")
        assert len(result.report_id) == 8

    async def test_analyze_dataset_has_insights_list(self, division):
        result = await division.analyze_dataset({"metric": 100}, "How is performance?")
        assert isinstance(result.insights, list)
        assert len(result.insights) >= 1

    async def test_analyze_dataset_has_recommendations_list(self, division):
        result = await division.analyze_dataset({"metric": 100}, "question")
        assert isinstance(result.recommendations, list)

    async def test_analyze_dataset_correct_report_type(self, division):
        result = await division.analyze_dataset({"metric": 100}, "question")
        assert result.report_type == "dashboard"

    async def test_forecast_metric_returns_analytics_report(self, division):
        from apps.workforce.analytics.analytics_division import AnalyticsReport
        result = await division.forecast_metric(
            "MRR", [10000, 11000, 12500, 14000, 15800], periods_ahead=6
        )
        assert isinstance(result, AnalyticsReport)

    async def test_forecast_metric_projections_correct_length(self, division):
        result = await division.forecast_metric(
            "Signups", [100, 120, 140, 160], periods_ahead=12
        )
        # Projections are in charts_spec[0]
        projections = result.charts_spec[0].get("projections", [])
        assert len(projections) == 12

    async def test_forecast_metric_projections_list_not_empty(self, division):
        result = await division.forecast_metric("Revenue", [5000, 6000, 7000], periods_ahead=3)
        projections = result.charts_spec[0].get("projections", [])
        assert len(projections) == 3

    async def test_forecast_metric_upward_trend(self, division):
        result = await division.forecast_metric("MRR", [100, 110, 120, 130], periods_ahead=4)
        projections = result.charts_spec[0].get("projections", [])
        # With upward trend, last projection should be > first historical
        assert projections[-1] > 130

    async def test_forecast_metric_report_type_is_forecast(self, division):
        result = await division.forecast_metric("CAC", [200, 190, 180], periods_ahead=3)
        assert result.report_type == "forecast"

    async def test_funnel_analysis_returns_analytics_report(self, division):
        from apps.workforce.analytics.analytics_division import AnalyticsReport
        result = await division.funnel_analysis(
            {"awareness": 10000, "interest": 3000, "decision": 800, "purchase": 200}
        )
        assert isinstance(result, AnalyticsReport)

    async def test_funnel_analysis_has_insights(self, division):
        result = await division.funnel_analysis(
            {"top": 5000, "middle": 1000, "bottom": 100}
        )
        assert isinstance(result.insights, list)
        assert len(result.insights) >= 1

    async def test_funnel_analysis_correct_report_type(self, division):
        result = await division.funnel_analysis({"stage1": 1000, "stage2": 200})
        assert result.report_type == "funnel"

    async def test_funnel_analysis_overall_cvr_in_insights(self, division):
        result = await division.funnel_analysis({"visitors": 1000, "buyers": 100})
        # Overall CVR should appear in insights
        cvr_insight = any("10.00" in ins or "CVR" in ins for ins in result.insights)
        assert cvr_insight

    async def test_attribution_analysis_returns_analytics_report(self, division):
        from apps.workforce.analytics.analytics_division import AnalyticsReport
        result = await division.attribution_analysis(
            channels={"meta": 3000, "google": 2000, "email": 500},
            conversions=150,
            revenue=15000.0,
        )
        assert isinstance(result, AnalyticsReport)

    async def test_attribution_analysis_has_charts_spec(self, division):
        result = await division.attribution_analysis(
            {"meta": 1000, "google": 1000}, 50, 5000.0
        )
        assert isinstance(result.charts_spec, list)
        assert len(result.charts_spec) >= 1

    async def test_build_kpi_dashboard_returns_analytics_report(self, division):
        from apps.workforce.analytics.analytics_division import AnalyticsReport
        result = await division.build_kpi_dashboard(
            {"MRR": 50000, "churn_rate": 0.05, "NPS": 45, "CAC": 120}
        )
        assert isinstance(result, AnalyticsReport)

    async def test_build_kpi_dashboard_correct_report_type(self, division):
        result = await division.build_kpi_dashboard({"MRR": 50000})
        assert result.report_type == "kpi_monitor"

    async def test_business_intelligence_report_returns_analytics_report(self, division):
        from apps.workforce.analytics.analytics_division import AnalyticsReport
        result = await division.business_intelligence_report(
            {
                "revenue": 500000,
                "growth_rate": 0.25,
                "employees": 12,
                "markets": ["US", "EU"],
                "top_product": "SaaS Platform",
            }
        )
        assert isinstance(result, AnalyticsReport)

    async def test_business_intelligence_report_has_insights(self, division):
        result = await division.business_intelligence_report({"revenue": 100000})
        assert isinstance(result.insights, list)
        assert len(result.insights) >= 1

    async def test_analytics_stats_has_required_keys(self, division):
        await division.analyze_dataset({"m": 1}, "question")
        stats = division.analytics_stats()
        assert "total_reports" in stats
        assert "by_type" in stats
        assert "avg_confidence" in stats

    async def test_analytics_stats_empty_returns_zeros(self, division):
        stats = division.analytics_stats()
        assert stats["total_reports"] == 0
        assert stats["avg_confidence"] == 0.0

    async def test_recent_reports_returns_list(self, division):
        await division.analyze_dataset({"m": 1}, "q")
        reports = division.recent_reports(limit=5)
        assert isinstance(reports, list)
        assert len(reports) <= 5

    async def test_quick_insight_returns_string(self, division):
        result = await division.quick_insight("churn_rate", 0.08, "above target of 5%")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_reports_accumulate_in_stats(self, division):
        await division.analyze_dataset({"m": 1}, "q1")
        await division.forecast_metric("MRR", [100, 200, 300], 3)
        stats = division.analytics_stats()
        assert stats["total_reports"] == 2

    async def test_get_analytics_division_singleton(self):
        with patch(
            "apps.workforce.analytics.analytics_division.get_cache",
            return_value=_mock_cache(),
        ):
            with patch(
                "apps.workforce.analytics.analytics_division.get_ai_client",
                return_value=_mock_ai(),
            ):
                from apps.workforce.analytics.analytics_division import get_analytics_division
                d1 = get_analytics_division()
                d2 = get_analytics_division()
                assert d1 is d2


# ══════════════════════════════════════════════════════════════════════════════
# 5. Linear Forecast Helper — 4 tests
# ══════════════════════════════════════════════════════════════════════════════

class TestLinearForecast:
    """Tests for the _linear_forecast helper."""

    def test_forecast_correct_length(self):
        from apps.workforce.analytics.analytics_division import _linear_forecast
        result = _linear_forecast([100, 110, 120], 6)
        assert len(result) == 6

    def test_forecast_upward_trend(self):
        from apps.workforce.analytics.analytics_division import _linear_forecast
        result = _linear_forecast([100, 200, 300], 3)
        # Slope = 100, last = 300 → 400, 500, 600
        assert result[0] == pytest.approx(400.0, rel=1e-3)

    def test_forecast_single_value(self):
        from apps.workforce.analytics.analytics_division import _linear_forecast
        result = _linear_forecast([500.0], 4)
        assert len(result) == 4
        assert all(v == 500.0 for v in result)

    def test_forecast_empty_list(self):
        from apps.workforce.analytics.analytics_division import _linear_forecast
        result = _linear_forecast([], 3)
        assert len(result) == 3
        assert all(v == 0.0 for v in result)
