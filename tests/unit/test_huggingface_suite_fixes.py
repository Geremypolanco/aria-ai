"""Regression tests for bugs found auditing huggingface_suite.py:

1. translate() had a "fallback" that unconditionally called the fixed
   en->es model Helsinki-NLP/opus-mt-tc-big-en-es for ANY unsupported
   language pair (mislabeled "multilingual model" in a comment — it isn't)
   and returned that mistranslated output tagged with the original
   source/target and success:True, with no isinstance guard on the
   result shape. Removed the broken fallback.
2. translate_product_listing() returned "success": True unconditionally
   even when every per-language translate() call failed.
3. _gradio_call()'s Gradio-3.x fallback ignored fn_name and hardcoded
   fn_index: 0, silently routing every call to whichever function sits
   at index 0 on the target Space. Now resolves the real fn_index via
   the Space's /config before falling back to 0.
4. generate_structured() called json.loads() directly on the model's raw
   response_format output, unlike the safe-extraction pattern used
   elsewhere in the codebase (ai_client.py's _extract_json_safe) for the
   same "model didn't honor structured output" scenario.
5. generate_structured()/vision_language() created a new
   AsyncInferenceClient per call and never closed it, leaking the
   underlying aiohttp session on every call.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.tools.huggingface_suite import HuggingFaceSuite

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fake_huggingface_hub_module(monkeypatch):
    """huggingface_suite.py imports `from huggingface_hub import
    AsyncInferenceClient` lazily inside methods specifically because the
    real SDK isn't installed in this test environment — inject a fake
    module so that import resolves to our test double."""
    fake_module = types.ModuleType("huggingface_hub")
    fake_module.AsyncInferenceClient = MagicMock()
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_module)
    return fake_module


async def test_translate_no_longer_has_broken_multilingual_fallback():
    suite = HuggingFaceSuite()
    suite._token = "hf_fake"

    with patch.object(HuggingFaceSuite, "_call", AsyncMock(return_value=None)):
        result = await suite.translate("hello", source="en", target="xx")

    assert result["success"] is False
    assert "Helsinki-NLP/opus-mt-tc-big-en-es" not in str(result)


async def test_translate_product_listing_reports_failure_when_all_translations_fail():
    suite = HuggingFaceSuite()
    suite._token = "hf_fake"

    async def fake_translate(text, source, target):
        return {"success": False, "error": "no model"}

    with patch.object(suite, "translate", fake_translate):
        result = await suite.translate_product_listing(
            {"name": "Widget", "description": "A great widget"}, source="es", targets=["en"]
        )

    assert result["success"] is False


async def test_translate_product_listing_reports_success_when_translation_succeeds():
    suite = HuggingFaceSuite()
    suite._token = "hf_fake"

    async def fake_translate(text, source, target):
        return {"success": True, "translated": f"[{target}] {text}"}

    with patch.object(suite, "translate", fake_translate):
        result = await suite.translate_product_listing(
            {"name": "Widget", "description": "A great widget"}, source="es", targets=["en"]
        )

    assert result["success"] is True


async def test_gradio_call_fallback_resolves_fn_index_from_config():
    suite = HuggingFaceSuite()
    suite._token = "hf_fake"

    captured = {}

    async def fake_post(url, **kwargs):
        resp = MagicMock()
        if url.endswith("/call/infer"):
            resp.status_code = 500
        elif url.endswith("/api/predict"):
            captured["json"] = kwargs.get("json")
            resp.status_code = 200
            resp.json.return_value = {"data": ["ok"]}
        return resp

    async def fake_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "dependencies": [
                {"api_name": "/other_fn"},
                {"api_name": "/infer"},
            ]
        }
        return resp

    suite._http.post = fake_post
    suite._http.get = fake_get

    result = await suite._gradio_call("some/space", "infer", ["input"])

    assert result == ["ok"]
    assert captured["json"]["fn_index"] == 1


async def test_generate_structured_extracts_json_from_markdown_fenced_response(
    fake_huggingface_hub_module,
):
    suite = HuggingFaceSuite()
    suite._token = "hf_fake"

    fake_message = MagicMock()
    fake_message.content = '```json\n{"a": 1}\n```'
    fake_choice = MagicMock()
    fake_choice.message = fake_message
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]

    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)
    fake_client.close = AsyncMock()
    fake_huggingface_hub_module.AsyncInferenceClient.return_value = fake_client

    result = await suite.generate_structured("extract", {"type": "object"})

    assert result["success"] is True
    assert result["data"] == {"a": 1}
    fake_client.close.assert_awaited_once()
