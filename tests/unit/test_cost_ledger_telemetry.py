"""Tests for CostLedger's telemetry additions (apps/core/ops/cost_ledger.py):
all_month_costs() and recent_samples() — the real (non-fabricated) data feed
for Mission Control's Financial/Resource telemetry module.
"""

from __future__ import annotations

from datetime import UTC, datetime

from apps.core.ops.cost_ledger import CostLedger

NOW = datetime(2026, 7, 25, tzinfo=UTC)


def test_all_month_costs_returns_only_current_month():
    led = CostLedger()
    led.record("a@example.com", "claude-sonnet-5", 1_000_000, 0, now=NOW)
    led.record("b@example.com", "claude-sonnet-5", 500_000, 0, now=NOW)
    # A different month must not leak into this month's view.
    other_month = datetime(2026, 6, 1, tzinfo=UTC)
    led.record("c@example.com", "claude-sonnet-5", 1_000_000, 0, now=other_month)

    costs = led.all_month_costs(now=NOW)

    assert set(costs.keys()) == {"a@example.com", "b@example.com"}
    assert costs["a@example.com"] == 3.0
    assert costs["b@example.com"] == 1.5


def test_all_month_costs_empty_when_nothing_recorded():
    led = CostLedger()
    assert led.all_month_costs(now=NOW) == {}


def test_recent_samples_reflects_real_recorded_charges():
    led = CostLedger()
    led.record("a@example.com", "claude-sonnet-5", 1_000_000, 0, now=NOW)
    led.record("b@example.com", "claude-haiku-4-5", 1_000_000, 0, now=NOW)

    samples = led.recent_samples()

    assert len(samples) == 2
    assert samples[0]["email"] == "a@example.com"
    assert samples[0]["cost_usd"] == 3.0
    assert samples[1]["email"] == "b@example.com"
    assert samples[1]["cost_usd"] == 1.0
    assert all("ts" in s for s in samples)


def test_recent_samples_respects_limit_and_ring_buffer_cap():
    led = CostLedger()
    for i in range(600):
        led.record(f"user{i}@example.com", "_free", 1, 1, now=NOW)

    # Ring buffer is capped at 500 regardless of how many were recorded.
    assert len(led.recent_samples(limit=1000)) == 500
    assert len(led.recent_samples(limit=5)) == 5


def test_record_without_email_does_not_create_a_sample():
    led = CostLedger()
    led.record("", "claude-sonnet-5", 1_000_000, 0, now=NOW)
    assert led.recent_samples() == []
    assert led.all_month_costs(now=NOW) == {}
