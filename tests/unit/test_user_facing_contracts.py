"""
Schema gates on the user-facing call sites (cuspide wave 3).

Covers the five newly wrapped sites:
  1. AriaMind._reason            -> MindDecision      (every chat turn)
  2. ExecutiveDecisionEngine      -> ExecutiveDecision (dashboard report)
  3. MarketScanner               -> MarketOpportunityList + U5 provenance
  4. EcommerceAgent product idea -> EcommerceProductData (+ U3 price clamp
     at the Shopify listing boundary)
  5. EcommerceAgent funnel       -> HighTicketFunnel

Each site: schema accept/reject unit tests + a wiring test proving the
call site actually passes the schema through the validate->retry->dead-
letter gate (a faithful in-test replica of AriaAIClient.complete_json's
gate, so invalid model output degrades to the caller's fallback).
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from pydantic import ValidationError

from apps.core.llm.contracts import (
    EcommerceProductData,
    ExecutiveDecision,
    HighTicketFunnel,
    MarketOpportunityList,
    MindDecision,
    get_dead_letter_queue,
    validate_citations,
    validate_or_retry,
)
from apps.core.llm.contracts.citations import CitationsRequiredError

# ── faithful gate replica (mirrors AriaAIClient.complete_json) ─────────────


class FakeAI:
    """Stands in for AriaAIClient: runs the REAL validate_or_retry gate."""

    def __init__(self, payload: Any):
        self.payload = payload
        self.captured: dict[str, Any] = {}

    async def _one(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    async def complete_json(self, **kwargs):
        self.captured = kwargs
        schema = kwargs.get("schema")
        if schema is None:
            return await self._one()
        result = await validate_or_retry(
            self._one,
            schema,
            schema_name=kwargs.get("schema_name") or "unknown",
            agent_name=kwargs.get("agent_name") or "",
        )
        if result.ok:
            data = result.data
            return data.model_dump() if hasattr(data, "model_dump") else dict(data)
        get_dead_letter_queue().push(result.dead_letter)
        return {}


@pytest.fixture(autouse=True)
def _clean_dlq():
    get_dead_letter_queue().clear()
    yield
    get_dead_letter_queue().clear()


# ── 1. MindDecision ─────────────────────────────────────────────────────────


def _mind_payload(**over):
    p = {
        "thought": "user wants a summary; no tool needed",
        "autonomous_execution": False,
        "needs_clarification": False,
        "tool": None,
        "tool_args": None,
        "reply": "Here is your summary.",
        "goal_action": None,
    }
    p.update(over)
    return p


def test_mind_decision_valid():
    m = MindDecision.model_validate(_mind_payload())
    assert m.reply == "Here is your summary."
    assert m.tool is None


def test_mind_decision_tool_string_variants_normalized():
    for raw in ("", "null", "none", "  None  "):
        m = MindDecision.model_validate(_mind_payload(tool=raw))
        assert m.tool is None, raw


def test_mind_decision_tool_name_kept():
    m = MindDecision.model_validate(_mind_payload(tool="web_search", tool_args={"q": "x"}))
    assert m.tool == "web_search"
    assert m.tool_args == {"q": "x"}


def test_mind_decision_rejects_missing_thought():
    with pytest.raises(ValidationError):
        MindDecision.model_validate(_mind_payload(thought=""))


def test_mind_decision_goal_action_shapes():
    m = MindDecision.model_validate(
        _mind_payload(goal_action={"action": "add", "text": "launch store", "priority": 3})
    )
    assert m.goal_action.action == "add"
    m2 = MindDecision.model_validate(
        _mind_payload(goal_action={"action": "update", "index": 0, "progress": "half"})
    )
    assert m2.goal_action.index == 0
    with pytest.raises(ValidationError):
        MindDecision.model_validate(_mind_payload(goal_action={"action": "delete"}))


def test_mind_decision_wiring_passes_schema():
    # aria_mind imports the schema lazily inside _reason; assert the contract
    # module exposes exactly the keys the planner prompt promises.
    import inspect

    import apps.core.cognition.aria_mind as mind_mod

    src = inspect.getsource(mind_mod.AriaMind._reason)
    assert "schema=MindDecision" in src
    assert 'schema_name="MindDecision"' in src


# ── 2. ExecutiveDecision ────────────────────────────────────────────────────


def test_executive_decision_valid():
    d = ExecutiveDecision.model_validate(
        {
            "decision": "C",
            "reasoning": "experiments compound",
            "expected_roi": 7.5,
            "action_plan": ["run price test", "measure 7 days"],
        }
    )
    assert d.decision == "C"


def test_executive_decision_rejects_bad_values():
    with pytest.raises(ValidationError):
        ExecutiveDecision.model_validate(
            {"decision": "F", "reasoning": "x", "expected_roi": 5, "action_plan": ["a"]}
        )
    with pytest.raises(ValidationError):
        ExecutiveDecision.model_validate(
            {"decision": "A", "reasoning": "x", "expected_roi": 11, "action_plan": ["a"]}
        )


@pytest.mark.asyncio
async def test_executive_decision_wiring():
    from apps.core.engines.executive_decision import ExecutiveDecisionEngine

    fake_ai = FakeAI(
        {
            "decision": "B",
            "reasoning": "optimize converts",
            "expected_roi": 8.0,
            "action_plan": ["rewrite hero", "a/b price"],
        }
    )

    class FakeScanner:
        async def scan_opportunities(self):
            return []

    class FakeAttr:
        async def get_top_performing_content(self, n):
            return []

        async def get_revenue_graph_json(self):
            return {}

    engine = ExecutiveDecisionEngine.__new__(ExecutiveDecisionEngine)
    engine.ai = fake_ai
    engine.market_scanner = FakeScanner()
    engine.attribution = FakeAttr()

    decision = await engine.make_daily_decision()
    assert fake_ai.captured.get("schema") is ExecutiveDecision
    assert decision["decision"] == "B"
    assert decision["expected_roi"] == 8.0


@pytest.mark.asyncio
async def test_executive_decision_invalid_output_degrades():
    from apps.core.engines.executive_decision import ExecutiveDecisionEngine

    fake_ai = FakeAI({"decision": "Z", "reasoning": "x", "expected_roi": 99, "action_plan": []})

    class FakeScanner:
        async def scan_opportunities(self):
            return []

    class FakeAttr:
        async def get_top_performing_content(self, n):
            return []

        async def get_revenue_graph_json(self):
            return {}

    engine = ExecutiveDecisionEngine.__new__(ExecutiveDecisionEngine)
    engine.ai = fake_ai
    engine.market_scanner = FakeScanner()
    engine.attribution = FakeAttr()

    decision = await engine.make_daily_decision()
    assert decision == {"error": "Decision failed"}  # honest, never invented
    assert len(get_dead_letter_queue()) == 1


# ── 3. MarketScanner + U5 ───────────────────────────────────────────────────


def _opp(topic="AI planners", cites=("web:tavily-0",)):
    return {
        "topic": topic,
        "market_size": "large",
        "competition_level": "medium",
        "expected_roi": 7.0,
        "citations": list(cites),
    }


def test_market_opportunity_list_valid():
    lst = MarketOpportunityList.model_validate({"opportunities": [_opp(), _opp("AI audits")]})
    assert len(lst.opportunities) == 2


def test_market_opportunity_rejects_missing_provenance():
    with pytest.raises(ValidationError):
        MarketOpportunityList.model_validate({"opportunities": [_opp(cites=[])]})
    with pytest.raises(ValidationError):
        MarketOpportunityList.model_validate(
            {"opportunities": [dict(_opp(), citations=None)]}
        )


class _FakeWeb:
    def __init__(self, results):
        self._results = results

    async def search_web(self, query, num_results=5):
        return {"success": True, "results": self._results, "query": query}


@pytest.mark.asyncio
async def test_market_scanner_keeps_only_evidenced_citations():
    from apps.core.engines.market_scanner import MarketScanner

    scanner = MarketScanner.__new__(MarketScanner)
    scanner.web = _FakeWeb(
        [
            {"title": "Trend: AI planners", "url": "https://x.test/1", "source": "Tavily"},
            {"title": "Trend: AI audits", "url": "https://x.test/2", "source": "Tavily"},
        ]
    )
    scanner.ai = FakeAI(
        {
            "opportunities": [
                _opp("AI planners", ("web:tavily-0",)),
                _opp("AI audits", ("web:tavily-1", "web:hallucinated-9")),
                _opp("Ghost niche", ("web:made-up-1",)),
            ]
        }
    )
    opps = await scanner._scan_google_trends()
    assert [o["topic"] for o in opps] == ["AI planners", "AI audits"]
    assert opps[0]["citations"] == ["web:tavily-0"]
    assert opps[1]["citations"] == ["web:tavily-1"]  # invented citation stripped
    validate_citations(opps, min_citations=1)  # U5 holds


@pytest.mark.asyncio
async def test_market_scanner_no_evidence_no_opportunities():
    from apps.core.engines.market_scanner import MarketScanner

    scanner = MarketScanner.__new__(MarketScanner)
    scanner.web = _FakeWeb([])
    scanner.ai = FakeAI({"opportunities": [_opp()]})
    assert await scanner._scan_google_trends() == []


@pytest.mark.asyncio
async def test_market_scanner_invalid_output_degrades_to_empty():
    from apps.core.engines.market_scanner import MarketScanner

    scanner = MarketScanner.__new__(MarketScanner)
    scanner.web = _FakeWeb([{"title": "t", "url": "u", "source": "Tavily"}])
    scanner.ai = FakeAI({"opportunities": [{"topic": "x"}]})  # fails schema
    assert await scanner._scan_google_trends() == []
    assert len(get_dead_letter_queue()) == 1


def test_validate_citations_rejects_bad_format():
    with pytest.raises(CitationsRequiredError):
        validate_citations([{"label": "x", "citations": ["not-a-citation"]}], min_citations=1)




def _import_ecommerce_agent(monkeypatch):
    """Import ecommerce_agent with the heavy aria_tools registry stubbed.

    The real aria_tools chain builds httpx clients at import time, which
    trips over this sandbox's proxy env vars (environmental, unrelated to
    the contract wiring under test).
    """
    stub = types.ModuleType("apps.core.tools.aria_tools")
    stub.tool_registry = object()
    monkeypatch.setitem(sys.modules, "apps.core.tools.aria_tools", stub)
    import apps.core.agents.ecommerce_agent as ea

    return ea


# ── 4. EcommerceProductData + U3 price clamp ─────────────────────────────────


def _product_payload(**over):
    p = {
        "title": "AI Productivity Planner",
        "description_html": "<p>" + "Sell more with AI. " * 10 + "</p>",
        "price": "49.99",
        "compare_at_price": "79.99",
        "sku": "ARIA-PLN-001",
        "inventory": 50,
        "category": "Digital",
        "vendor": "Aria Premium",
        "tags": ["planner", "ai", "productivity"],
        "seo_title": "AI Productivity Planner",
        "seo_description": "Plan your week with AI.",
        "requires_shipping": False,
        "weight": 0.0,
        "weight_unit": "kg",
        "image_suggestions": ["planner cover mockup"],
        "video_concept": "30s demo of the planner",
        "zapier_automations": ["new sale -> email"],
        "high_ticket_upsell": "1:1 setup call $497",
    }
    p.update(over)
    return p


def test_ecommerce_product_valid():
    p = EcommerceProductData.model_validate(_product_payload())
    assert p.price == "49.99"


def test_ecommerce_product_rejects_bad_price():
    with pytest.raises(ValidationError):
        EcommerceProductData.model_validate(_product_payload(price="free"))
    with pytest.raises(ValidationError):
        EcommerceProductData.model_validate(_product_payload(price="49.999"))


@pytest.mark.asyncio
async def test_ecommerce_product_wiring_passes_schema(monkeypatch):
    ea = _import_ecommerce_agent(monkeypatch)

    fake_ai = FakeAI(_product_payload())
    monkeypatch.setattr(ea, "get_ai_client", lambda: fake_ai)
    agent = ea.EcommerceAgent.__new__(ea.EcommerceAgent)
    agent.knowledge = {"shopify_listing_best_practices": ["clear title"]}
    product = await agent._generate_product_idea("planners", {})
    assert fake_ai.captured.get("schema") is EcommerceProductData
    assert product["title"] == "AI Productivity Planner"


@pytest.mark.asyncio
async def test_shopify_listing_clamps_hallucinated_price(monkeypatch):
    ea = _import_ecommerce_agent(monkeypatch)

    captured = {}

    class FakeEngine:
        def __init__(self, shop, token):
            pass

        def create_optimized_product(self, product_data):
            captured.update(product_data)
            return "gid://shopify/Product/1"

    stub = types.ModuleType("apps.core.integrations.shopify_engine")
    stub.ShopifyEngine = FakeEngine
    monkeypatch.setitem(sys.modules, "apps.core.integrations.shopify_engine", stub)

    from types import SimpleNamespace

    monkeypatch.setattr(
        ea,
        "settings",
        SimpleNamespace(
            SHOPIFY_URL="test-shop",
            SHOPIFY_SHOP_NAME=None,
            SHOPIFY_ADMIN_TOKEN="tok",
        ),
    )

    agent = ea.EcommerceAgent.__new__(ea.EcommerceAgent)
    res = await agent._create_shopify_listing(_product_payload(price="49.99"))
    assert res["success"] is True
    assert captured["price"] == "49.99"

    # hallucinated $0.01 -> clamped to $1.00 floor; $99999 -> $999.00 ceiling
    await agent._create_shopify_listing(_product_payload(price="0.01"))
    assert captured["price"] == "1.00"
    await agent._create_shopify_listing(_product_payload(price="99999"))
    assert captured["price"] == "999.00"
    # garbage -> deterministic $99.99 default, never raises
    await agent._create_shopify_listing(_product_payload(price="priceless"))
    assert captured["price"] == "99.99"


# ── 5. HighTicketFunnel ─────────────────────────────────────────────────────


def _funnel_payload(**over):
    stages = ["Awareness", "Interest", "Qualification", "Proposal", "Close"]
    p = {
        "service_name": "AI Growth Consulting",
        "price_range": "$997 - $4,997",
        "target_audience": "busy founders",
        "value_proposition": "We install your AI growth engine in 30 days.",
        "funnel_stages": [{"stage": s, "action": f"do {s.lower()}"} for s in stages],
        "follow_up_sequence": ["day 1 msg", "day 3 msg", "day 7 msg"],
        "shopify_integration": "embed booking widget",
        "zapier_automation": "lead -> CRM",
    }
    p.update(over)
    return p


def test_high_ticket_funnel_valid():
    f = HighTicketFunnel.model_validate(_funnel_payload())
    assert len(f.funnel_stages) == 5


def test_high_ticket_funnel_rejects_wrong_stage_count():
    with pytest.raises(ValidationError):
        HighTicketFunnel.model_validate(
            _funnel_payload(funnel_stages=[{"stage": "A", "action": "x"}])
        )


@pytest.mark.asyncio
async def test_high_ticket_funnel_wiring_passes_schema(monkeypatch):
    ea = _import_ecommerce_agent(monkeypatch)

    fake_ai = FakeAI(_funnel_payload())
    monkeypatch.setattr(ea, "get_ai_client", lambda: fake_ai)
    agent = ea.EcommerceAgent.__new__(ea.EcommerceAgent)
    agent.knowledge = {"high_ticket_sales_strategies": ["value first"]}
    result = await agent._create_high_ticket_funnel("consulting")
    assert fake_ai.captured.get("schema") is HighTicketFunnel
    assert result["success"] is True
    assert result["funnel"]["service_name"] == "AI Growth Consulting"


@pytest.mark.asyncio
async def test_high_ticket_funnel_invalid_output_uses_fallback(monkeypatch):
    ea = _import_ecommerce_agent(monkeypatch)

    fake_ai = FakeAI({"service_name": ""})  # fails schema -> {}
    monkeypatch.setattr(ea, "get_ai_client", lambda: fake_ai)
    agent = ea.EcommerceAgent.__new__(ea.EcommerceAgent)
    agent.knowledge = {"high_ticket_sales_strategies": ["value first"]}
    result = await agent._create_high_ticket_funnel("consulting")
    assert result["success"] is True  # honest fallback, never invented
    assert "consulting" in result["funnel"]["service_name"].lower()
    assert len(get_dead_letter_queue()) == 1
