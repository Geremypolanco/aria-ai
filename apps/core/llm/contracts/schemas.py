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
from typing import Literal

from pydantic import BaseModel, Field

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
