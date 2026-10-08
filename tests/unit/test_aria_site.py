"""
Tests for the ARIA_BASE_URL honest-degradation contract (cuspide wave 3).

- No default domain is ever invented: unconfigured -> "".
- Generated content never links to a dead domain.
- The income loop parks traffic-driving strategies while the site is
  unconfigured/unreachable, without touching the bandit's learned counts.
"""

from __future__ import annotations

import pytest

from apps.core.aria_site import (
    describe_site_status,
    get_aria_base_url,
    is_aria_site_live,
    reset_probe_cache,
    site_link,
)


@pytest.fixture(autouse=True)
def _clean_probe():
    reset_probe_cache()
    yield
    reset_probe_cache()


def _set_base(monkeypatch, value: str):
    monkeypatch.setattr("apps.core.aria_site.settings.ARIA_BASE_URL", value, raising=False)


# ── get_aria_base_url / site_link ──────────────────────────────────────────


def test_unconfigured_returns_empty_string(monkeypatch):
    _set_base(monkeypatch, "")
    assert get_aria_base_url() == ""
    assert site_link("/dashboard") == ""


def test_configured_url_is_normalized(monkeypatch):
    _set_base(monkeypatch, "https://aria.example.com/")
    assert get_aria_base_url() == "https://aria.example.com"
    assert site_link("/dashboard") == "https://aria.example.com/dashboard"
    assert site_link() == "https://aria.example.com"


def test_no_dead_domain_default():
    # The old hardcoded default must never come back in any form.

    assert "fly.dev" not in get_aria_base_url()
    assert "fly.dev" not in site_link("/dashboard")


# ── liveness probe ─────────────────────────────────────────────────────────


def test_probe_false_when_unconfigured(monkeypatch):
    _set_base(monkeypatch, "")
    called = []

    class FakeHttpx:
        @staticmethod
        def get(*a, **k):
            called.append(1)
            raise AssertionError("must not probe without a configured URL")

    monkeypatch.setitem(__import__("sys").modules, "httpx", FakeHttpx)
    assert is_aria_site_live() is False
    assert called == []


def _fake_httpx(monkeypatch, status=200, exc=None):
    calls = []

    class Resp:
        status_code = status

    class FakeHttpx:
        @staticmethod
        def get(*a, **k):
            calls.append(1)
            if exc:
                raise exc
            return Resp()

    monkeypatch.setitem(__import__("sys").modules, "httpx", FakeHttpx)
    return calls


def test_probe_true_on_2xx(monkeypatch):
    _set_base(monkeypatch, "https://aria.example.com")
    _fake_httpx(monkeypatch, status=200)
    assert is_aria_site_live() is True


def test_probe_false_on_4xx(monkeypatch):
    _set_base(monkeypatch, "https://aria.example.com")
    _fake_httpx(monkeypatch, status=404)
    assert is_aria_site_live() is False


def test_probe_false_on_network_error(monkeypatch):
    _set_base(monkeypatch, "https://aria.example.com")
    _fake_httpx(monkeypatch, exc=ConnectionError("down"))
    assert is_aria_site_live() is False


def test_probe_result_is_cached(monkeypatch):
    _set_base(monkeypatch, "https://aria.example.com")
    calls = _fake_httpx(monkeypatch, status=200)
    assert is_aria_site_live() is True
    assert is_aria_site_live() is True
    assert len(calls) == 1  # second call served from cache
    assert is_aria_site_live(force=True) is True
    assert len(calls) == 2


def test_describe_site_status_unconfigured(monkeypatch):
    _set_base(monkeypatch, "")
    assert "not configured" in describe_site_status()


# ── income-loop traffic gating ─────────────────────────────────────────────


def _make_bandit():
    from apps.core.tools.income_loop import STRATEGIES, ThompsonBandit

    names = [s[0] for s in STRATEGIES]
    return ThompsonBandit(names, {s[0]: float(s[1]) for s in STRATEGIES})


def test_traffic_set_matches_documented_roster():
    from apps.core.tools.income_loop import _TRAFFIC_STRATEGIES

    assert len(_TRAFFIC_STRATEGIES) == 23
    # every parked strategy must be a real strategy name
    names = {s[0] for s in __import__("apps.core.tools.income_loop", fromlist=["STRATEGIES"]).STRATEGIES}
    assert names >= _TRAFFIC_STRATEGIES


def test_bandit_exclude_never_draws_parked():
    from apps.core.tools.income_loop import _TRAFFIC_STRATEGIES

    bandit = _make_bandit()
    for _ in range(200):
        assert bandit.sample(exclude=_TRAFFIC_STRATEGIES) not in _TRAFFIC_STRATEGIES


def test_bandit_exclude_preserves_learned_counts():
    from apps.core.tools.income_loop import _TRAFFIC_STRATEGIES

    bandit = _make_bandit()
    before = dict(bandit._alpha)
    bandit.sample(exclude=_TRAFFIC_STRATEGIES)
    assert bandit._alpha == before  # exclusion never mutates learning state


def test_pick_strategy_parks_traffic_when_site_dead(monkeypatch):
    # _pick_strategy imports is_aria_site_live lazily from apps.core.aria_site
    import apps.core.aria_site as site_mod
    import apps.core.tools.income_loop as il

    monkeypatch.setattr(site_mod, "is_aria_site_live", lambda **k: False)
    loop = il.IncomeLoop()
    for _ in range(50):
        assert loop._pick_strategy() not in il._TRAFFIC_STRATEGIES


def test_pick_strategy_passes_exclude_through(monkeypatch):
    import apps.core.aria_site as site_mod
    import apps.core.tools.income_loop as il

    seen = {}

    orig_sample = il.ThompsonBandit.sample

    def spy(self, exclude=None):
        seen["exclude"] = exclude
        return orig_sample(self, exclude=exclude)

    monkeypatch.setattr(il.ThompsonBandit, "sample", spy)
    monkeypatch.setattr(site_mod, "is_aria_site_live", lambda **k: False)
    loop = il.IncomeLoop()
    loop._pick_strategy()
    assert seen["exclude"] == il._TRAFFIC_STRATEGIES

    monkeypatch.setattr(site_mod, "is_aria_site_live", lambda **k: True)
    loop2 = il.IncomeLoop()
    loop2._pick_strategy()
    assert seen["exclude"] is None


# ── generated-content helpers never emit dead links ────────────────────────


def test_content_helpers_unconfigured(monkeypatch):
    import apps.core.tools.income_loop as il

    _set_base(monkeypatch, "")
    assert il._dashboard_url() == ""
    assert il._site_cta_md() == ""
    assert il._published_by_md() == "*Published by ARIA AI*"
    assert il._dashboard_md_link() == "ARIA AI Dashboard"
    assert il._dash_suffix() == ""
    assert "fly.dev" not in il._tracking_link_format()
    assert "ARIA_BASE_URL" in il._tracking_link_format()  # honest placeholder


def test_content_helpers_configured(monkeypatch):
    import apps.core.tools.income_loop as il

    _set_base(monkeypatch, "https://aria.example.com")
    assert il._dashboard_url() == "https://aria.example.com/dashboard"
    assert "https://aria.example.com/dashboard" in il._site_cta_md()
    assert "https://aria.example.com/dashboard" in il._published_by_md()
    assert "fly.dev" not in il._site_cta_md()
    assert "fly.dev" not in il._tracking_link_format()
