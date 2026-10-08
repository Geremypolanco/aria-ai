"""
LLM contracts — anti-hallucination enforcement for ARIA AI.

Vendored pattern from ``@polanco/llm-contracts``
(``~/workspace/polanco-business-os/packages/llm-contracts``), reimplemented
in Python/pydantic v2 for this codebase. No TypeScript was copied; the
enforcement semantics are identical:

  U2 — every LLM output is validated against a schema; on failure it is
       retried with exponential backoff (max 3 attempts) and then routed to
       a visible dead-letter queue. Data is NEVER invented or padded to
       make a schema pass.
  U3 — "LLM on the edges, math in the core": numbers and facts that reach
       money, reports, or users go through deterministic guards
       (see :mod:`deterministic`).
  U5 — facts shown to users carry provenance; without provenance they are
       not shown (see :mod:`citations`).

Usage::

    from apps.core.llm.contracts import (
        DigitalProductData,
        get_dead_letter_queue,
        validate_or_retry,
    )

    result = await validate_or_retry(
        lambda: ai.complete_json(system=..., user=...),
        DigitalProductData,
        schema_name="DigitalProductData",
    )
    if result.ok:
        product = result.data          # a validated DigitalProductData
    else:
        get_dead_letter_queue().push(result.dead_letter)  # visible, never silent
"""

from apps.core.llm.contracts.citations import (
    CITATION_RE,
    finding_citations,
    source_to_citation,
    validate_citations,
)
from apps.core.llm.contracts.dead_letter import (
    DeadLetterEntry,
    DeadLetterQueue,
    get_dead_letter_queue,
)
from apps.core.llm.contracts.deterministic import safe_price_cents, usd_to_cents
from apps.core.llm.contracts.schemas import (
    AgentPlan,
    DigitalProductData,
    EbookMeta,
    ExecutiveSummary,
    ExtractedFact,
    ExtractionResult,
    FindingClassification,
    MissionStep,
    OfferData,
    RoadmapPhase,
    finding_kinds,
)
from apps.core.llm.contracts.validate import ValidateResult, validate_or_retry

__all__ = [
    "CITATION_RE",
    "AgentPlan",
    "DeadLetterEntry",
    "DeadLetterQueue",
    "DigitalProductData",
    "EbookMeta",
    "ExecutiveSummary",
    "ExtractedFact",
    "ExtractionResult",
    "FindingClassification",
    "MissionStep",
    "OfferData",
    "RoadmapPhase",
    "ValidateResult",
    "finding_citations",
    "finding_kinds",
    "get_dead_letter_queue",
    "safe_price_cents",
    "source_to_citation",
    "usd_to_cents",
    "validate_citations",
    "validate_or_retry",
]
