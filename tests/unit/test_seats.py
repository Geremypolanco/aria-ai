"""Team-seat logic: invite, seat limit, membership, removal."""

import asyncio

import pytest

from apps.core import seats


class _FakeCache:
    def __init__(self):
        self.d = {}

    async def get(self, k):
        return self.d.get(k)

    async def set(self, k, v, ttl_seconds=None):
        self.d[k] = v


@pytest.fixture(autouse=True)
def fake_cache(monkeypatch):
    cache = _FakeCache()

    async def _get_cache():
        return cache

    monkeypatch.setattr(seats, "_cache", _get_cache)
    return cache


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_add_member_and_list():
    ok, _ = run(seats.add_member("owner@x.com", "a@y.com", seats_limit := 5))
    assert ok
    assert run(seats.list_members("owner@x.com")) == ["a@y.com"]
    assert run(seats.owner_of("a@y.com")) == "owner@x.com"


def test_seat_limit_enforced():
    # seats=2 means owner + 1 member max
    ok1, _ = run(seats.add_member("o@x.com", "a@y.com", 2))
    ok2, msg2 = run(seats.add_member("o@x.com", "b@y.com", 2))
    assert ok1 and not ok2
    assert "seat" in msg2.lower()


def test_pro_has_no_seats():
    ok, msg = run(seats.add_member("o@x.com", "a@y.com", 1))
    assert not ok and "upgrade" in msg.lower()


def test_cannot_add_self():
    ok, _ = run(seats.add_member("o@x.com", "o@x.com", 5))
    assert not ok


def test_member_cannot_join_two_teams():
    run(seats.add_member("o1@x.com", "a@y.com", 5))
    ok, msg = run(seats.add_member("o2@x.com", "a@y.com", 5))
    assert not ok and "another" in msg.lower()


def test_remove_member():
    run(seats.add_member("o@x.com", "a@y.com", 5))
    assert run(seats.remove_member("o@x.com", "a@y.com"))
    assert run(seats.list_members("o@x.com")) == []
    assert run(seats.owner_of("a@y.com")) is None


def test_invalid_email_rejected():
    ok, _ = run(seats.add_member("o@x.com", "notanemail", 5))
    assert not ok
