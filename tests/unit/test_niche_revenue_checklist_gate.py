"""Regression test: NicheRevenueEngine.launch_niche() gated publishing on
`not checklist.passed and checklist.score < 70` — but ChecklistResult.passed
is only True when ALL 14 gates pass (passed=len(failed) == 0). A listing
failing 1-4 gates (score 71-92, passed=False) satisfied `not checklist.passed`
but NOT `checklist.score < 70`, so the compound `and` was False and the
block was skipped entirely — the listing published despite failing the
"no exceptions, no shortcuts" 14-gate checklist that PrePublicationChecklist's
own docstring guarantees.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.tools.niche_revenue_engine import (
    NICHE_CATALOG,
    NicheRevenueEngine,
    ServiceListing,
)

pytestmark = pytest.mark.asyncio


def _incomplete_listing() -> ServiceListing:
    """A listing that fails exactly 2 gates (faq_present, portfolio_samples_present)
    out of 14 -> score = 12/14*100 = 85 (>= 70), passed = False."""
    niche_key = next(iter(NICHE_CATALOG))
    niche = NICHE_CATALOG[niche_key]
    return ServiceListing(
        niche_key=niche_key,
        title=f"Professional {niche['name']} {niche['keywords'][0]}",
        tagline="A tagline",
        description=(" ".join(["word"] * 250) + " order now"),
        deliverables=niche["deliverables"],
        pricing_tiers={
            "basic": {"price": niche["pricing_basic"], "description": "d"},
            "standard": {"price": niche["pricing_standard"], "description": "d"},
            "premium": {"price": niche["pricing_premium"], "description": "d"},
        },
        keywords=niche["keywords"],
        target_audience="Small business owners needing this service",
        portfolio_samples=[],  # fails gate 13
        faq=[],  # fails gate 7
        turnaround_days=niche["turnaround_days"],
        revision_policy="Up to 2 revisions included in all packages",
        platforms=niche["platforms"],
        category=niche["category"],
        tags=niche["keywords"][:5],
    )


async def test_launch_niche_blocks_publishing_when_any_gate_fails():
    engine = NicheRevenueEngine()
    listing = _incomplete_listing()
    checklist = engine._checklist.run(listing)
    assert checklist.passed is False
    assert checklist.score >= 70  # the exact condition that used to slip through

    with patch(
        "apps.core.tools.niche_revenue_engine.NicheTeam.research",
        AsyncMock(return_value={"opportunity_score": 50}),
    ), patch(
        "apps.core.tools.niche_revenue_engine.NicheTeam.create_listing",
        AsyncMock(return_value=listing),
    ), patch.object(
        NicheRevenueEngine, "_save_listing", AsyncMock()
    ), patch.object(
        engine._publisher, "publish_to_gumroad", AsyncMock()
    ) as mock_publish:
        result = await engine.launch_niche(listing.niche_key)

    assert result.success is False
    assert not result.published_urls
    mock_publish.assert_not_awaited()
