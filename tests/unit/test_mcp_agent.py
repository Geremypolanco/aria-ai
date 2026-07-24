"""Unit tests for the ARIA MCP client (apps/core/integrations/mcp_agent.py).

Covers the schema mapping, tool-name sanitization, config validation, MCP
result flattening, and the full function-calling loop — the loop is exercised
with a fake Anthropic client and a fake MCP connection so no network or API key
is required.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.core.integrations.mcp_agent import (
    MCPAgent,
    MCPServerConfig,
    _result_to_text,
    _sanitize_tool_name,
    mcp_tool_to_anthropic,
)


# ── schema mapping ────────────────────────────────────────────────
def test_mcp_tool_to_anthropic_basic():
    tool = SimpleNamespace(
        name="get_weather",
        description="Get the weather",
        inputSchema={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    )
    mapped = mcp_tool_to_anthropic(tool)
    assert mapped["name"] == "get_weather"
    assert mapped["description"] == "Get the weather"
    assert mapped["input_schema"]["type"] == "object"
    assert "city" in mapped["input_schema"]["properties"]


def test_mcp_tool_to_anthropic_missing_schema_is_normalized():
    tool = SimpleNamespace(name="ping", description=None, inputSchema=None)
    mapped = mcp_tool_to_anthropic(tool, override_name="srv__ping")
    assert mapped["name"] == "srv__ping"
    # description falls back to a generated one
    assert "ping" in mapped["description"]
    # a valid object schema is always produced
    assert mapped["input_schema"]["type"] == "object"
    assert mapped["input_schema"]["properties"] == {}


def test_mcp_tool_to_anthropic_non_object_schema_normalized():
    tool = SimpleNamespace(name="x", description="d", inputSchema={"type": "string"})
    mapped = mcp_tool_to_anthropic(tool)
    assert mapped["input_schema"]["type"] == "object"


# ── name sanitization ─────────────────────────────────────────────
def test_sanitize_tool_name():
    assert _sanitize_tool_name("mem", "store") == "mem__store"
    # invalid chars replaced, length capped at 64
    dirty = _sanitize_tool_name("my server", "do.it!")
    assert dirty == "my_server__do_it_"
    assert len(_sanitize_tool_name("s" * 40, "t" * 40)) == 64


# ── config validation ─────────────────────────────────────────────
def test_config_validate_stdio_requires_command():
    with pytest.raises(ValueError):
        MCPServerConfig(name="x", transport="stdio").validate()


def test_config_validate_sse_requires_url():
    with pytest.raises(ValueError):
        MCPServerConfig(name="x", transport="sse").validate()


def test_config_validate_ok():
    MCPServerConfig(name="x", transport="stdio", command="python3").validate()
    MCPServerConfig(name="y", transport="sse", url="https://h/sse").validate()


# ── result flattening ─────────────────────────────────────────────
def test_result_to_text_success():
    result = SimpleNamespace(
        isError=False,
        content=[
            SimpleNamespace(type="text", text="hello"),
            SimpleNamespace(type="text", text="world"),
        ],
    )
    text, is_error = _result_to_text(result)
    assert text == "hello\nworld"
    assert is_error is False


def test_result_to_text_error():
    result = SimpleNamespace(isError=True, content=[SimpleNamespace(type="text", text="boom")])
    text, is_error = _result_to_text(result)
    assert text == "boom"
    assert is_error is True


# ── full function-calling loop (fakes, no network) ────────────────
class _FakeConn:
    """Stands in for an MCPConnection — records the call and returns a result."""

    def __init__(self):
        self.name = "mem"
        self.tools = [
            SimpleNamespace(
                name="store_memory",
                description="store",
                inputSchema={"type": "object", "properties": {"key": {"type": "string"}}},
            )
        ]
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, real, args):
        self.calls.append((real, args))
        return SimpleNamespace(
            isError=False,
            content=[SimpleNamespace(type="text", text=f"stored {args.get('key')}")],
        )

    async def aclose(self):
        pass


class _FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)

    async def create(self, **kwargs):
        return self._responses.pop(0)


class _FakeAnthropic:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


@pytest.mark.asyncio
async def test_run_executes_tool_then_returns_final_text():
    agent = MCPAgent([MCPServerConfig(name="mem", command="python3")])
    conn = _FakeConn()
    agent._connections = [conn]
    agent._routing = {"mem__store_memory": (conn, "store_memory")}

    # Turn 1: Claude asks for the tool. Turn 2: Claude gives a final answer.
    tool_use = SimpleNamespace(
        type="tool_use", id="tu_1", name="mem__store_memory", input={"key": "color"}
    )
    final = SimpleNamespace(type="text", text="Guardado el color.")
    agent._anthropic = _FakeAnthropic(
        [
            SimpleNamespace(stop_reason="tool_use", content=[tool_use]),
            SimpleNamespace(stop_reason="end_turn", content=[final]),
        ]
    )

    result = await agent.run("guarda mi color")

    assert result.text == "Guardado el color."
    assert result.stop_reason == "end_turn"
    assert result.turns == 2
    assert conn.calls == [("store_memory", {"key": "color"})]
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool == "mem__store_memory"
    assert result.tool_calls[0].is_error is False


@pytest.mark.asyncio
async def test_run_no_tool_returns_immediately():
    agent = MCPAgent([MCPServerConfig(name="mem", command="python3")])
    agent._connections = []
    agent._routing = {}
    final = SimpleNamespace(type="text", text="Hola.")
    agent._anthropic = _FakeAnthropic([SimpleNamespace(stop_reason="end_turn", content=[final])])

    result = await agent.run("hola")
    assert result.text == "Hola."
    assert result.turns == 1
    assert result.tool_calls == []


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_is_error():
    agent = MCPAgent([MCPServerConfig(name="mem", command="python3")])
    agent._routing = {}
    out, is_error = await agent._dispatch_tool("nope", {})
    assert is_error is True
    assert "unknown" in out.lower()
