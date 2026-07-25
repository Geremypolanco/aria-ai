"""Regression test: _client_ip (rate-limit keying) trusted the *first*
X-Forwarded-For entry, which is exactly the hop a client controls themselves
before the request ever reaches Fly.io's edge. Any caller could send a
different X-Forwarded-For per request and get a fresh rate-limit bucket every
time, defeating every IP-keyed limiter (login, signup, admin login, chat,
code execution, ...). Fixed to prefer Fly's own Fly-Client-IP header, and to
fall back to the *last* XFF entry (the hop Fly's proxy itself appended)
rather than the first."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apps.core.main import _client_ip as main_client_ip
from apps.core.security.deps import _client_ip as deps_client_ip


def _fake_request(headers: dict[str, str], client_host: str | None = "10.0.0.1") -> MagicMock:
    req = MagicMock()
    req.headers = headers
    req.client = MagicMock(host=client_host) if client_host else None
    return req


@pytest.mark.parametrize("client_ip_fn", [main_client_ip, deps_client_ip])
class TestClientIPSpoofing:
    def test_prefers_fly_client_ip_header(self, client_ip_fn):
        req = _fake_request(
            {"fly-client-ip": "203.0.113.9", "x-forwarded-for": "1.2.3.4, 203.0.113.9"}
        )
        assert client_ip_fn(req) == "203.0.113.9"

    def test_falls_back_to_last_xff_entry_not_first(self, client_ip_fn):
        """An attacker-supplied first hop must not be trusted — only the
        entry Fly's own proxy appended (the last one) is trustworthy."""
        req = _fake_request({"x-forwarded-for": "1.2.3.4, 203.0.113.9"})
        assert client_ip_fn(req) == "203.0.113.9"

    def test_spoofed_first_hop_no_longer_yields_a_fresh_identity_per_request(self, client_ip_fn):
        """The real regression: two requests from the same actual client, each
        spoofing a different fake first hop, must resolve to the SAME IP —
        otherwise each request gets its own rate-limit bucket."""
        req_a = _fake_request({"x-forwarded-for": "1.1.1.1, 203.0.113.9"})
        req_b = _fake_request({"x-forwarded-for": "9.9.9.9, 203.0.113.9"})
        assert client_ip_fn(req_a) == client_ip_fn(req_b) == "203.0.113.9"

    def test_falls_back_to_request_client_host_when_no_headers(self, client_ip_fn):
        req = _fake_request({}, client_host="10.0.0.1")
        assert client_ip_fn(req) == "10.0.0.1"

    def test_falls_back_to_unknown_when_nothing_available(self, client_ip_fn):
        req = _fake_request({}, client_host=None)
        assert client_ip_fn(req) == "unknown"
