"""Regression test: HFDiscovery._run_model()'s 503 (model cold-start) retry
path posted a second request into `res2`, but if that retry ALSO failed
(non-200), the fallthrough error report at the bottom of the method still
referenced the original `res` object instead of `res2` — logging/returning
the stale first response's status code and body forever, no matter what the
retry actually returned.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.core.tools.hf_discovery import HFDiscovery

pytestmark = pytest.mark.asyncio


async def test_run_model_reports_retry_response_when_retry_also_fails(monkeypatch):
    hf = HFDiscovery.__new__(HFDiscovery)
    hf._http = MagicMock()

    first = MagicMock()
    first.status_code = 503
    first.json.return_value = {"estimated_time": 0}

    second = MagicMock()
    second.status_code = 429
    second.text = "rate limited on retry"

    hf._http.post = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr("apps.core.tools.hf_discovery.asyncio.sleep", AsyncMock())
    hf._headers = lambda is_binary=False: {}

    result = await hf._run_model("some/model", {"inputs": "hi"})

    assert result["success"] is False
    assert result["error"] == "HTTP 429"
