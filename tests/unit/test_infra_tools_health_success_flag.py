"""Regression test: InfraTools.monitor_api_health() returned "success": True
unconditionally regardless of whether the monitored endpoints were actually
up, so a caller checking the top-level success flag (rather than digging
into health[url]["up"] for every url) would believe the health check passed
even when every single monitored endpoint was down.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.tools.infra_tools import InfraTools

pytestmark = pytest.mark.asyncio


async def test_monitor_api_health_reports_failure_when_all_endpoints_down():
    tools = InfraTools()
    fake_resp = MagicMock(status_code=500)

    with patch("apps.core.tools.web_tools._assert_public_url", AsyncMock()):
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=fake_resp)):
            result = await tools.monitor_api_health(["https://example.com/health"])

    assert result["success"] is False


async def test_monitor_api_health_reports_success_when_all_endpoints_up():
    tools = InfraTools()
    fake_resp = MagicMock(status_code=200)

    with patch("apps.core.tools.web_tools._assert_public_url", AsyncMock()):
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=fake_resp)):
            result = await tools.monitor_api_health(["https://example.com/health"])

    assert result["success"] is True
