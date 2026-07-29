"""Regression test: register_deliverable / deliver_purchase are wired into
AriaMind._execute_tool's dispatcher (apps/core/cognition/aria_mind.py), the
same way every other acquisition tool (discover_leads, generate_sales_proposal)
is reachable from a live conversation, not just callable directly on
DeliveryEngine.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind

pytestmark = pytest.mark.asyncio


async def test_register_deliverable_requires_fields():
    mind = AriaMind()
    obs, media = await mind._execute_tool("register_deliverable", {"sku": "x"})

    assert media == {}
    assert "need" in obs.lower()


async def test_register_deliverable_reaches_delivery_engine():
    fake_engine = AsyncMock()
    fake_engine.register_deliverable = AsyncMock(
        return_value={"success": True, "deliverable": {"sku": "x", "name": "Guide"}}
    )
    with patch(
        "apps.acquisition.delivery.delivery_engine.get_delivery_engine",
        return_value=fake_engine,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "register_deliverable",
            {"sku": "x", "name": "Guide", "content": "https://example.com/guide"},
        )

    assert media == {}
    assert "registered" in obs.lower()
    fake_engine.register_deliverable.assert_awaited_once_with(
        "x", "Guide", "https://example.com/guide", "link", 0.0
    )


async def test_register_deliverable_surfaces_engine_error():
    fake_engine = AsyncMock()
    fake_engine.register_deliverable = AsyncMock(
        return_value={"success": False, "error": "Blocked pattern: phishing"}
    )
    with patch(
        "apps.acquisition.delivery.delivery_engine.get_delivery_engine",
        return_value=fake_engine,
    ):
        mind = AriaMind()
        obs, _ = await mind._execute_tool(
            "register_deliverable",
            {"sku": "x", "name": "Guide", "content": "phishing text"},
        )

    assert "blocked pattern" in obs.lower()


async def test_deliver_purchase_requires_fields():
    mind = AriaMind()
    obs, media = await mind._execute_tool("deliver_purchase", {"sku": "x"})

    assert media == {}
    assert "need" in obs.lower()


async def test_deliver_purchase_reaches_delivery_engine_and_reports_sent():
    from apps.acquisition.delivery.delivery_engine import DeliveryRecord

    fake_engine = AsyncMock()
    fake_engine.deliver = AsyncMock(
        return_value=DeliveryRecord(
            sku="x", buyer_email="buyer@example.com", status="sent", detail="via resend"
        )
    )
    with patch(
        "apps.acquisition.delivery.delivery_engine.get_delivery_engine",
        return_value=fake_engine,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "deliver_purchase", {"sku": "x", "buyer_email": "buyer@example.com"}
        )

    assert media == {}
    assert "delivered" in obs.lower()
    fake_engine.deliver.assert_awaited_once_with("x", "buyer@example.com", "", "")


async def test_deliver_purchase_reports_ambiguous_outcome_without_triggering_retry():
    from apps.acquisition.delivery.delivery_engine import DeliveryRecord

    fake_engine = AsyncMock()
    fake_engine.deliver = AsyncMock(
        return_value=DeliveryRecord(
            sku="x",
            buyer_email="buyer@example.com",
            status="ambiguous",
            detail="send_newsletter raised before confirming outcome: timeout",
        )
    )
    with patch(
        "apps.acquisition.delivery.delivery_engine.get_delivery_engine",
        return_value=fake_engine,
    ):
        mind = AriaMind()
        obs, _ = await mind._execute_tool(
            "deliver_purchase", {"sku": "x", "buyer_email": "buyer@example.com"}
        )

    assert "unconfirmed" in obs.lower()
    # Must not match AriaMind._FAILURE_SIGNALS, or the generic retry loop
    # would treat this genuinely-unknown outcome as safely retryable and
    # could send the product a second time.
    assert not AriaMind()._looks_like_failure(obs)


async def test_deliver_purchase_reports_in_progress_without_triggering_retry():
    from apps.acquisition.delivery.delivery_engine import DeliveryRecord

    fake_engine = AsyncMock()
    fake_engine.deliver = AsyncMock(
        return_value=DeliveryRecord(
            sku="x",
            buyer_email="buyer@example.com",
            status="in_progress",
            detail="Another delivery attempt for this order is already in progress",
        )
    )
    with patch(
        "apps.acquisition.delivery.delivery_engine.get_delivery_engine",
        return_value=fake_engine,
    ):
        mind = AriaMind()
        obs, _ = await mind._execute_tool(
            "deliver_purchase", {"sku": "x", "buyer_email": "buyer@example.com"}
        )

    assert "underway" in obs.lower()
    assert not AriaMind()._looks_like_failure(obs)


async def test_deliver_purchase_reports_no_deliverable_without_guessing():
    from apps.acquisition.delivery.delivery_engine import DeliveryRecord

    fake_engine = AsyncMock()
    fake_engine.deliver = AsyncMock(
        return_value=DeliveryRecord(
            sku="unregistered",
            buyer_email="buyer@example.com",
            status="no_deliverable",
            detail="No deliverable registered for sku 'unregistered'",
        )
    )
    with patch(
        "apps.acquisition.delivery.delivery_engine.get_delivery_engine",
        return_value=fake_engine,
    ):
        mind = AriaMind()
        obs, _ = await mind._execute_tool(
            "deliver_purchase", {"sku": "unregistered", "buyer_email": "buyer@example.com"}
        )

    assert "register_deliverable first" in obs
    assert "won't guess" in obs.lower()
