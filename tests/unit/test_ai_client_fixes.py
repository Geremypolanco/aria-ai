"""Regression tests for bugs found while auditing apps/core/tools/ai_client.py.

1. _extract_json_safe() hardcoded a "{" before "[" preference. For a
   top-level JSON array of objects (e.g. `[{"a":1},{"b":2}]`), it found the
   "{" nested inside the array before the "[", then greedily grabbed up to
   the last "}" — landing before the array's closing "]" and producing
   invalid JSON. complete_json() would then silently return {} for any
   list-shaped AI response.
2. _call_gemini/_call_groq/_call_openai/_call_anthropic called .strip() (or
   indexed straight into a "content" block) without guarding against a
   None/missing content field — unlike _call_huggingface, which already
   guarded with `(... or "").strip()`. A safety-filtered or refusal
   response would raise AttributeError/KeyError that got misattributed to
   the provider as a failure, needlessly tripping its circuit breaker.
"""

from __future__ import annotations

import pytest

from apps.core.tools.ai_client import AriaAIClient


@pytest.fixture
def client():
    return AriaAIClient()


def test_extract_json_safe_handles_top_level_array(client):
    text = 'Here is the list:\n[{"a": 1}, {"b": 2}]\nHope that helps.'
    extracted = client._extract_json_safe(text)
    assert extracted == '[{"a": 1}, {"b": 2}]'


def test_extract_json_safe_handles_top_level_object(client):
    text = '```json\n{"a": 1, "b": [1, 2]}\n```'
    extracted = client._extract_json_safe(text)
    assert extracted == '{"a": 1, "b": [1, 2]}'


def test_extract_json_safe_no_brackets_returns_text(client):
    assert client._extract_json_safe("no json here") == "no json here"


@pytest.mark.asyncio
async def test_call_gemini_handles_safety_blocked_response(client, monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            # Safety-blocked Gemini responses omit "content" entirely.
            return {"candidates": [{"finishReason": "SAFETY"}]}

    async def fake_post(*a, **k):
        return FakeResp()

    monkeypatch.setattr(client._http, "post", fake_post)
    monkeypatch.setattr("apps.core.tools.ai_client.settings.GOOGLE_API_KEY", "fake-key")
    content, tokens = await client._call_gemini("gemini-1.5-flash", "sys", "usr", 100, 0.5)
    assert content == ""


@pytest.mark.asyncio
async def test_call_groq_handles_none_content(client, monkeypatch):
    class FakeMessage:
        content = None

    class FakeChoice:
        message = FakeMessage()

    class FakeUsage:
        total_tokens = 0

    class FakeCompletion:
        choices = [FakeChoice()]
        usage = FakeUsage()

    async def fake_create(*a, **k):
        return FakeCompletion()

    monkeypatch.setattr(client._groq.chat.completions, "create", fake_create)
    content, tokens = await client._call_groq("model", "sys", "usr", 100, 0.5)
    assert content == ""


@pytest.mark.asyncio
async def test_call_openai_handles_none_content(client, monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": None}}], "usage": {"total_tokens": 5}}

    async def fake_post(*a, **k):
        return FakeResp()

    monkeypatch.setattr(client._http, "post", fake_post)
    monkeypatch.setattr("apps.core.tools.ai_client.settings.OPENAI_API_KEY", "fake-key")
    content, tokens = await client._call_openai("model", "sys", "usr", 100, 0.5)
    assert content == ""
    assert tokens == 5


@pytest.mark.asyncio
async def test_call_anthropic_skips_non_text_blocks(client, monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "content": [
                    {"type": "thinking", "thinking": "internal reasoning"},
                    {"type": "text", "text": "final answer"},
                ],
                "usage": {"input_tokens": 1, "output_tokens": 2},
            }

    async def fake_post(*a, **k):
        return FakeResp()

    monkeypatch.setattr(client._http, "post", fake_post)
    content, tokens = await client._call_anthropic("model", "sys", "usr", 100, 0.5)
    assert content == "final answer"
    assert tokens == 3
