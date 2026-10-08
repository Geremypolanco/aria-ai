"""
Smoke test: the 3 money boundaries in sandbox mode (no real keys).

Runs without docker, without network, without credentials. It exercises
EXACTLY the guard calls the production boundaries use — same schemas,
same clamp parameters — against adversarial LLM outputs:

  1. income_loop product factory -> Gumroad
     schema=DigitalProductData + safe_price_cents(default=997, 100..99900)
  2. income_loop premium offer -> Gumroad
     schema=OfferData + safe_price_cents(default=149700, 50000..500000)
  3. cfo_agent -> Gumroad/Stripe
     usd_to_cents(default=999, 7.0..27.0 USD) [+ EbookMeta schema]

A hallucinated price must NEVER become a real charge: out-of-range values
are clamped, garbage falls back to the default, invalid JSON is
dead-lettered. Run inside docker with scripts/smoke_e2e_docker.sh.
"""

from __future__ import annotations

import pytest

from apps.core.llm.contracts import (
    DigitalProductData,
    EbookMeta,
    OfferData,
    get_dead_letter_queue,
    safe_price_cents,
    usd_to_cents,
    validate_or_retry,
)


@pytest.fixture(autouse=True)
def _clean_dlq():
    get_dead_letter_queue().clear()
    yield
    get_dead_letter_queue().clear()


async def _gate(payload, schema, name):
    async def _one():
        return payload

    result = await validate_or_retry(_one, schema, schema_name=name, agent_name="smoke")
    if result.ok:
        return result.data.model_dump()
    get_dead_letter_queue().push(result.dead_letter)
    return None


def _product(price_cents):
    return {
        "product_name": "Smoke Planner",
        "tagline": "plan anything",
        "description": "A smoke-test product. " * 10,
        "table_of_contents": ["intro", "plan"],
        "price_cents": price_cents,
        "tags": ["smoke"],
    }


def _offer(price_cents):
    return {
        "offer_name": "Smoke Offer",
        "tagline": "big value",
        "description": "A smoke-test offer. " * 10,
        "what_included": ["audit"],
        "price_cents": price_cents,
        "target_client": "founders",
        "tags": ["smoke"],
    }


def _ebook(price_usd):
    return {
        "title": "Smoke Ebook",
        "subtitle": "sub",
        "description": "A smoke-test ebook. " * 10,
        "price_usd": price_usd,
        "pages_estimate": 42,
        "chapter_titles": ["one"],
        "target_audience": "everyone",
        "unique_value_proposition": "smoke",
        "keywords": ["smoke"],
    }


# ── boundary 1: income_loop product factory -> Gumroad ─────────────────────


@pytest.mark.asyncio
async def test_boundary1_product_schema_and_clamp():
    # valid output passes the schema untouched
    data = await _gate(_product(1999), DigitalProductData, "DigitalProductData")
    assert data["price_cents"] == 1999
    # the boundary clamp: $19.99 stays $19.99
    assert safe_price_cents(data["price_cents"], default_cents=997, min_cents=100, max_cents=99900) == 1999


@pytest.mark.asyncio
async def test_boundary1_hallucinated_prices_never_charge():
    # $0.01 -> clamped to the $1.00 floor
    data = await _gate(_product(1), DigitalProductData, "DigitalProductData")
    assert data is None  # schema rejects: below the $1.00 floor
    assert len(get_dead_letter_queue()) == 1
    assert safe_price_cents(1, default_cents=997, min_cents=100, max_cents=99900) == 100

    # $99,999 -> clamped to the $999.00 ceiling
    assert safe_price_cents(9999900, default_cents=997, min_cents=100, max_cents=99900) == 99900

    # garbage -> deterministic $9.97 default, never raises
    assert safe_price_cents("priceless", default_cents=997, min_cents=100, max_cents=99900) == 997
    assert safe_price_cents(None, default_cents=997, min_cents=100, max_cents=99900) == 997


# ── boundary 2: income_loop premium offer -> Gumroad ────────────────────────


@pytest.mark.asyncio
async def test_boundary2_offer_schema_and_clamp():
    data = await _gate(_offer(149700), OfferData, "OfferData")
    assert data["price_cents"] == 149700
    assert safe_price_cents(149700, default_cents=149700, min_cents=50000, max_cents=500000) == 149700


@pytest.mark.asyncio
async def test_boundary2_hallucinated_offer_never_charges():
    # $5.00 on a $500-minimum offer -> schema rejects, clamp floors at $500
    data = await _gate(_offer(500), OfferData, "OfferData")
    assert data is None
    assert safe_price_cents(500, default_cents=149700, min_cents=50000, max_cents=500000) == 50000
    # $50,000 offer -> ceiling $5,000
    assert safe_price_cents(5000000, default_cents=149700, min_cents=50000, max_cents=500000) == 500000


# ── boundary 3: cfo_agent -> Gumroad/Stripe ─────────────────────────────────


@pytest.mark.asyncio
async def test_boundary3_cfo_schema_and_clamp():
    data = await _gate(_ebook(19.99), EbookMeta, "EbookMeta")
    assert data["price_usd"] == 19.99
    # the choke point: $19.99 -> 1999 cents, inside the $7-$27 band
    assert usd_to_cents(19.99, default_cents=999, min_usd=7.0, max_usd=27.0) == 1999


@pytest.mark.asyncio
async def test_boundary3_cfo_hallucinated_price_never_charges():
    # $0.50 ebook -> schema rejects (< $7); clamp floors at $7.00
    data = await _gate(_ebook(0.5), EbookMeta, "EbookMeta")
    assert data is None
    assert usd_to_cents(0.5, default_cents=999, min_usd=7.0, max_usd=27.0) == 700
    # $999 ebook -> ceiling $27.00
    assert usd_to_cents(999, default_cents=999, min_usd=7.0, max_usd=27.0) == 2700
    # garbage -> $9.99 default, never raises
    assert usd_to_cents("a lot", default_cents=999, min_usd=7.0, max_usd=27.0) == 999


# ── the boundaries are actually wired in the production code paths ─────────


def test_boundary_code_paths_reference_guards():
    # Source-level wiring check (importing the agent packages is not
    # possible in this sandbox: an unrelated module builds httpx clients
    # at import time and trips over the sandbox proxy env vars).
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    il_src = (root / "apps/core/tools/income_loop.py").read_text()
    cfo_src = (root / "apps/core/agents/cfo_agent.py").read_text()
    assert "schema=DigitalProductData" in il_src
    assert "schema=OfferData" in il_src
    assert il_src.count("safe_price_cents(") >= 2
    assert "usd_to_cents(" in cfo_src


def test_health_summary_reports_dead_letters():
    from apps.core.tools.ai_client import AIProvider, AriaAIClient

    client = AriaAIClient.__new__(AriaAIClient)

    class _H:
        class _S:
            value = "healthy"

        state = _S()
        success_rate = 100.0
        total_calls = 0
        consecutive_failures = 0

    client._health = {p: _H() for p in AIProvider}
    client._total_tokens = 0
    client._total_fallbacks = 0
    summary = client.get_health_summary()
    assert "dead_letters" in summary
    assert "dead_letters_persistent" in summary
    assert summary["dead_letters_persistent"]["available"] is False  # no creds in sandbox
    assert summary["dead_letters_persistent"]["count"] is None
