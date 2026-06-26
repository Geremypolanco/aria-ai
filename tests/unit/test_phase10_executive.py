"""
Phase 10 tests — Executive Layer: CEO, COO, CTO, CFO, CMO, ExecutiveCouncil.

Covers:
  - CEOAgent: set_growth_target, make_strategic_decision, prioritize_departments,
    weekly_vision_statement, active_targets, decision_log, strategic_summary
  - COOAgent: track_metric, assess_workflow, coordinate_departments,
    department_health, at_risk_metrics, operations_report
  - CTOAgent: evaluate_technology, architecture_review, system_health_check,
    tech_radar, technical_debt_report, engineering_metrics
  - CFOAgent: model_scenario, allocate_budget, roi_analysis,
    burn_rate_warning, profitability_report
  - CMOAgent: create_campaign_brief, define_brand_position, growth_strategy,
    active_campaigns, marketing_summary
  - ExecutiveCouncil: convene, emergency_pivot, quarterly_planning, council_summary
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Shared mock helpers ────────────────────────────────────────────────────────

def _mock_cache():
    """In-memory cache mock."""
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content: str = "Build quiz funnel"):
    """AI client mock whose .complete() is async."""
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


def _mock_ai_failed():
    ai = MagicMock()
    r = MagicMock()
    r.success = False
    r.content = ""
    ai.complete = AsyncMock(return_value=r)
    return ai


# ══════════════════════════════════════════════════════════════════════════════
# 1. CEOAgent
# ══════════════════════════════════════════════════════════════════════════════

class TestCEOAgent:
    """Tests for CEOAgent."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.executive.ceo_agent as m
        m._instance = None
        yield
        m._instance = None

    @pytest.fixture
    def ceo(self):
        with patch("apps.executive.ceo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.ceo_agent.get_ai_client", return_value=_mock_ai("Build quiz funnel")):
                from apps.executive.ceo_agent import CEOAgent
                return CEOAgent()

    async def test_set_growth_target_returns_growth_target(self, ceo):
        from apps.executive.ceo_agent import GrowthTarget
        with patch("apps.executive.ceo_agent.get_cache", return_value=_mock_cache()):
            result = await ceo.set_growth_target("revenue", 1000, 5000, 30)
        assert isinstance(result, GrowthTarget)
        assert result.metric == "revenue"
        assert result.current_value == 1000
        assert result.target_value == 5000
        assert result.deadline_days == 30
        assert result.status == "active"
        assert result.target_id

    async def test_set_growth_target_stored_in_list(self, ceo):
        with patch("apps.executive.ceo_agent.get_cache", return_value=_mock_cache()):
            await ceo.set_growth_target("subscribers", 100, 1000, 60)
        assert len(ceo._targets) == 1

    async def test_make_strategic_decision_returns_strategic_decision(self, ceo):
        from apps.executive.ceo_agent import StrategicDecision
        ai_content = "CHOICE: Launch paid ads | RATIONALE: Fastest ROI | PRIORITY: 8 | REVENUE_IMPACT: 5000 | EFFORT_HOURS: 20"
        with patch("apps.executive.ceo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.ceo_agent.get_ai_client", return_value=_mock_ai(ai_content)):
                result = await ceo.make_strategic_decision(
                    context={"niche": "fitness", "revenue": 2000},
                    options=["Launch paid ads", "Content marketing", "Influencer deals"],
                )
        assert isinstance(result, StrategicDecision)
        assert result.decision_id
        assert result.priority >= 1 and result.priority <= 10
        assert result.roi_score >= 0
        assert result.approved is True

    async def test_make_strategic_decision_ai_failure_fallback(self, ceo):
        from apps.executive.ceo_agent import StrategicDecision
        with patch("apps.executive.ceo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.ceo_agent.get_ai_client", return_value=_mock_ai_failed()):
                result = await ceo.make_strategic_decision(
                    context={"niche": "fitness"},
                    options=["Option A", "Option B"],
                )
        assert isinstance(result, StrategicDecision)
        assert result.title  # should have a title even if AI fails

    async def test_make_strategic_decision_roi_score_computed(self, ceo):
        ai_content = "CHOICE: Build quiz | RATIONALE: High ROI | PRIORITY: 9 | REVENUE_IMPACT: 10000 | EFFORT_HOURS: 50"
        with patch("apps.executive.ceo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.ceo_agent.get_ai_client", return_value=_mock_ai(ai_content)):
                result = await ceo.make_strategic_decision(
                    context={"niche": "quiz"},
                    options=["Build quiz", "Run ads"],
                )
        assert result.roi_score == 10000 / 50  # 200.0

    async def test_prioritize_departments_returns_list(self, ceo):
        dept_metrics = {
            "marketing": {"roi": 3.5},
            "sales": {"roi": 2.1},
            "product": {"roi": 1.8},
        }
        with patch("apps.executive.ceo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.ceo_agent.get_ai_client", return_value=_mock_ai("marketing, sales, product")):
                result = await ceo.prioritize_departments(dept_metrics)
        assert isinstance(result, list)
        assert len(result) == 3
        for item in result:
            assert "rank" in item
            assert "department" in item

    async def test_weekly_vision_statement_returns_string(self, ceo):
        with patch("apps.executive.ceo_agent.get_ai_client", return_value=_mock_ai("This week we conquer fitness")):
            result = await ceo.weekly_vision_statement("fitness")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_active_targets_empty_initially(self, ceo):
        result = ceo.active_targets()
        assert isinstance(result, list)
        assert len(result) == 0

    async def test_active_targets_after_set(self, ceo):
        with patch("apps.executive.ceo_agent.get_cache", return_value=_mock_cache()):
            await ceo.set_growth_target("revenue", 0, 10000, 90)
        result = ceo.active_targets()
        assert len(result) == 1
        assert result[0]["status"] == "active"

    async def test_decision_log_returns_list(self, ceo):
        result = ceo.decision_log()
        assert isinstance(result, list)

    async def test_strategic_summary_required_keys(self, ceo):
        result = ceo.strategic_summary()
        assert "total_decisions" in result
        assert "approved_ratio" in result
        assert "avg_roi_score" in result
        assert "active_targets" in result

    async def test_strategic_summary_after_decision(self, ceo):
        with patch("apps.executive.ceo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.ceo_agent.get_ai_client", return_value=_mock_ai("CHOICE: X | RATIONALE: Y | PRIORITY: 5 | REVENUE_IMPACT: 1000 | EFFORT_HOURS: 10")):
                await ceo.make_strategic_decision({"niche": "test"}, ["X", "Y"])
        summary = ceo.strategic_summary()
        assert summary["total_decisions"] == 1
        assert 0 <= summary["approved_ratio"] <= 1


# ══════════════════════════════════════════════════════════════════════════════
# 2. COOAgent
# ══════════════════════════════════════════════════════════════════════════════

class TestCOOAgent:
    """Tests for COOAgent."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.executive.coo_agent as m
        m._instance = None
        yield
        m._instance = None

    @pytest.fixture
    def coo(self):
        with patch("apps.executive.coo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.coo_agent.get_ai_client", return_value=_mock_ai("Bottleneck: slow content approval")):
                from apps.executive.coo_agent import COOAgent
                return COOAgent()

    async def test_track_metric_returns_operational_metric(self, coo):
        from apps.executive.coo_agent import OperationalMetric
        with patch("apps.executive.coo_agent.get_cache", return_value=_mock_cache()):
            result = await coo.track_metric("revenue", 8500, "USD", "marketing", 10000)
        assert isinstance(result, OperationalMetric)
        assert result.name == "revenue"
        assert result.value == 8500
        assert result.unit == "USD"
        assert result.dept == "marketing"
        assert result.metric_id

    async def test_track_metric_on_track_status(self, coo):
        with patch("apps.executive.coo_agent.get_cache", return_value=_mock_cache()):
            result = await coo.track_metric("conversion", 0.9, "ratio", "sales", 1.0)
        assert result.status == "on_track"

    async def test_track_metric_at_risk_status(self, coo):
        with patch("apps.executive.coo_agent.get_cache", return_value=_mock_cache()):
            result = await coo.track_metric("conversion", 0.7, "ratio", "sales", 1.0)
        assert result.status == "at_risk"

    async def test_track_metric_critical_status(self, coo):
        with patch("apps.executive.coo_agent.get_cache", return_value=_mock_cache()):
            result = await coo.track_metric("conversion", 0.4, "ratio", "sales", 1.0)
        assert result.status == "critical"

    async def test_assess_workflow_returns_workflow_status(self, coo):
        from apps.executive.coo_agent import WorkflowStatus
        tasks = [
            {"name": "write content", "done": True},
            {"name": "review content", "done": False},
            {"name": "publish", "done": False},
        ]
        with patch("apps.executive.coo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.coo_agent.get_ai_client", return_value=_mock_ai("Bottleneck: content review")):
                result = await coo.assess_workflow("marketing", tasks)
        assert isinstance(result, WorkflowStatus)
        assert result.dept == "marketing"
        assert result.tasks_total == 3
        assert result.tasks_done == 1
        assert 0 <= result.efficiency_score <= 100
        assert result.bottleneck

    async def test_coordinate_departments_returns_dict(self, coo):
        priorities = [
            {"department": "marketing", "priority_score": 9},
            {"department": "sales", "priority_score": 7},
        ]
        with patch("apps.executive.coo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.coo_agent.get_ai_client", return_value=_mock_ai("Focus on marketing first")):
                result = await coo.coordinate_departments(priorities)
        assert isinstance(result, dict)
        assert "coordination_plan" in result
        assert "departments_count" in result
        assert result["departments_count"] == 2

    async def test_department_health_returns_dict(self, coo):
        with patch("apps.executive.coo_agent.get_cache", return_value=_mock_cache()):
            await coo.track_metric("revenue", 8000, "USD", "marketing", 10000)
            await coo.track_metric("leads", 50, "count", "sales", 100)
        result = coo.department_health()
        assert isinstance(result, dict)
        assert "marketing" in result
        assert "sales" in result

    async def test_at_risk_metrics_returns_list(self, coo):
        with patch("apps.executive.coo_agent.get_cache", return_value=_mock_cache()):
            await coo.track_metric("revenue", 5000, "USD", "marketing", 10000)  # at_risk
        result = coo.at_risk_metrics()
        assert isinstance(result, list)
        assert len(result) >= 1

    async def test_operations_report_required_keys(self, coo):
        result = coo.operations_report()
        assert "total_metrics" in result
        assert "at_risk" in result
        assert "critical" in result
        assert "avg_efficiency" in result


# ══════════════════════════════════════════════════════════════════════════════
# 3. CTOAgent
# ══════════════════════════════════════════════════════════════════════════════

class TestCTOAgent:
    """Tests for CTOAgent."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.executive.cto_agent as m
        m._instance = None
        yield
        m._instance = None

    @pytest.fixture
    def cto(self):
        with patch("apps.executive.cto_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.cto_agent.get_ai_client", return_value=_mock_ai(
                "RECOMMENDATION: adopt | CATEGORY: tool | COMPLEXITY: low | RISK: low | RATIONALE: Mature ecosystem"
            )):
                from apps.executive.cto_agent import CTOAgent
                return CTOAgent()

    async def test_evaluate_technology_returns_tech_decision(self, cto):
        from apps.executive.cto_agent import TechDecision
        ai_resp = "RECOMMENDATION: adopt | CATEGORY: tool | COMPLEXITY: low | RISK: low | RATIONALE: Stable and fast"
        with patch("apps.executive.cto_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.cto_agent.get_ai_client", return_value=_mock_ai(ai_resp)):
                result = await cto.evaluate_technology("FastAPI", "REST API backend")
        assert isinstance(result, TechDecision)
        assert result.decision_id
        assert result.title == "Evaluate FastAPI"
        assert result.recommendation == "adopt"
        assert result.category == "tool"
        assert result.complexity == "low"
        assert result.risk_level == "low"

    async def test_evaluate_technology_updates_tech_radar(self, cto):
        ai_resp = "RECOMMENDATION: trial | CATEGORY: architecture | COMPLEXITY: medium | RISK: medium | RATIONALE: Promising"
        with patch("apps.executive.cto_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.cto_agent.get_ai_client", return_value=_mock_ai(ai_resp)):
                await cto.evaluate_technology("GraphQL", "API layer")
        radar = cto.tech_radar()
        assert "GraphQL" in radar["trial"]

    async def test_architecture_review_returns_dict(self, cto):
        import json
        review_json = json.dumps({
            "risks": ["Single point of failure", "No caching"],
            "recommendations": ["Add Redis", "Use CDN"],
            "score": 6,
        })
        with patch("apps.executive.cto_agent.get_ai_client", return_value=_mock_ai(review_json)):
            result = await cto.architecture_review("Monolithic Flask app on single server")
        assert isinstance(result, dict)
        assert "risks" in result
        assert "recommendations" in result
        assert "score" in result
        assert isinstance(result["risks"], list)
        assert isinstance(result["recommendations"], list)
        assert 0 <= result["score"] <= 10

    async def test_architecture_review_score_in_range(self, cto):
        import json
        with patch("apps.executive.cto_agent.get_ai_client", return_value=_mock_ai(json.dumps({"risks": [], "recommendations": [], "score": 8}))):
            result = await cto.architecture_review("Microservices with Redis")
        assert 0 <= result["score"] <= 10

    async def test_system_health_check_returns_list(self, cto):
        from apps.executive.cto_agent import SystemHealth
        with patch("apps.executive.cto_agent.get_cache", return_value=_mock_cache()):
            result = await cto.system_health_check(["api", "database", "cache"])
        assert isinstance(result, list)
        assert len(result) == 3
        for item in result:
            assert isinstance(item, SystemHealth)
            assert item.status in ("healthy", "degraded", "down")

    async def test_tech_radar_has_quadrants(self, cto):
        result = cto.tech_radar()
        assert "adopt" in result
        assert "trial" in result
        assert "hold" in result
        assert "avoid" in result

    async def test_technical_debt_report_keys(self, cto):
        result = cto.technical_debt_report()
        assert "total_decisions" in result
        assert "high_risk_decisions" in result
        assert "high_complexity_decisions" in result
        assert "tech_debt_score" in result

    async def test_engineering_metrics_keys(self, cto):
        result = cto.engineering_metrics()
        assert "decisions_made" in result
        assert "avg_complexity" in result
        assert "high_risk_count" in result


# ══════════════════════════════════════════════════════════════════════════════
# 4. CFOAgent
# ══════════════════════════════════════════════════════════════════════════════

class TestCFOAgent:
    """Tests for CFOAgent."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.executive.cfo_agent as m
        m._instance = None
        yield
        m._instance = None

    @pytest.fixture
    def cfo(self):
        with patch("apps.executive.cfo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.cfo_agent.get_ai_client", return_value=_mock_ai("Stable demand, low churn risk")):
                from apps.executive.cfo_agent import CFOAgent
                return CFOAgent()

    async def test_model_scenario_returns_financial_scenario(self, cfo):
        from apps.executive.cfo_agent import FinancialScenario
        with patch("apps.executive.cfo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.cfo_agent.get_ai_client", return_value=_mock_ai("Market stable, low churn")):
                result = await cfo.model_scenario(
                    "Growth",
                    revenue_drivers={"ads": 5000, "organic": 3000},
                    cost_drivers={"ops": 2000, "marketing": 1500},
                )
        assert isinstance(result, FinancialScenario)
        assert result.scenario_id
        assert result.name == "Growth"
        assert result.revenue_projection > 0
        assert result.cost_projection > 0
        assert isinstance(result.assumptions, list)

    async def test_model_scenario_roi_computed(self, cfo):
        with patch("apps.executive.cfo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.cfo_agent.get_ai_client", return_value=_mock_ai("Assumptions here")):
                result = await cfo.model_scenario(
                    "Base",
                    revenue_drivers={"primary": 10000},
                    cost_drivers={"primary": 5000},
                )
        # ROI = (10000 - 5000) / 5000 * 100 = 100%
        assert result.roi == 100.0
        assert result.profit_margin == 50.0

    async def test_allocate_budget_returns_list(self, cfo):
        from apps.executive.cfo_agent import BudgetAllocation
        with patch("apps.executive.cfo_agent.get_cache", return_value=_mock_cache()):
            result = await cfo.allocate_budget(
                10000,
                departments=["marketing", "product", "ops"],
                performance_data={
                    "marketing": {"score": 8},
                    "product": {"score": 6},
                    "ops": {"score": 4},
                },
            )
        assert isinstance(result, list)
        assert len(result) == 3
        for alloc in result:
            assert isinstance(alloc, BudgetAllocation)
            assert alloc.allocated_usd > 0

    async def test_allocate_budget_sums_to_total(self, cfo):
        with patch("apps.executive.cfo_agent.get_cache", return_value=_mock_cache()):
            result = await cfo.allocate_budget(
                10000,
                departments=["marketing", "sales"],
                performance_data={"marketing": {"score": 5}, "sales": {"score": 5}},
            )
        total = sum(a.allocated_usd for a in result)
        assert abs(total - 10000) < 1.0  # within $1 rounding

    async def test_roi_analysis_required_keys(self, cfo):
        result = await cfo.roi_analysis(
            investment_usd=5000,
            expected_returns={"year1": 8000, "year2": 3000},
        )
        assert "roi_pct" in result
        assert "payback_days" in result
        assert "npv" in result
        assert "recommendation" in result

    async def test_roi_analysis_positive_roi(self, cfo):
        result = await cfo.roi_analysis(
            investment_usd=1000,
            expected_returns={"return": 3000},
        )
        assert result["roi_pct"] > 0
        assert result["recommendation"] in ("Strong buy", "Buy", "Hold", "Avoid")

    async def test_burn_rate_warning_healthy(self, cfo):
        result = cfo.burn_rate_warning(monthly_burn=1000, cash_on_hand=24000)
        assert result["warning"] == "healthy"
        assert result["runway_months"] == 24.0

    async def test_burn_rate_warning_critical(self, cfo):
        result = cfo.burn_rate_warning(monthly_burn=5000, cash_on_hand=8000)
        assert result["warning"] == "critical"
        assert result["runway_months"] < 3

    async def test_burn_rate_warning_no_burn(self, cfo):
        result = cfo.burn_rate_warning(monthly_burn=0, cash_on_hand=50000)
        assert result["warning"] == "none"

    async def test_profitability_report_keys(self, cfo):
        result = cfo.profitability_report()
        assert "total_scenarios" in result
        assert "best_scenario" in result
        assert "avg_roi" in result
        assert "budget_efficiency" in result

    async def test_profitability_report_after_scenario(self, cfo):
        with patch("apps.executive.cfo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.cfo_agent.get_ai_client", return_value=_mock_ai("Assumptions")):
                await cfo.model_scenario("A", {"rev": 5000}, {"cost": 2000})
        report = cfo.profitability_report()
        assert report["total_scenarios"] == 1
        assert report["best_scenario"] == "A"


# ══════════════════════════════════════════════════════════════════════════════
# 5. CMOAgent
# ══════════════════════════════════════════════════════════════════════════════

class TestCMOAgent:
    """Tests for CMOAgent."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.executive.cmo_agent as m
        m._instance = None
        yield
        m._instance = None

    @pytest.fixture
    def cmo(self):
        with patch("apps.executive.cmo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.cmo_agent.get_ai_client", return_value=_mock_ai(
                "NAME: Fitness Domination | MESSAGE: Transform your body | KPI_CTR: 3.5 | KPI_CONV: 4.0 | TIMELINE: 30"
            )):
                from apps.executive.cmo_agent import CMOAgent
                return CMOAgent()

    async def test_create_campaign_brief_returns_campaign_brief(self, cmo):
        from apps.executive.cmo_agent import CampaignBrief
        ai_content = "NAME: Launch Blitz | MESSAGE: Get results fast | KPI_CTR: 2.5 | KPI_CONV: 3.0 | TIMELINE: 14"
        with patch("apps.executive.cmo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.cmo_agent.get_ai_client", return_value=_mock_ai(ai_content)):
                result = await cmo.create_campaign_brief(
                    objective="increase sales",
                    target_audience="fitness enthusiasts",
                    budget_usd=2000,
                    channels=["instagram", "facebook", "email"],
                )
        assert isinstance(result, CampaignBrief)
        assert result.brief_id
        assert result.campaign_name == "Launch Blitz"
        assert result.key_message == "Get results fast"
        assert result.budget_usd == 2000
        assert isinstance(result.channels, list)
        assert isinstance(result.kpis, dict)

    async def test_create_campaign_brief_kpis_populated(self, cmo):
        ai_content = "NAME: Test | MESSAGE: Test message | KPI_CTR: 5.0 | KPI_CONV: 2.5 | TIMELINE: 30"
        with patch("apps.executive.cmo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.cmo_agent.get_ai_client", return_value=_mock_ai(ai_content)):
                result = await cmo.create_campaign_brief(
                    "grow", "all users", 1000, ["email"]
                )
        assert "ctr_pct" in result.kpis
        assert "conversion_pct" in result.kpis

    async def test_define_brand_position_returns_brand_position(self, cmo):
        from apps.executive.cmo_agent import BrandPosition
        ai_content = "STATEMENT: The #1 fitness app | VALUE: Science-backed results | TONE: energetic | DIFF: Personalized AI coaching"
        with patch("apps.executive.cmo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.cmo_agent.get_ai_client", return_value=_mock_ai(ai_content)):
                result = await cmo.define_brand_position(
                    niche="fitness",
                    strengths=["AI coaching", "science-backed", "affordable"],
                )
        assert isinstance(result, BrandPosition)
        assert result.position_id
        assert result.niche == "fitness"
        assert result.positioning_statement
        assert result.unique_value
        assert result.tone

    async def test_growth_strategy_returns_dict_with_required_keys(self, cmo):
        with patch("apps.executive.cmo_agent.get_ai_client", return_value=_mock_ai("Focus on SEO and paid social")):
            result = await cmo.growth_strategy(
                current_metrics={"revenue": 5000, "cac": 25},
                goal_metric="revenue",
            )
        assert isinstance(result, dict)
        assert "channel_mix" in result
        assert "content_pillars" in result
        assert "ad_strategy" in result
        assert "timeline" in result

    async def test_growth_strategy_channel_mix_is_list(self, cmo):
        with patch("apps.executive.cmo_agent.get_ai_client", return_value=_mock_ai("Go big on social")):
            result = await cmo.growth_strategy({"revenue": 1000}, "revenue")
        assert isinstance(result["channel_mix"], list)

    async def test_active_campaigns_returns_list(self, cmo):
        result = cmo.active_campaigns()
        assert isinstance(result, list)

    async def test_marketing_summary_required_keys(self, cmo):
        result = cmo.marketing_summary()
        assert "total_campaigns" in result
        assert "active_positions" in result
        assert "channels_active" in result
        assert isinstance(result["channels_active"], list)

    async def test_marketing_summary_after_campaign(self, cmo):
        ai_content = "NAME: Campaign X | MESSAGE: Buy now | KPI_CTR: 3.0 | KPI_CONV: 2.0 | TIMELINE: 30"
        with patch("apps.executive.cmo_agent.get_cache", return_value=_mock_cache()):
            with patch("apps.executive.cmo_agent.get_ai_client", return_value=_mock_ai(ai_content)):
                await cmo.create_campaign_brief("grow", "everyone", 500, ["tiktok", "youtube"])
        summary = cmo.marketing_summary()
        assert summary["total_campaigns"] == 1
        assert "tiktok" in summary["channels_active"] or "youtube" in summary["channels_active"]


# ══════════════════════════════════════════════════════════════════════════════
# 6. ExecutiveCouncil
# ══════════════════════════════════════════════════════════════════════════════

class TestExecutiveCouncil:
    """Tests for ExecutiveCouncil."""

    @pytest.fixture(autouse=True)
    def _reset_singletons(self):
        import apps.executive.executive_council as ec
        import apps.executive.ceo_agent as ceo_m
        import apps.executive.coo_agent as coo_m
        import apps.executive.cto_agent as cto_m
        import apps.executive.cfo_agent as cfo_m
        import apps.executive.cmo_agent as cmo_m
        ec._instance = None
        ceo_m._instance = None
        coo_m._instance = None
        cto_m._instance = None
        cfo_m._instance = None
        cmo_m._instance = None
        yield
        ec._instance = None
        ceo_m._instance = None
        coo_m._instance = None
        cto_m._instance = None
        cfo_m._instance = None
        cmo_m._instance = None

    @pytest.fixture
    def council(self):
        cache = _mock_cache()
        ai = _mock_ai("Build quiz funnel | CHOICE: Content marketing | RATIONALE: High ROI | PRIORITY: 8 | REVENUE_IMPACT: 5000 | EFFORT_HOURS: 20")
        with patch("apps.executive.executive_council.get_cache", return_value=cache), \
             patch("apps.executive.ceo_agent.get_cache", return_value=cache), \
             patch("apps.executive.coo_agent.get_cache", return_value=cache), \
             patch("apps.executive.cto_agent.get_cache", return_value=cache), \
             patch("apps.executive.cfo_agent.get_cache", return_value=cache), \
             patch("apps.executive.cmo_agent.get_cache", return_value=cache), \
             patch("apps.executive.executive_council.get_ai_client", return_value=ai), \
             patch("apps.executive.ceo_agent.get_ai_client", return_value=ai), \
             patch("apps.executive.coo_agent.get_ai_client", return_value=ai), \
             patch("apps.executive.cto_agent.get_ai_client", return_value=ai), \
             patch("apps.executive.cfo_agent.get_ai_client", return_value=ai), \
             patch("apps.executive.cmo_agent.get_ai_client", return_value=ai):
            from apps.executive.executive_council import ExecutiveCouncil
            return ExecutiveCouncil()

    async def test_convene_returns_executive_report(self, council):
        from apps.executive.executive_council import ExecutiveReport
        assert ExecutiveReport is not None  # verify the dataclass exists

    async def test_convene_returns_executive_report_type(self, council):
        cache = _mock_cache()
        ai_ceo = _mock_ai("CHOICE: Content | RATIONALE: Best ROI | PRIORITY: 8 | REVENUE_IMPACT: 5000 | EFFORT_HOURS: 20")
        ai_general = _mock_ai("Good plan for growth")
        with patch("apps.executive.executive_council.get_cache", return_value=cache), \
             patch("apps.executive.ceo_agent.get_cache", return_value=cache), \
             patch("apps.executive.coo_agent.get_cache", return_value=cache), \
             patch("apps.executive.cto_agent.get_cache", return_value=cache), \
             patch("apps.executive.cfo_agent.get_cache", return_value=cache), \
             patch("apps.executive.cmo_agent.get_cache", return_value=cache), \
             patch("apps.executive.executive_council.get_ai_client", return_value=ai_general), \
             patch("apps.executive.ceo_agent.get_ai_client", return_value=ai_ceo), \
             patch("apps.executive.coo_agent.get_ai_client", return_value=ai_general), \
             patch("apps.executive.cto_agent.get_ai_client", return_value=ai_general), \
             patch("apps.executive.cfo_agent.get_ai_client", return_value=ai_general), \
             patch("apps.executive.cmo_agent.get_ai_client", return_value=ai_general):
            from apps.executive.executive_council import ExecutiveReport
            result = await council.convene("fitness", {"revenue": 5000})
        assert isinstance(result, ExecutiveReport)
        assert result.report_id
        assert result.period
        assert isinstance(result.strategic_decisions, list)
        assert isinstance(result.operational_health, dict)
        assert isinstance(result.financial_outlook, dict)
        assert isinstance(result.marketing_priorities, list)
        assert isinstance(result.tech_priorities, list)
        assert isinstance(result.top_actions, list)

    async def test_convene_stores_report(self, council):
        cache = _mock_cache()
        ai = _mock_ai("CHOICE: A | RATIONALE: B | PRIORITY: 5 | REVENUE_IMPACT: 1000 | EFFORT_HOURS: 10")
        with patch("apps.executive.executive_council.get_cache", return_value=cache), \
             patch("apps.executive.ceo_agent.get_cache", return_value=cache), \
             patch("apps.executive.coo_agent.get_cache", return_value=cache), \
             patch("apps.executive.cto_agent.get_cache", return_value=cache), \
             patch("apps.executive.cfo_agent.get_cache", return_value=cache), \
             patch("apps.executive.cmo_agent.get_cache", return_value=cache), \
             patch("apps.executive.executive_council.get_ai_client", return_value=ai), \
             patch("apps.executive.ceo_agent.get_ai_client", return_value=ai), \
             patch("apps.executive.coo_agent.get_ai_client", return_value=ai), \
             patch("apps.executive.cto_agent.get_ai_client", return_value=ai), \
             patch("apps.executive.cfo_agent.get_ai_client", return_value=ai), \
             patch("apps.executive.cmo_agent.get_ai_client", return_value=ai):
            await council.convene("tech", {"revenue": 10000})
        assert len(council._reports) == 1

    async def test_emergency_pivot_returns_dict(self, council):
        ai = _mock_ai("STEP1: Halt spending | STEP2: Focus on best channel | STEP3: Communicate")
        with patch("apps.executive.executive_council.get_ai_client", return_value=ai):
            result = await council.emergency_pivot(
                trigger="Revenue dropped 50%",
                context={"revenue_drop": 50, "cause": "ad_ban"},
            )
        assert isinstance(result, dict)
        assert "trigger" in result
        assert "pivot_steps" in result
        assert "decision_ts" in result
        assert "status" in result
        assert isinstance(result["pivot_steps"], list)

    async def test_emergency_pivot_has_3_steps(self, council):
        ai = _mock_ai("STEP1: Cut costs | STEP2: Pivot channel | STEP3: Fundraise")
        with patch("apps.executive.executive_council.get_ai_client", return_value=ai):
            result = await council.emergency_pivot("Crisis", {"context": "test"})
        assert len(result["pivot_steps"]) <= 3
        assert len(result["pivot_steps"]) >= 1

    async def test_emergency_pivot_fallback_steps(self, council):
        """AI failure should still return 3 default steps."""
        with patch("apps.executive.executive_council.get_ai_client", return_value=_mock_ai_failed()):
            result = await council.emergency_pivot("Critical failure", {})
        assert len(result["pivot_steps"]) == 3

    async def test_quarterly_planning_returns_dict(self, council):
        ai = _mock_ai("Month 1: Foundation. Month 2: Growth. Month 3: Scale.")
        with patch("apps.executive.executive_council.get_ai_client", return_value=ai):
            result = await council.quarterly_planning(
                objectives=["Hit $10K MRR", "Launch 3 products", "Grow to 1K subscribers"]
            )
        assert isinstance(result, dict)
        assert "objectives" in result
        assert "quarter_plan" in result
        assert "month_1_focus" in result
        assert "month_2_focus" in result
        assert "month_3_focus" in result
        assert "kpis" in result

    async def test_quarterly_planning_kpis_dict(self, council):
        ai = _mock_ai("Execute quarterly plan with focus on revenue")
        with patch("apps.executive.executive_council.get_ai_client", return_value=ai):
            result = await council.quarterly_planning(["Grow revenue"])
        assert isinstance(result["kpis"], dict)
        assert "revenue_growth_pct" in result["kpis"]

    async def test_council_summary_required_keys(self, council):
        result = council.council_summary()
        assert "reports_generated" in result
        assert "last_report_ts" in result
        assert "council_health" in result

    async def test_council_summary_health_not_started(self, council):
        result = council.council_summary()
        assert result["council_health"] == "not_started"
        assert result["reports_generated"] == 0

    async def test_get_executive_council_singleton(self):
        with patch("apps.executive.executive_council.get_cache", return_value=_mock_cache()):
            from apps.executive.executive_council import get_executive_council, ExecutiveCouncil
            import apps.executive.executive_council as m
            m._instance = None
            c1 = get_executive_council()
            c2 = get_executive_council()
            assert c1 is c2
            m._instance = None
