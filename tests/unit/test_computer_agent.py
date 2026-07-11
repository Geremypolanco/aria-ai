"""Unit tests for ARIA's Computer Use agent (apps/core/integrations/computer_agent.py).

The browser is never launched here: a recording subclass of BrowserComputer
captures the physical actions, and a fake Anthropic client drives the loop — so
the tests run in CI with no browser download and no API key.
"""

from __future__ import annotations

from types import SimpleNamespace

from apps.core.integrations.computer_agent import (
    BrowserComputer,
    ComputerUseAgent,
    _tool_result_block,
    computer_tool_def,
)

_FAKE_B64 = "iVBORw0KGgo="  # placeholder base64 PNG header


class _RecordingComputer(BrowserComputer):
    """Records physical actions instead of driving a real browser."""

    def __init__(self):
        super().__init__()
        self.events: list[tuple] = []

    async def move(self, x, y):
        self.events.append(("move", x, y))

    async def click(self, x, y, button="left"):
        self.events.append(("click", x, y, button))

    async def double_click(self, x, y):
        self.events.append(("double_click", x, y))

    async def type_text(self, text):
        self.events.append(("type", text))

    async def key(self, combo):
        self.events.append(("key", combo))

    async def scroll(self, x, y, dx=0, dy=0):
        self.events.append(("scroll", x, y, dx, dy))

    async def screenshot_b64(self):
        return _FAKE_B64


# ── tool definition + tool_result formatting ──────────────────────
def test_computer_tool_def_shape():
    d = computer_tool_def()
    assert d["type"].startswith("computer_")
    assert d["name"] == "computer"
    assert d["display_width_px"] == 1024
    assert d["display_height_px"] == 768


def test_tool_result_block_image():
    block = _tool_result_block("tu_1", {"image_b64": _FAKE_B64})
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "tu_1"
    src = block["content"][0]["source"]
    assert block["content"][0]["type"] == "image"
    assert src["type"] == "base64"
    assert src["media_type"] == "image/png"
    assert src["data"] == _FAKE_B64


def test_tool_result_block_text():
    block = _tool_result_block("tu_2", {"text": "no soportada"})
    assert block["content"][0]["type"] == "text"
    assert block["content"][0]["text"] == "no soportada"


# ── action dispatch ───────────────────────────────────────────────
async def test_execute_click_returns_screenshot():
    comp = _RecordingComputer()
    out = await comp.execute({"action": "left_click", "coordinate": [200, 150]})
    assert ("click", 200, 150, "left") in comp.events
    assert out == {"image_b64": _FAKE_B64}  # feedback visual tras la acción


async def test_execute_type_and_key():
    comp = _RecordingComputer()
    await comp.execute({"action": "type", "text": "hola"})
    await comp.execute({"action": "key", "text": "Return"})
    assert ("type", "hola") in comp.events
    assert ("key", "Return") in comp.events


async def test_execute_screenshot_only():
    comp = _RecordingComputer()
    out = await comp.execute({"action": "screenshot"})
    assert out == {"image_b64": _FAKE_B64}
    assert comp.events == []  # screenshot no genera acción física


async def test_execute_unknown_action():
    comp = _RecordingComputer()
    out = await comp.execute({"action": "teleport"})
    assert "no soportada" in out["text"]


async def test_run_mock_executes_all_actions():
    comp = _RecordingComputer()
    agent = ComputerUseAgent(comp)
    run = await agent.run_mock(
        [
            {"action": "screenshot"},
            {"action": "left_click", "coordinate": [10, 20]},
            {"action": "type", "text": "x"},
        ]
    )
    assert len(run.steps) == 3
    assert all(s.kind == "image" for s in run.steps)
    assert ("click", 10, 20, "left") in comp.events


# ── full agent loop with a fake Anthropic client ──────────────────
class _FakeBetaMessages:
    def __init__(self, responses):
        self._responses = list(responses)

    async def create(self, **kwargs):
        return self._responses.pop(0)


class _FakeAnthropic:
    def __init__(self, responses):
        self.beta = SimpleNamespace(messages=_FakeBetaMessages(responses))


async def test_run_loop_executes_action_then_finishes():
    comp = _RecordingComputer()
    agent = ComputerUseAgent(comp)

    tool_use = SimpleNamespace(
        type="tool_use",
        id="tu_1",
        name="computer",
        input={"action": "left_click", "coordinate": [100, 100]},
    )
    final = SimpleNamespace(type="text", text="Listo, hice clic.")
    agent._anthropic = _FakeAnthropic(
        [
            SimpleNamespace(stop_reason="tool_use", content=[tool_use]),
            SimpleNamespace(stop_reason="end_turn", content=[final]),
        ]
    )

    run = await agent.run("haz clic en el botón", max_steps=5)
    assert run.final_text == "Listo, hice clic."
    assert run.stop_reason == "end_turn"
    assert len(run.steps) == 1
    assert ("click", 100, 100, "left") in comp.events


async def test_run_loop_handles_pause_turn():
    comp = _RecordingComputer()
    agent = ComputerUseAgent(comp)
    final = SimpleNamespace(type="text", text="ok")
    agent._anthropic = _FakeAnthropic(
        [
            SimpleNamespace(
                stop_reason="pause_turn", content=[SimpleNamespace(type="text", text="")]
            ),
            SimpleNamespace(stop_reason="end_turn", content=[final]),
        ]
    )
    run = await agent.run("tarea larga", max_steps=5)
    assert run.final_text == "ok"
