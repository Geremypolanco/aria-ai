"""
U5 — mandatory provenance for facts shown to users.

Vendored from ``packages/roi-engine/src/citations.ts``
(``@polanco/roi-engine``): every finding shown to a user must carry
citations in ``fuente:id`` format (e.g. ``crm:lead-4821``). ``validate_citations``
runs BEFORE the fact is rendered and RAISES when a finding falls short —
a fact without provenance cannot be shown. This is the cheapest structural
mechanism against fabricated figures: citations are derived from each
figure's evidence provenance, so an unlabeled number can never earn one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

#: Machine citation format: ``fuente:id``
CITATION_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*:[A-Za-z0-9][A-Za-z0-9_.-]*$")


class CitationsRequiredError(ValueError):
    """Raised when a finding is rendered without enough valid citations."""


def source_to_citation(source: str) -> str:
    """Normalize an evidence source id to ``fuente:id`` citation form.

    The engine stores sources as ``intake.leadsPerMonth`` or already as
    ``std:loaded-rate-1.3`` — replace the first ``.`` with ``:`` only when
    the source does not already contain a ``:``.
    """
    if ":" in source:
        return source
    dot = source.find(".")
    if dot > 0:
        return f"{source[:dot]}:{source[dot + 1:]}"
    return source


def _evidence_source(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("source", ""))
    return str(getattr(item, "source", ""))


def finding_citations(evidence: Iterable[Any]) -> list[str]:
    """Derive a finding's citations from its figure's evidence provenance,
    deduplicated. Every citation comes from real evidence — never invented.
    """
    seen: set[str] = set()
    out: list[str] = []
    for item in evidence:
        citation = source_to_citation(_evidence_source(item))
        if citation and citation not in seen:
            seen.add(citation)
            out.append(citation)
    return out


def _finding_label(finding: Any) -> str:
    if isinstance(finding, dict):
        return str(finding.get("label", "?"))
    return str(getattr(finding, "label", "?"))


def _finding_citations_list(finding: Any) -> list[str]:
    if isinstance(finding, dict):
        raw = finding.get("citations", [])
    else:
        raw = getattr(finding, "citations", [])
    return [str(c) for c in (raw or [])]


def validate_citations(findings: Iterable[Any], min_citations: int = 3) -> None:
    """U5 enforcement: every finding must carry at least ``min_citations``
    citations, all in valid ``fuente:id`` format. Raises
    :class:`CitationsRequiredError` otherwise — the caller must refuse to
    render or persist the fact.
    """
    for finding in findings:
        label = _finding_label(finding)
        citations = _finding_citations_list(finding)
        invalid = [c for c in citations if not CITATION_RE.match(c)]
        if len(citations) < min_citations or invalid:
            raise CitationsRequiredError(
                f"[citations] CITATIONS_REQUIRED: {label!r} has {len(citations)} "
                f"citations (< {min_citations} or invalid format: "
                f"[{', '.join(invalid)}])"
            )
