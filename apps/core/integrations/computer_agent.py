"""
computer_agent.py — "Computer Use" Agent for ARIA (Manus AI style).

Technical foundation for ARIA to autonomously control a computer using
Anthropic's native **Computer Use** API over an isolated environment (sandbox): a
Chromium browser controlled with Playwright.

Flow (Agent Loop with visual feedback):
  1. ARIA receives a task in natural language.
  2. Claude (multimodal model) looks at a screenshot and decides a
     physical action with coordinates (X, Y): move the mouse, click, type, etc.
  3. We execute that action in the sandbox (Playwright).
  4. We take a new screenshot, convert it to Base64, and inject it back
     as a `tool_result` in the API history.
  5. This repeats until Claude finishes (`stop_reason == "end_turn"`).

Everything is asynchronous (`async/await`) so it can run in the background within
a task queue (Manus pattern).

No keys / no token spend:
  - `BrowserComputer` and the action executor work 100% offline.
  - `ComputerUseAgent.run_mock()` runs a scripted sequence of actions
    against the real browser and tests the ENTIRE visual feedback loop
    (screenshot → base64 → tool_result) without calling Anthropic.
  - `ComputerUseAgent.run()` only uses the Anthropic API if ANTHROPIC_API_KEY is set.

Notes on versions:
  The user requested `claude-3-5-sonnet` + `computer_20241022`. That model is
  retired; we default to the current stable equivalent (`claude-sonnet-5`
  + `computer_20251124` tool, `computer-use-2025-11-24` beta). Everything is
  configurable via the constants below.
"""

from __future__ import annotations

import base64
import glob
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("aria.computer_agent")

# ── Sandbox and model configuration ────────────────────────
DISPLAY_WIDTH = 1024
DISPLAY_HEIGHT = 768

# Multimodal model + Computer Use tool (current stable versions).
MODEL = "claude-sonnet-5"
COMPUTER_TOOL_TYPE = "computer_20251124"
COMPUTER_BETA = "computer-use-2025-11-24"


def _find_chromium() -> str | None:
    """Locates a preinstalled Chromium binary (fallback if the Playwright
    version doesn't match the downloaded build). Can be forced with
    ARIA_CHROMIUM_PATH."""
    env = os.getenv("ARIA_CHROMIUM_PATH")
    if env and os.path.exists(env):
        return env
    root = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    matches = sorted(glob.glob(f"{root}/chromium-*/chrome-linux/chrome"))
    return matches[-1] if matches else None


SYSTEM_PROMPT = (
    "You are ARIA operating a computer through a web browser. "
    "Observe the screenshot, reason about the next step, and use the "
    "'computer' tool to act (move, click, type, keys). "
    "Work step by step; take a screenshot whenever you need to see the state."
)


def computer_tool_def(width: int = DISPLAY_WIDTH, height: int = DISPLAY_HEIGHT) -> dict[str, Any]:
    """Definition of the native Computer Use tool for Claude's payload."""
    return {
        "type": COMPUTER_TOOL_TYPE,
        "name": "computer",
        "display_width_px": width,
        "display_height_px": height,
        "display_number": 1,
    }


# ──────────────────────────────────────────────────────────────────
# Sandbox: a Chromium browser as a "computer"
# ──────────────────────────────────────────────────────────────────
class BrowserComputer:
    """Isolated environment controlled by Playwright that executes physical actions.

    Translates Computer Use API actions (coordinate-based) into
    real browser operations and produces Base64 screenshots.
    """

    def __init__(
        self,
        width: int = DISPLAY_WIDTH,
        height: int = DISPLAY_HEIGHT,
        headless: bool = True,
        start_url: str = "about:blank",
    ):
        self.width = width
        self.height = height
        self.headless = headless
        self.start_url = start_url
        self._pw: Any = None
        self._browser: Any = None
        self._page: Any = None
        self._cursor: tuple[int, int] = (width // 2, height // 2)

    async def start(self) -> None:
        """Launches the isolated browser at the standard resolution."""
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        launch_kwargs: dict[str, Any] = {"headless": self.headless}
        try:
            self._browser = await self._pw.chromium.launch(**launch_kwargs)
        except Exception as exc:  # noqa: BLE001 — fallback to preinstalled binary
            chromium = _find_chromium()
            logger.warning(
                "[computer] default launch failed (%s); using executable_path=%s", exc, chromium
            )
            self._browser = await self._pw.chromium.launch(
                executable_path=chromium, **launch_kwargs
            )
        context = await self._browser.new_context(
            viewport={"width": self.width, "height": self.height}
        )
        self._page = await context.new_page()
        if self.start_url and self.start_url != "about:blank":
            try:
                await self._page.goto(self.start_url)
            except Exception as exc:  # noqa: BLE001 — egress may be restricted
                logger.warning("[computer] could not open %s: %s", self.start_url, exc)
        logger.info("[computer] sandbox ready (%dx%d)", self.width, self.height)

    # ── coordinate-based physical actions ──────────────────
    async def goto(self, url: str) -> None:
        await self._page.goto(url)

    async def load_html(self, html: str) -> None:
        """Renders local HTML in the browser (useful without network access)."""
        await self._page.set_content(html, wait_until="load")

    async def move(self, x: int, y: int) -> None:
        self._cursor = (x, y)
        await self._page.mouse.move(x, y)

    async def click(self, x: int, y: int, button: str = "left") -> None:
        self._cursor = (x, y)
        await self._page.mouse.click(x, y, button=button)

    async def double_click(self, x: int, y: int) -> None:
        self._cursor = (x, y)
        await self._page.mouse.dblclick(x, y)

    async def type_text(self, text: str) -> None:
        await self._page.keyboard.type(text)

    async def key(self, combo: str) -> None:
        # Computer Use uses xdotool notation ("Return", "ctrl+a"); Playwright uses "+".
        mapped = "+".join(part.capitalize() if len(part) > 1 else part for part in combo.split("+"))
        await self._page.keyboard.press(mapped)

    async def scroll(self, x: int, y: int, dx: int = 0, dy: int = 0) -> None:
        await self._page.mouse.move(x, y)
        await self._page.mouse.wheel(dx, dy)

    async def screenshot_b64(self) -> str:
        """Captures the screen and returns it as a Base64 PNG."""
        png = await self._page.screenshot(type="png")
        return base64.b64encode(png).decode("ascii")

    async def close(self) -> None:
        try:
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[computer] error closing: %s", exc)

    # ── dispatcher for a Computer Use API action ──────────
    async def execute(self, action_input: dict[str, Any]) -> dict[str, Any]:
        """Executes a `computer` action and returns the result for the tool_result.

        Returns {"image_b64": ...} for actions that produce a screenshot, or
        {"text": ...} for actions without an image.
        """
        action = action_input.get("action")
        coord = action_input.get("coordinate") or [None, None]
        x, y = (coord + [None, None])[:2]

        if action == "screenshot":
            return {"image_b64": await self.screenshot_b64()}
        if action == "mouse_move":
            await self.move(int(x), int(y))
        elif action in ("left_click", "right_click", "middle_click"):
            button = {"left_click": "left", "right_click": "right", "middle_click": "middle"}[
                action
            ]
            await self.click(int(x), int(y), button=button)
        elif action == "double_click":
            await self.double_click(int(x), int(y))
        elif action == "type":
            await self.type_text(action_input.get("text", ""))
        elif action == "key":
            await self.key(action_input.get("text", ""))
        elif action == "scroll":
            amount = int(action_input.get("scroll_amount", 3)) * 100
            direction = action_input.get("scroll_direction", "down")
            dy = amount if direction == "down" else -amount if direction == "up" else 0
            dx = amount if direction == "right" else -amount if direction == "left" else 0
            await self.scroll(int(x or self._cursor[0]), int(y or self._cursor[1]), dx, dy)
        elif action in ("cursor_position", "wait"):
            pass  # no physical effect; we still return a screenshot
        else:
            return {"text": f"unsupported action: {action}"}

        # After any physical action we return a fresh screenshot (visual feedback).
        return {"image_b64": await self.screenshot_b64()}


# ──────────────────────────────────────────────────────────────────
# Agent: execution loop with Claude (Computer Use)
# ──────────────────────────────────────────────────────────────────
@dataclass
class AgentStep:
    action: dict[str, Any]
    kind: str  # "image" | "text"


@dataclass
class AgentRun:
    final_text: str
    steps: list[AgentStep] = field(default_factory=list)
    stop_reason: str | None = None


def _tool_result_block(tool_use_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Converts an action's result into an Anthropic tool_result block.

    A screenshot is injected as a Base64 image block (visual feedback);
    everything else as text.
    """
    if "image_b64" in result:
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": result["image_b64"],
                },
            }
        ]
    else:
        content = [{"type": "text", "text": result.get("text", "")}]
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}


class ComputerUseAgent:
    """Computer Use agentic loop — asynchronous, ready for a task queue."""

    def __init__(
        self,
        computer: BrowserComputer,
        *,
        api_key: str | None = None,
        model: str = MODEL,
        system: str = SYSTEM_PROMPT,
    ):
        self.computer = computer
        self.model = model
        self.system = system
        self._api_key = api_key
        self._anthropic: Any = None

    def _client(self) -> Any:
        if self._anthropic is None:
            from anthropic import AsyncAnthropic

            self._anthropic = AsyncAnthropic(api_key=self._api_key)
        return self._anthropic

    async def run(self, task: str, *, max_steps: int = 15, max_tokens: int = 4096) -> AgentRun:
        """Real loop with Claude. Requires ANTHROPIC_API_KEY."""
        client = self._client()
        tools = [computer_tool_def(self.computer.width, self.computer.height)]
        messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
        run = AgentRun(final_text="")

        for _ in range(max_steps):
            response = await client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=self.system,
                tools=tools,
                betas=[COMPUTER_BETA],
                messages=messages,
            )
            run.stop_reason = response.stop_reason

            # pause_turn: the server-side loop paused; resend to continue.
            if response.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": response.content})
                continue

            if response.stop_reason != "tool_use":
                run.final_text = "".join(
                    b.text for b in response.content if getattr(b, "type", None) == "text"
                ).strip()
                return run

            messages.append({"role": "assistant", "content": response.content})
            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                result = await self.computer.execute(block.input or {})
                run.steps.append(
                    AgentStep(
                        action=block.input or {}, kind="image" if "image_b64" in result else "text"
                    )
                )
                tool_results.append(_tool_result_block(block.id, result))
            messages.append({"role": "user", "content": tool_results})

        run.final_text = "(step limit reached)"
        return run

    async def run_mock(self, actions: list[dict[str, Any]]) -> AgentRun:
        """Runs a scripted sequence of actions — WITHOUT calling Anthropic.

        Tests the full visual feedback loop (action → screenshot →
        base64 → tool_result) against the real browser, without spending tokens.
        """
        run = AgentRun(final_text="(mock)", stop_reason="mock")
        for i, action in enumerate(actions):
            result = await self.computer.execute(action)
            # Build the tool_result exactly as it would be sent to the API (format validation).
            block = _tool_result_block(f"mock_{i}", result)
            assert block["type"] == "tool_result"
            run.steps.append(
                AgentStep(action=action, kind="image" if "image_b64" in result else "text")
            )
            logger.info(
                "[computer:mock] step %d %s -> %s", i, action.get("action"), run.steps[-1].kind
            )
        return run
