"""Aria Revenue Engine, Phase 1: DeliveryEngine
(apps/acquisition/delivery/delivery_engine.py) — closes the one real gap
found while surveying the existing acquisition/CRM/lead stack: every other
piece (LeadEngine, CRMEngine, LeadScraper, OutreachSequencer, LinkedIn
outreach) generates draft content or tracks pipeline state, but nothing
actually sends a paying customer what they bought once a sale closes.

register_deliverable() is the one point new content enters the system, and
runs the same Layer 3 content-safety firewall (guardrails.check_content_safety)
used by send_email/post_to_social — checked once, at registration, since
deliver() itself must be fully automatic (a real purchase can't wait on a
chat turn) and never generates or alters content of its own.

deliver() must refuse — not silently no-op, not invent a placeholder — when
a sku was never registered, since sending nothing is safer than sending
something a human never actually decided on.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


@pytest.fixture
def engine():
    with patch("apps.acquisition.delivery.delivery_engine.get_cache", return_value=_mock_cache()):
        from apps.acquisition.delivery.delivery_engine import DeliveryEngine

        return DeliveryEngine()


PHISHING_TEXT = "Please verify your account now, click here to continue or it will be suspended."


# ── register_deliverable ────────────────────────────────────────────────────


async def test_register_deliverable_success(engine):
    result = await engine.register_deliverable(
        sku="playbook-v1",
        name="The AI Agent Safety Playbook",
        content="https://example.com/playbook",
        delivery_type="link",
        price_usd=79.0,
    )
    assert result["success"] is True
    assert result["deliverable"]["sku"] == "playbook-v1"
    assert engine.get_deliverable("playbook-v1") is not None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sku": "", "name": "X", "content": "https://example.com"},
        {"sku": "x", "name": "", "content": "https://example.com"},
        {"sku": "x", "name": "X", "content": ""},
    ],
)
async def test_register_deliverable_requires_all_fields(engine, kwargs):
    result = await engine.register_deliverable(**kwargs)
    assert result["success"] is False
    assert engine.list_deliverables() == []


async def test_register_deliverable_rejects_invalid_delivery_type(engine):
    result = await engine.register_deliverable(
        sku="x", name="X", content="https://example.com", delivery_type="carrier_pigeon"
    )
    assert result["success"] is False
    assert "delivery_type" in result["error"]


async def test_register_deliverable_blocks_phishing_content():
    with patch("apps.acquisition.delivery.delivery_engine.get_cache", return_value=_mock_cache()):
        from apps.acquisition.delivery.delivery_engine import DeliveryEngine

        engine = DeliveryEngine()

    result = await engine.register_deliverable(sku="x", name="X", content=PHISHING_TEXT)
    assert result["success"] is False
    assert "blocked pattern" in result["error"].lower()
    assert engine.get_deliverable("x") is None


# ── deliver ──────────────────────────────────────────────────────────────────


async def test_deliver_sends_registered_deliverable(engine):
    await engine.register_deliverable(
        sku="playbook-v1", name="Playbook", content="https://example.com/playbook"
    )
    with patch(
        "apps.core.tools.publishing_tools.PublishingTools.send_newsletter",
        AsyncMock(return_value={"success": True, "provider": "resend"}),
    ):
        record = await engine.deliver("playbook-v1", "buyer@example.com", buyer_name="Alex")

    assert record.status == "sent"
    assert "resend" in record.detail
    assert engine.recent_deliveries()[0]["sku"] == "playbook-v1"


async def test_deliver_refuses_unregistered_sku(engine):
    record = await engine.deliver("never-registered", "buyer@example.com")

    assert record.status == "no_deliverable"
    assert "never-registered" in record.detail


async def test_deliver_requires_buyer_email(engine):
    await engine.register_deliverable(sku="x", name="X", content="https://example.com")
    record = await engine.deliver("x", "")

    assert record.status == "failed"


async def test_deliver_records_provider_failure(engine):
    await engine.register_deliverable(sku="x", name="X", content="https://example.com")
    with patch(
        "apps.core.tools.publishing_tools.PublishingTools.send_newsletter",
        AsyncMock(return_value={"success": False, "error": "All email providers failed"}),
    ):
        record = await engine.deliver("x", "buyer@example.com")

    assert record.status == "failed"
    assert "providers failed" in record.detail


async def test_delivery_stats_reflect_outcomes(engine):
    await engine.register_deliverable(sku="x", name="X", content="https://example.com")
    with patch(
        "apps.core.tools.publishing_tools.PublishingTools.send_newsletter",
        AsyncMock(return_value={"success": True, "provider": "resend"}),
    ):
        await engine.deliver("x", "buyer1@example.com")
    await engine.deliver("unregistered", "buyer2@example.com")

    stats = engine.delivery_stats()
    assert stats["total_deliverables_registered"] == 1
    assert stats["total_delivery_attempts"] == 2
    assert stats["sent"] == 1
    assert stats["no_deliverable"] == 1
