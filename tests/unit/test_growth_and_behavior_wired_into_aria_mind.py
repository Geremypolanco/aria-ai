"""Regression test: StrategicForecaster, LeverageAnalyzer (apps/strategy/),
BehaviorAnalyzer, and PersonaEngine (apps/psychology/) — four complete
implementations with their own singleton getters already in place — had zero
live callers, same pattern as RDWing/BrandEngine/PriorityEngine/
PersuasionEngine before them.

Wired into aria_mind.py's tool dispatcher as: forecast_revenue,
find_growth_bottleneck, growth_removal_plan, simulate_growth_lever,
analyze_user_behavior, predict_customer_churn, generate_audience_personas,
match_content_to_persona.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, not by calling the engines directly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.psychology.behavior.behavior_analyzer import BehaviorAnalyzer
from apps.psychology.personas.persona_engine import PersonaEngine
from apps.strategy.forecasting.strategic_forecaster import StrategicForecaster
from apps.strategy.leverage.leverage_analyzer import LeverageAnalyzer

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
def _patch_caches():
    fake_forecaster = _FakeCache()
    fake_behavior = _FakeCache()
    fake_persona = _FakeCache()
    with (
        patch(
            "apps.strategy.forecasting.strategic_forecaster.get_cache",
            return_value=fake_forecaster,
        ),
        patch("apps.psychology.behavior.behavior_analyzer.get_cache", return_value=fake_behavior),
        patch("apps.psychology.personas.persona_engine.get_cache", return_value=fake_persona),
    ):
        yield


async def test_forecast_revenue_reachable_from_tool_dispatch():
    forecaster = StrategicForecaster()
    with patch(
        "apps.strategy.forecasting.strategic_forecaster.get_strategic_forecaster",
        return_value=forecaster,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "forecast_revenue",
            {"initial_revenue": 1000, "growth_rate": 0.1, "months": 12, "model": "exponential"},
        )

    assert media == {}
    assert "Total projected revenue" in obs


async def test_forecast_revenue_requires_positive_initial_revenue():
    forecaster = StrategicForecaster()
    with patch(
        "apps.strategy.forecasting.strategic_forecaster.get_strategic_forecaster",
        return_value=forecaster,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("forecast_revenue", {"initial_revenue": 0})

    assert media == {}
    assert "$0" in obs


async def test_find_growth_bottleneck_reachable_from_tool_dispatch():
    analyzer = LeverageAnalyzer()
    with patch(
        "apps.strategy.leverage.leverage_analyzer.get_leverage_analyzer", return_value=analyzer
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "find_growth_bottleneck",
            {"metrics": {"conversion_rate": 0.01, "retention_rate": 0.3}},
        )

    assert media == {}
    assert "Primary bottleneck" in obs


async def test_growth_removal_plan_reachable_from_tool_dispatch():
    analyzer = LeverageAnalyzer()
    with patch(
        "apps.strategy.leverage.leverage_analyzer.get_leverage_analyzer", return_value=analyzer
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("growth_removal_plan", {"bottleneck": "conversion"})

    assert media == {}
    assert "Removal plan" in obs


async def test_simulate_growth_lever_shows_revenue_delta():
    analyzer = LeverageAnalyzer()
    with patch(
        "apps.strategy.leverage.leverage_analyzer.get_leverage_analyzer", return_value=analyzer
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "simulate_growth_lever",
            {"metrics": {"traffic": 1000, "conversion_rate": 0.02}, "lever": "conversion", "improvement_pct": 20},
        )

    assert media == {}
    assert "Annualized lift" in obs


async def test_analyze_user_behavior_reachable_from_tool_dispatch():
    analyzer = BehaviorAnalyzer()
    with patch(
        "apps.psychology.behavior.behavior_analyzer.get_behavior_analyzer", return_value=analyzer
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "analyze_user_behavior",
            {"user_id": "u1", "actions": [{"type": "add_to_cart"}, {"type": "purchase"}]},
        )

    assert media == {}
    assert "u1" in obs
    assert "Next best action" in obs


async def test_analyze_user_behavior_requires_actions():
    analyzer = BehaviorAnalyzer()
    with patch(
        "apps.psychology.behavior.behavior_analyzer.get_behavior_analyzer", return_value=analyzer
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("analyze_user_behavior", {"user_id": "u1"})

    assert media == {}
    assert "actions" in obs.lower()


async def test_predict_customer_churn_uses_prior_analysis():
    analyzer = BehaviorAnalyzer()
    with patch(
        "apps.psychology.behavior.behavior_analyzer.get_behavior_analyzer", return_value=analyzer
    ):
        mind = AriaMind()
        await mind._execute_tool(
            "analyze_user_behavior", {"user_id": "u2", "actions": [{"type": "cancel"}]}
        )
        obs, media = await mind._execute_tool("predict_customer_churn", {"user_id": "u2"})

    assert media == {}
    assert "u2" in obs
    assert "churn signals" in obs.lower()


async def test_generate_audience_personas_reachable_from_tool_dispatch():
    engine = PersonaEngine()
    with patch("apps.psychology.personas.persona_engine.get_persona_engine", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "generate_audience_personas", {"niche": "fitness", "count": 2}
        )

    assert media == {}
    assert "audience personas" in obs.lower()
    personas = await engine.list_personas()
    assert len(personas) == 2


async def test_match_content_to_persona_reachable_from_tool_dispatch():
    engine = PersonaEngine()
    with patch("apps.psychology.personas.persona_engine.get_persona_engine", return_value=engine):
        mind = AriaMind()
        created = await engine.generate_niche_personas("fitness", 1)
        obs, media = await mind._execute_tool(
            "match_content_to_persona",
            {"content": "Join now for exclusive access", "persona_id": created[0].persona_id},
        )

    assert media == {}
    assert "Persona match" in obs
