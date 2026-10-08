"""
Tests for the anti-hallucination contracts (U2/U3/U5).

U2 — every structured LLM output is validated; failures retry with
     exponential backoff (max 3) and then land in the visible dead-letter
     queue. Invalid JSON → dead-letter (never invented/padded data).
U3 — LLM on the edges, deterministic math in the core: prices that reach
     money boundaries are computed by pure, total functions.
U5 — facts shown to users carry provenance; without it they are refused.

These tests never touch the network.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from apps.core.llm.contracts import (
    CITATION_RE,
    DigitalProductData,
    EbookMeta,
    ExecutiveSummary,
    FindingClassification,
    OfferData,
    RoadmapPhase,
    ValidateResult,
    finding_citations,
    get_dead_letter_queue,
    safe_price_cents,
    source_to_citation,
    usd_to_cents,
    validate_citations,
    validate_or_retry,
)
from apps.core.llm.contracts.citations import CitationsRequiredError
from apps.core.llm.contracts.dead_letter import DeadLetterEntry, DeadLetterQueue

# ── U2: schemas ────────────────────────────────────────────────────────────


def _valid_product() -> dict:
    return {
        "product_name": "The Complete AI Freelancer Toolkit",
        "tagline": "10 proven AI workflows that freelancers use to earn more",
        "description": "A comprehensive toolkit with 50+ prompt templates, "
        "workflow blueprints for writing, design, development, and consulting, "
        "plus a 30-day income ramp plan with real case studies.",
        "table_of_contents": ["Chapter 1: Foundations", "Chapter 2: Workflows"],
        "price_cents": 1997,
        "tags": ["ai", "freelance"],
    }


def test_digital_product_schema_accepts_valid_output():
    product = DigitalProductData.model_validate(_valid_product())
    assert product.price_cents == 1997


def test_digital_product_schema_rejects_hallucinated_price():
    bad = _valid_product() | {"price_cents": 5}  # $0.05 — absurd
    with pytest.raises(ValidationError):
        DigitalProductData.model_validate(bad)
    bad = _valid_product() | {"price_cents": 9999999}  # $99,999.99 — absurd
    with pytest.raises(ValidationError):
        DigitalProductData.model_validate(bad)


def test_digital_product_schema_rejects_missing_keys():
    with pytest.raises(ValidationError):
        DigitalProductData.model_validate({"product_name": "x"})


def test_ebook_meta_schema_enforces_price_band():
    meta = {
        "title": "T",
        "subtitle": "S",
        "description": "d" * 60,
        "price_usd": 9.99,
        "pages_estimate": 30,
        "chapter_titles": ["Chapter 1"],
        "target_audience": "freelancers",
        "unique_value_proposition": "practical",
        "keywords": ["ai"],
    }
    assert EbookMeta.model_validate(meta).price_usd == 9.99
    with pytest.raises(ValidationError):
        EbookMeta.model_validate(meta | {"price_usd": 999.0})


def test_offer_schema_enforces_premium_band():
    offer = {
        "offer_name": "Premium AI Automation Audit",
        "tagline": "Find the leaks",
        "description": "d" * 60,
        "what_included": ["Audit", "Roadmap"],
        "price_cents": 149700,
        "target_client": "B2B agencies",
        "tags": ["consulting"],
    }
    assert OfferData.model_validate(offer).price_cents == 149700
    with pytest.raises(ValidationError):
        OfferData.model_validate(offer | {"price_cents": 100})


def test_executive_summary_bullet_bounds():
    base = {"headline": "H", "caveats": []}
    with pytest.raises(ValidationError):
        ExecutiveSummary.model_validate(base | {"bullets": ["a", "b"]})  # < 3
    ok = ExecutiveSummary.model_validate(base | {"bullets": ["a", "b", "c"]})
    assert len(ok.bullets) == 3


def test_finding_classification_confidence_bounds():
    assert FindingClassification.model_validate(
        {"kind": "lead_leakage", "confidence": 0.8}
    ).confidence == 0.8
    with pytest.raises(ValidationError):
        FindingClassification.model_validate({"kind": "lead_leakage", "confidence": 1.5})
    with pytest.raises(ValidationError):
        FindingClassification.model_validate({"kind": "nope", "confidence": 0.5})


def test_roadmap_phase_bounds():
    with pytest.raises(ValidationError):
        RoadmapPhase.model_validate({"phase": 4, "title": "T", "actions": ["a"]})
    assert RoadmapPhase.model_validate(
        {"phase": 2, "title": "T", "actions": ["a"]}
    ).phase == 2


# ── U2: validate_or_retry ──────────────────────────────────────────────────


async def test_validate_or_retry_ok_first_attempt():
    result = await validate_or_retry(
        lambda: asyncio.sleep(0, result=_valid_product()),
        DigitalProductData,
        base_delay_s=0,
    )
    assert result.ok is True
    assert isinstance(result.data, DigitalProductData)
    assert result.dead_letter is None


async def test_validate_or_retry_succeeds_after_retry():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            return {"product_name": "x"}  # invalid
        return _valid_product()

    result = await validate_or_retry(flaky, DigitalProductData, base_delay_s=0)
    assert result.ok is True
    assert calls["n"] == 3


async def test_validate_or_retry_invalid_json_goes_to_dead_letter():
    """Per contract: invalid JSON → dead-letter after max attempts."""

    async def always_bad():
        return {"not": "the schema"}

    result: ValidateResult = await validate_or_retry(
        always_bad,
        DigitalProductData,
        max_attempts=3,
        base_delay_s=0,
        schema_name="DigitalProductData",
        agent_name="test",
    )
    assert result.ok is False
    assert result.data is None
    dl = result.dead_letter
    assert dl is not None
    assert dl.schema == "DigitalProductData"
    assert dl.attempts == 3
    assert dl.agent == "test"
    assert len(dl.errors) > 0  # validation messages, never invented data


async def test_validate_or_retry_fn_raising_goes_to_dead_letter():
    async def boom():
        raise RuntimeError("provider exploded")

    result = await validate_or_retry(boom, DigitalProductData, base_delay_s=0)
    assert result.ok is False
    assert result.dead_letter is not None
    assert result.dead_letter.attempts == 3
    assert any("provider exploded" in e for e in result.dead_letter.errors)


async def test_validate_or_retry_never_invents_data():
    """A failing output is quarantined — never padded to pass the schema."""
    seen: list[dict] = []

    async def bad():
        payload = {"product_name": "x"}
        seen.append(payload)
        return payload

    result = await validate_or_retry(bad, DigitalProductData, base_delay_s=0)
    assert result.ok is False
    # the only payloads ever produced are the raw invalid ones
    assert all(p == {"product_name": "x"} for p in seen)


# ── U2: dead-letter queue ──────────────────────────────────────────────────


def test_dead_letter_queue_push_list_clear():
    q = DeadLetterQueue()
    entry = DeadLetterEntry(schema="S", errors=["e1"], attempts=3, agent="a")
    q.push(entry)
    assert len(q) == 1
    assert q.list()[0].schema == "S"
    assert q.list()[0].id  # unique id assigned
    assert q.list()[0].at  # timestamp assigned
    q.clear()
    assert len(q) == 0


def test_dead_letter_queue_json_roundtrip():
    q = DeadLetterQueue()
    q.push(DeadLetterEntry(schema="S", errors=["bad price"], attempts=2))
    restored = DeadLetterQueue.from_json(q.to_json())
    assert len(restored) == 1
    assert restored.list()[0].errors == ["bad price"]
    # malformed snapshots degrade to an empty queue, never raise
    assert len(DeadLetterQueue.from_json("[]")) == 0


def test_dead_letter_singleton_is_shared():
    assert get_dead_letter_queue() is get_dead_letter_queue()


# ── U2: complete_json schema gate wiring ───────────────────────────────────


def _client_with_stubbed_complete(stub: AsyncMock):
    from apps.core.tools.ai_client import AriaAIClient

    client = AriaAIClient.__new__(AriaAIClient)
    client._complete_json_once = stub  # type: ignore[attr-defined]
    return client


async def test_complete_json_schema_gate_passes_valid_output():
    client = _client_with_stubbed_complete(AsyncMock(return_value=_valid_product()))
    out = await client.complete_json(
        system="s", user="u", schema=DigitalProductData, agent_name="test"
    )
    assert out["price_cents"] == 1997
    assert out["product_name"].startswith("The Complete")


async def test_complete_json_schema_gate_quarantines_invalid_output():
    """Invalid JSON through the client gate → {} + visible dead-letter."""
    q = get_dead_letter_queue()
    q.clear()
    client = _client_with_stubbed_complete(
        AsyncMock(return_value={"price_cents": 5})  # fails schema every attempt
    )
    out = await client.complete_json(
        system="s",
        user="u",
        schema=DigitalProductData,
        schema_name="DigitalProductData",
        agent_name="test",
    )
    assert out == {}  # legacy failure contract preserved
    assert len(q) == 1
    assert q.list()[-1].schema == "DigitalProductData"
    assert q.list()[-1].attempts == 3
    q.clear()


async def test_complete_json_without_schema_unchanged():
    client = _client_with_stubbed_complete(AsyncMock(return_value={"anything": "goes"}))
    out = await client.complete_json(system="s", user="u")
    assert out == {"anything": "goes"}


# ── U3: deterministic numeric core ─────────────────────────────────────────


def test_safe_price_cents_passes_through_sane_values():
    assert safe_price_cents(1997, default_cents=997, min_cents=100, max_cents=99900) == 1997
    assert safe_price_cents("2700", default_cents=997, min_cents=100, max_cents=99900) == 2700


def test_safe_price_cents_clamps_hallucinated_values():
    assert safe_price_cents(5, default_cents=997, min_cents=100, max_cents=99900) == 100
    assert safe_price_cents(9999999, default_cents=997, min_cents=100, max_cents=99900) == 99900


def test_safe_price_cents_never_raises_on_garbage():
    for garbage in (None, "free", "", float("nan"), True, object()):
        assert (
            safe_price_cents(garbage, default_cents=997, min_cents=100, max_cents=99900)
            == 997
        )


def test_usd_to_cents_rounds_half_up_and_clamps():
    assert usd_to_cents(9.99, default_cents=999, min_usd=7.0, max_usd=27.0) == 999
    assert usd_to_cents(9.995, default_cents=999, min_usd=7.0, max_usd=27.0) == 1000
    assert usd_to_cents(9999.0, default_cents=999, min_usd=7.0, max_usd=27.0) == 2700
    assert usd_to_cents(0.5, default_cents=999, min_usd=7.0, max_usd=27.0) == 700
    assert usd_to_cents(None, default_cents=999, min_usd=7.0, max_usd=27.0) == 999
    assert usd_to_cents("not-a-price", default_cents=999, min_usd=7.0, max_usd=27.0) == 999


# ── U5: citations ──────────────────────────────────────────────────────────


def test_citation_format():
    assert CITATION_RE.match("crm:lead-4821")
    assert CITATION_RE.match("intake:q7")
    assert not CITATION_RE.match("not a citation")
    assert not CITATION_RE.match(":missing-source")


def test_source_to_citation():
    assert source_to_citation("intake.leadsPerMonth") == "intake:leadsPerMonth"
    assert source_to_citation("std:loaded-rate-1.3") == "std:loaded-rate-1.3"


def test_finding_citations_dedupes():
    evidence = [{"source": "crm.a"}, {"source": "crm.a"}, {"source": "gmail:b"}]
    assert finding_citations(evidence) == ["crm:a", "gmail:b"]


def test_validate_citations_passes_with_three():
    findings = [
        {"label": "f1", "citations": ["crm:a", "gmail:b", "intake:c"]},
        {"label": "f2", "citations": ["crm:a", "gmail:b", "intake:c", "std:d"]},
    ]
    validate_citations(findings)  # must not raise


def test_validate_citations_throws_without_provenance():
    with pytest.raises(CitationsRequiredError):
        validate_citations([{"label": "made-up", "citations": ["crm:a"]}])
    with pytest.raises(CitationsRequiredError):
        validate_citations([{"label": "bad-format", "citations": ["a", "b", "c"]}])
