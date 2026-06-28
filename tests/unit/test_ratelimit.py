"""Unit tests for the reusable rate-limit dependency."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from apps.api.ratelimit import _client_ip, rate_limit


def _request(ip="1.2.3.4", headers=None):
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = ip
    req.headers = headers or {}
    return req


class TestClientIP:
    def test_prefers_fly_client_ip(self):
        req = _request("10.0.0.1", {"fly-client-ip": "203.0.113.7", "x-forwarded-for": "1.1.1.1"})
        assert _client_ip(req) == "203.0.113.7"

    def test_falls_back_to_xff_first_hop(self):
        req = _request("10.0.0.1", {"x-forwarded-for": "198.51.100.9, 10.0.0.1"})
        assert _client_ip(req) == "198.51.100.9"

    def test_falls_back_to_socket_peer(self):
        assert _client_ip(_request("192.0.2.5")) == "192.0.2.5"


class TestRateLimit:
    async def test_allows_when_under_limit(self):
        cache = MagicMock()
        cache.check_rate_limit = AsyncMock(return_value=True)
        with patch("apps.core.memory.redis_client.get_cache", return_value=cache):
            dep = rate_limit(5, 60, "test")
            assert await dep(_request()) is None  # no raise

    async def test_blocks_when_over_limit(self):
        cache = MagicMock()
        cache.check_rate_limit = AsyncMock(return_value=False)
        with patch("apps.core.memory.redis_client.get_cache", return_value=cache):
            dep = rate_limit(5, 60, "test")
            with pytest.raises(HTTPException) as exc:
                await dep(_request())
            assert exc.value.status_code == 429

    async def test_fails_open_without_cache(self):
        with patch("apps.core.memory.redis_client.get_cache", return_value=None):
            dep = rate_limit(5, 60, "test")
            assert await dep(_request()) is None  # fail-open, no raise

    async def test_fails_open_on_limiter_error(self):
        cache = MagicMock()
        cache.check_rate_limit = AsyncMock(side_effect=RuntimeError("redis down"))
        with patch("apps.core.memory.redis_client.get_cache", return_value=cache):
            dep = rate_limit(5, 60, "test")
            assert await dep(_request()) is None  # fail-open on error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
