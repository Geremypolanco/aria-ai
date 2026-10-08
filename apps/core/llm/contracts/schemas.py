"""
LLM output contracts — validated schemas for every structured output an LLM
is allowed to produce inside ARIA AI.

ATTRIBUTION: the pattern of validating LLM outputs against strict schemas
(fixed shapes, numeric ranges, bounded arrays) is vendored from
``@polanco/llm-contracts``
(``~/workspace/polanco-business-os/packages/llm-contracts``, itself a
clean-room reimplementation inspired by RaeburnAI's auditResultSchema,
Apache-2.0). This file is a from-scratch Python/pydantic v2 port for the
ARIA AI codebase. No code was copied.

ANTI-HALLUCINATION RULE: an LLM result that fails validation is retried
(see ``validate.py``) and, if it still fails, routed to the dead-letter
queue (see ``dead_letter.py``). We NEVER invent or pad data to make a
schema pass.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ── Mirrors of the @polanco/llm-contracts TypeScript schemas ────────────────

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

finding_kinds = (
    "lead_leakage",
    "abandoned_quotes",
    "manual_admin",
    "missed_calls",
    "ai_governance_gap",
    "other",
)


class ExtractedFact(BaseModel):
    """One extracted fact with its citation back to the source."""

    key: str = Field(min_length=1)
    value: str | float | int
    citation: str = Field(min_length=1)


class ExtractionResult(BaseModel):
    """Structured extraction of a document (contract, PDF, email thread)."""

    source_sha256: str = Field(pattern=_SHA256_HEX_RE.pattern)
    facts: list[ExtractedFact] = Field(default_factory=list)


class ExecutiveSummary(BaseModel):
    """Executive summary for a report: one headline, 3–6 bullets, caveats."""

    headline: str = Field(min_length=1, max_length=140)
    bullets: list[str] = Field(min_length=3, max_length=6)
    caveats: list[str] = Field(default_factory=list)


class FindingClassification(BaseModel):
    """Classification of a finding with a confidence score in [0, 1]."""

    kind: Literal["lead_leakage", "abandoned_quotes", "manual_admin", "missed_calls", "ai_governance_gap", "other"]
    confidence: float = Field(ge=0.0, le=1.0)


class RoadmapPhase(BaseModel):
    """One phase of a remediation roadmap (phases 1–3, 1–8 actions each)."""

    phase: int = Field(ge=1, le=3)
    title: str = Field(min_length=1)
    actions: list[str] = Field(min_length=1, max_length=8)


# ── ARIA AI output schemas (per output type produced by call sites) ─────────
#
# Bounds below mirror the ranges the prompts themselves demand, so a
# conforming model output validates unchanged; only hallucinations
# (absurd prices, empty payloads, wrong shapes) are rejected.


class DigitalProductData(BaseModel):
    """Structured output of the income-loop product factory.

    ``price_cents`` is the real price published on Gumroad — bounded so a
    hallucinated price can never become a real charge (U3).
    """

    product_name: str = Field(min_length=1, max_length=120)
    tagline: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=50)
    table_of_contents: list[str] = Field(min_length=1, max_length=12)
    price_cents: int = Field(ge=100, le=99900)  # $1.00 – $999.00
    tags: list[str] = Field(min_length=1, max_length=8)


class EbookMeta(BaseModel):
    """Structured output of the CFO agent's ebook metadata generator.

    The prompt constrains the price to $7–$27 USD; the schema enforces it.
    """

    title: str = Field(min_length=1, max_length=140)
    subtitle: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=50)
    price_usd: float = Field(ge=7.0, le=27.0)
    pages_estimate: int = Field(ge=5, le=500)
    chapter_titles: list[str] = Field(min_length=1, max_length=20)
    target_audience: str = Field(min_length=1)
    unique_value_proposition: str = Field(min_length=1)
    keywords: list[str] = Field(min_length=1, max_length=10)


class OfferData(BaseModel):
    """Structured output of the income-loop premium B2B offer generator.

    The prompt constrains the price to $500–$5,000; the schema enforces it.
    """

    offer_name: str = Field(min_length=1, max_length=140)
    tagline: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=50)
    what_included: list[str] = Field(min_length=1, max_length=8)
    price_cents: int = Field(ge=50000, le=500000)  # $500.00 – $5,000.00
    target_client: str = Field(min_length=1)
    tags: list[str] = Field(min_length=1, max_length=8)


class MissionStep(BaseModel):
    """One mission inside an orchestrator plan."""

    agent: str = Field(min_length=1)
    mission: str = Field(min_length=1)


class AgentPlan(BaseModel):
    """Structured output of the orchestrator's planning call."""

    focus: str = Field(min_length=1)
    missions: list[MissionStep] = Field(min_length=1, max_length=10)


# ── User-facing call-site schemas (cuspide wave 3) ──────────────────────────
#
# These wrap the highest-exposure LLM outputs that are rendered to users
# (chat replies, dashboard reports, store listings). Bounds mirror the
# ranges the prompts themselves demand; only hallucinations (wrong shapes,
# absurd prices, missing provenance) are rejected. Every field below is
# read by real downstream code — nothing here is decorative.


class GoalAction(BaseModel):
    """Goal mutation proposed by the chat planner (add/update a user goal)."""

    action: Literal["add", "update"]
    text: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    index: int | None = Field(default=None, ge=0)
    progress: str | None = None
    status: str | None = None


class MindDecision(BaseModel):
    """Structured output of AriaMind._reason — the single highest-exposure
    LLM call site: every chat turn's plan (tool dispatch + user reply).

    Mirrors the exact JSON contract in the planner prompt. On persistent
    validation failure the caller falls back to the FAST direct-reply path,
    so the user still gets an honest answer instead of a malformed plan.
    """

    thought: str = Field(min_length=1)
    autonomous_execution: bool = False
    needs_clarification: bool = False
    tool: str | None = None
    tool_args: dict[str, Any] | None = None
    reply: str = ""
    goal_action: GoalAction | None = None

    @field_validator("tool", mode="before")
    @classmethod
    def _normalize_tool(cls, v: Any) -> str | None:
        # Models sometimes emit "" / "null" / "none" instead of null —
        # normalize to None so downstream `bool(tool)` checks stay correct.
        if v is None:
            return None
        s = str(v).strip()
        if not s or s.lower() in ("null", "none"):
            return None
        return s


class ExecutiveDecision(BaseModel):
    """Structured output of the daily executive decision (dashboard report).

    The prompt constrains the decision to A–E and expected_roi to a 0–10
    scale; the schema enforces both. Rendered on the operator dashboard.
    """

    decision: Literal["A", "B", "C", "D", "E"]
    reasoning: str = Field(min_length=1)
    expected_roi: float = Field(ge=0.0, le=10.0)
    action_plan: list[str] = Field(min_length=1, max_length=8)


class MarketOpportunity(BaseModel):
    """One market opportunity from the trend scanner (dashboard + executive
    decision input). U5: every opportunity carries citations in ``fuente:id``
    format derived from the real web-search evidence — an opportunity
    without provenance is never shown."""

    topic: str = Field(min_length=1, max_length=140)
    market_size: str = Field(min_length=1, max_length=60)
    competition_level: str = Field(min_length=1, max_length=60)
    expected_roi: float = Field(ge=0.0, le=10.0)
    citations: list[str] = Field(min_length=1, max_length=10)


class MarketOpportunityList(BaseModel):
    """Envelope for the scanner's opportunity list."""

    opportunities: list[MarketOpportunity] = Field(min_length=1, max_length=20)


class EcommerceProductData(BaseModel):
    """Structured output of the ecommerce product-idea generator.

    The product (including ``price``) is published as a real Shopify
    listing visible to customers — the schema enforces the prompt's shape
    and a deterministic U3 price clamp is applied at the listing boundary.
    """

    title: str = Field(min_length=1, max_length=70)
    description_html: str = Field(min_length=50)
    price: str = Field(pattern=r"^\d+(\.\d{1,2})?$")  # USD string, e.g. "49.99"
    compare_at_price: str = Field(default="", pattern=r"^$|^\d+(\.\d{1,2})?$")
    sku: str = Field(min_length=1, max_length=40)
    inventory: int = Field(ge=0, le=100000)
    category: str = Field(min_length=1, max_length=60)
    vendor: str = Field(min_length=1, max_length=60)
    tags: list[str] = Field(min_length=1, max_length=8)
    seo_title: str = Field(min_length=1, max_length=70)
    seo_description: str = Field(min_length=1, max_length=160)
    requires_shipping: bool = False
    weight: float = Field(ge=0.0, le=10000.0)
    weight_unit: str = Field(default="kg", max_length=10)
    image_suggestions: list[str] = Field(min_length=1, max_length=5)
    video_concept: str = Field(min_length=1)
    zapier_automations: list[str] = Field(default_factory=list, max_length=5)
    high_ticket_upsell: str = Field(min_length=1)


class FunnelStage(BaseModel):
    """One stage of a high-ticket sales funnel."""

    stage: str = Field(min_length=1, max_length=40)
    action: str = Field(min_length=1)


class HighTicketFunnel(BaseModel):
    """Structured output of the high-ticket funnel generator (rendered to
    the operator as a service blueprint)."""

    service_name: str = Field(min_length=1, max_length=120)
    price_range: str = Field(min_length=1, max_length=60)
    target_audience: str = Field(min_length=1)
    value_proposition: str = Field(min_length=1)
    funnel_stages: list[FunnelStage] = Field(min_length=5, max_length=5)
    follow_up_sequence: list[str] = Field(min_length=3, max_length=3)
    shopify_integration: str = Field(min_length=1)
    zapier_automation: str = Field(min_length=1)
