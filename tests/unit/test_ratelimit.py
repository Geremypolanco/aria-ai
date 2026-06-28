"""Unit tests for the reusable rate-limit dependency."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from apps.api.ratelimit import rate_limit


def _request(ip="1.2.3.4"):
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = ip
    return req


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
