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
    c.set_if_not_exists = AsyncMock(return_value=True)
    c.delete = AsyncMock(return_value=True)
    c.acquire_lock = AsyncMock(return_value=True)
    c.release_lock = AsyncMock(return_value=True)
    c.compare_and_delete = AsyncMock(return_value=True)
    return c


@pytest.fixture
def engine():
    with patch("apps.acquisition.delivery.delivery_engine.get_cache", return_value=_mock_cache()):
        from apps.acquisition.delivery.delivery_engine import DeliveryEngine

        # yield, not return: the patch must stay active for the whole test
        # body, since register_deliverable/deliver call get_cache() lazily
        # inside _load()/_save() — a `return` here would exit the `with`
        # block (and revert the patch) before the test ever awaits anything,
        # letting those calls reach the real redis client instead.
        yield DeliveryEngine()


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


async def test_deliver_refuses_concurrent_send_for_the_same_order_ref(engine):
    """A second call while the first is still holding the (sku, order_ref)
    lock must not send — the check-then-send sequence itself is protected,
    not just the after-the-fact dedup check."""
    await engine.register_deliverable(sku="x", name="X", content="https://example.com")
    locked_cache = _mock_cache()
    locked_cache.set_if_not_exists = AsyncMock(return_value=False)
    send = AsyncMock(return_value={"success": True, "provider": "resend"})
    with (
        patch("apps.acquisition.delivery.delivery_engine.get_cache", return_value=locked_cache),
        patch("apps.core.tools.publishing_tools.PublishingTools.send_newsletter", send),
    ):
        record = await engine.deliver("x", "buyer@example.com", order_ref="order-1")

    assert record.status == "in_progress"
    send.assert_not_awaited()


async def test_deliver_is_idempotent_for_the_same_order_ref(engine):
    """A repeat call for an order already confirmed sent (e.g. an automated
    retry after an ambiguous response) must return the stored result, never
    send a second real email for one purchase."""
    await engine.register_deliverable(sku="x", name="X", content="https://example.com")
    send = AsyncMock(return_value={"success": True, "provider": "resend"})
    with patch("apps.core.tools.publishing_tools.PublishingTools.send_newsletter", send):
        first = await engine.deliver("x", "buyer@example.com", order_ref="order-1")
        second = await engine.deliver("x", "buyer@example.com", order_ref="order-1")

    assert first.status == second.status == "sent"
    assert first.record_id == second.record_id
    send.assert_awaited_once()


async def test_deliver_retries_after_a_failed_attempt_for_the_same_order_ref(engine):
    """A prior failure never actually sent anything, so it must not block a
    fresh attempt for the same order_ref."""
    await engine.register_deliverable(sku="x", name="X", content="https://example.com")
    with patch(
        "apps.core.tools.publishing_tools.PublishingTools.send_newsletter",
        AsyncMock(return_value={"success": False, "error": "boom"}),
    ):
        first = await engine.deliver("x", "buyer@example.com", order_ref="order-1")
    with patch(
        "apps.core.tools.publishing_tools.PublishingTools.send_newsletter",
        AsyncMock(return_value={"success": True, "provider": "resend"}),
    ):
        second = await engine.deliver("x", "buyer@example.com", order_ref="order-1")

    assert first.status == "failed"
    assert second.status == "sent"
    assert first.record_id != second.record_id


async def test_deliver_records_ambiguous_outcome_on_provider_exception(engine):
    """An exception from send_newsletter means we genuinely don't know if
    the email went out — must be "ambiguous", never "failed" (which would
    tell both the dedup check and the caller's retry logic that nothing was
    sent and a retry is safe)."""
    await engine.register_deliverable(sku="x", name="X", content="https://example.com")
    with patch(
        "apps.core.tools.publishing_tools.PublishingTools.send_newsletter",
        AsyncMock(side_effect=TimeoutError("connection reset")),
    ):
        record = await engine.deliver("x", "buyer@example.com", order_ref="order-1")

    assert record.status == "ambiguous"
    assert "connection reset" in record.detail


async def test_deliver_does_not_retry_after_an_ambiguous_outcome(engine):
    """A second call for the same order after an ambiguous outcome must
    return the stored ambiguous record, not attempt to send again."""
    await engine.register_deliverable(sku="x", name="X", content="https://example.com")
    send = AsyncMock(side_effect=TimeoutError("connection reset"))
    with patch("apps.core.tools.publishing_tools.PublishingTools.send_newsletter", send):
        first = await engine.deliver("x", "buyer@example.com", order_ref="order-1")
        second = await engine.deliver("x", "buyer@example.com", order_ref="order-1")

    assert first.status == second.status == "ambiguous"
    assert first.record_id == second.record_id
    send.assert_awaited_once()


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
