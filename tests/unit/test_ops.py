"""Unit tests for the ARIA ops/autonomy modules (admin automation)."""

from __future__ import annotations

import pytest

from apps.core.ops import connector_health as ch
from apps.core.ops import self_healing as sh
from apps.core.ops.cost_ledger import CostLedger, estimate_cost


# ── cost_ledger (AI burn-rate cap) ────────────────────────────────
def test_estimate_cost_known_model():
    # opus 4.8: $5/1M in, $25/1M out
    cost = estimate_cost("claude-opus-4-8", 1_000_000, 1_000_000)
    assert cost == pytest.approx(30.0)


def test_estimate_cost_free_provider_is_zero():
    assert estimate_cost("some-hf-model", 5_000_000, 5_000_000) == 0.0
    assert estimate_cost(None, 1000, 1000) == 0.0


def test_ledger_accumulates_per_user_month():
    led = CostLedger()
    led.record("a@x.com", "claude-opus-4-8", 1_000_000, 0)  # $5
    led.record("a@x.com", "claude-opus-4-8", 1_000_000, 0)  # $5
    led.record("b@x.com", "claude-opus-4-8", 1_000_000, 0)  # $5
    assert led.month_cost("a@x.com") == pytest.approx(10.0)
    assert led.month_cost("b@x.com") == pytest.approx(5.0)
    assert led.month_cost("nobody@x.com") == 0.0


async def test_throttle_at_70_percent_for_paid():
    led = CostLedger()
    # Pro budget = $8 → 70% = $5.60. Burn $6 of opus output.
    led.record("pro@x.com", "claude-opus-4-8", 0, 240_000)  # 0.24M * $25 = $6.00
    assert led.month_cost("pro@x.com") == pytest.approx(6.0)
    assert led.over_threshold("pro@x.com", "pro") is True
    # evaluate() freezes a paid user over threshold
    assert await led.evaluate("pro@x.com", "pro") is True
    assert await led.is_frozen("pro@x.com") is True
    assert "pro@x.com" in led.frozen_users()


async def test_under_threshold_not_frozen():
    led = CostLedger()
    led.record("pro@x.com", "claude-opus-4-8", 0, 40_000)  # $1.00 of $8 budget
    assert led.over_threshold("pro@x.com", "pro") is False
    assert await led.evaluate("pro@x.com", "pro") is False
    assert await led.is_frozen("pro@x.com") is False


async def test_free_plan_not_frozen_by_burn_cap():
    led = CostLedger()
    led.record("free@x.com", "claude-opus-4-8", 0, 1_000_000)  # way over
    # evaluate only freezes pro/business
    assert await led.evaluate("free@x.com", "free") is False


async def test_frozen_state_survives_a_new_process_via_cache(monkeypatch):
    """The whole point of persisting the freeze flag: a fresh CostLedger
    (simulating a restart, or a different worker instance) must still see a
    user as frozen if the shared cache has the flag set."""
    store: dict[str, str] = {}

    class FakeCache:
        async def set(self, key, value, ttl_seconds=0):
            store[key] = value

        async def get(self, key):
            return store.get(key)

        async def delete(self, key):
            store.pop(key, None)

    monkeypatch.setattr(
        "apps.core.memory.redis_client.get_cache", lambda: FakeCache(), raising=False
    )

    led1 = CostLedger()
    await led1.freeze("pro@x.com")

    led2 = CostLedger()  # fresh instance — nothing in its local _frozen set
    assert await led2.is_frozen("pro@x.com") is True


# ── self_healing (auto-retry) ─────────────────────────────────────
def test_is_retryable_classification():
    assert sh.is_retryable(TimeoutError("timed out")) is True
    assert sh.is_retryable(Exception("Connection reset by peer")) is True
    assert sh.is_retryable(Exception("429 Too Many Requests")) is True
    assert sh.is_retryable(Exception("OAuth token expired")) is True
    assert sh.is_retryable(Exception("503 Service Unavailable")) is True
    # permanent
    assert sh.is_retryable(ValueError("invalid caption: field required")) is False
    assert sh.is_retryable(Exception("401 unauthorized: revoked")) is False


async def test_run_success_first_try():
    async def task():
        return "ok"

    out = await sh.run_with_self_healing(task, sleep=_no_sleep())
    assert out.ok is True
    assert out.attempts == 1
    assert out.result == "ok"
    assert out.delays_used == []


async def test_retries_transient_then_succeeds():
    calls = {"n": 0}
    slept: list[float] = []

    async def task():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("timed out")
        return "published"

    async def sleep(d):
        slept.append(d)

    out = await sh.run_with_self_healing(task, sleep=sleep)
    assert out.ok is True
    assert calls["n"] == 3
    assert slept == [300, 900]  # 5 min, 15 min before the 3rd (successful) try


async def test_exhausts_retries_and_alerts():
    alerts: list = []

    async def task():
        raise TimeoutError("still timing out")

    async def on_alert(outcome):
        alerts.append(outcome)

    slept: list[float] = []

    async def sleep(d):
        slept.append(d)

    out = await sh.run_with_self_healing(task, on_alert=on_alert, sleep=sleep)
    assert out.ok is False
    assert out.retryable is True
    assert slept == [300, 900, 1800]  # 5, 15, 30 min — 3 retries
    assert len(alerts) == 1
    assert alerts[0].ok is False


async def test_permanent_error_no_retry_but_alerts():
    slept: list[float] = []
    alerts: list = []

    async def task():
        raise ValueError("caption field required")

    out = await sh.run_with_self_healing(
        task, on_alert=lambda o: _record(alerts, o), sleep=lambda d: _append(slept, d)
    )
    assert out.ok is False
    assert out.retryable is False
    assert slept == []  # no backoff for permanent errors
    assert len(alerts) == 1


# ── connector_health (semaphore) ──────────────────────────────────
def test_classify_status():
    assert ch.classify(200, None) == "online"
    assert ch.classify(403, None) == "online"  # host up, just auth
    assert ch.classify(429, None) == "online"  # host up, rate-limited
    assert ch.classify(404, None) == "degraded"
    assert ch.classify(503, None) == "offline"
    assert ch.classify(None, "ConnectError: refused") == "offline"


async def test_check_all_updates_store_and_flags_offline():
    store = ch.HealthStore()

    async def fake_getter(url):
        if "instagram" in url:
            return None, "ConnectError: down"  # offline
        if "youtube" in url:
            return 503, None  # offline
        return 200, None  # online

    result = await ch.check_all(getter=fake_getter, store=store)
    assert result["instagram"]["status"] == "offline"
    assert result["youtube"]["status"] == "offline"
    assert result["linkedin"]["status"] == "online"
    assert store.any_offline() is True
    assert set(store.offline()) == {"instagram", "youtube"}


# ── helpers ───────────────────────────────────────────────────────
def _no_sleep():
    async def sleep(_d):
        return None

    return sleep


async def _record(store, item):
    store.append(item)


async def _append(store, item):
    store.append(item)
