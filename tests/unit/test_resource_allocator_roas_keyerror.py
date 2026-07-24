"""Regression test: optimize_allocation() computed a fallback ROAS with
`c["revenue"] / c["spend"]` (direct indexing) while every other field in the
same dict used `.get(..., 0)` — a campaign with a "spend" but no "revenue"
key (and no explicit "roas") raised KeyError and crashed the whole
allocation, even though the surrounding code clearly intended to tolerate
missing fields."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.asyncio


async def test_optimize_allocation_tolerates_missing_revenue_key():
    from apps.orchestration.resource_allocator import ResourceAllocator

    allocator = ResourceAllocator()
    with patch.object(allocator, "_save", AsyncMock()):
        result = await allocator.optimize_allocation(
            [{"channel": "paid_ads", "spend": 300}]
        )

    assert result.total_budget_usd == 300
