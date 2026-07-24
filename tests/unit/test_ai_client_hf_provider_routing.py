"""Regression test for a bug found auditing ai_client.py:

AriaAIClient._try_hf_with_rotation() loops over HF_PROVIDER_ROTATION
("together", "nebius", "hf-inference", "featherless-ai") and passes each
provider name into _call_huggingface(), but that method built its request
as {"model": model_id, ...} — dropping the provider entirely. The HF router
(router.huggingface.co) only dispatches to a specific inference provider
when the model field uses the "model_id:provider" suffix syntax; without
it, every "rotation" iteration sent the exact same unrouted request, so a
transient failure on one provider was retried as an identical no-op up to
4 times per model before ever moving to the next model, and the "HF fallo"
log lines misattributed failures to providers that were never actually
contacted.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.core.tools.ai_client import AriaAIClient

pytestmark = pytest.mark.asyncio


async def test_call_huggingface_routes_to_requested_provider(monkeypatch):
    client = AriaAIClient.__new__(AriaAIClient)

    captured = {}
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "hi"}}],
        "usage": {"total_tokens": 5},
    }

    async def fake_post(url, json=None, headers=None):
        captured["json"] = json
        return fake_response

    client._http = MagicMock()
    client._http.post = AsyncMock(side_effect=fake_post)
    monkeypatch.setattr("apps.core.tools.ai_client.settings.HF_TOKEN", "hf_fake_key")

    await client._call_huggingface(
        "Qwen/Qwen2.5-72B-Instruct", "sys", "usr", 100, 0.7, "together"
    )

    assert captured["json"]["model"] == "Qwen/Qwen2.5-72B-Instruct:together"
