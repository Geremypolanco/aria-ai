"""
computer_agent_demo.py — Initial test of ARIA's Computer Use agent.

Spins up the isolated browser (Chromium/Playwright), "opens a page," and runs
the visual feedback loop with a scripted sequence of actions (move mouse →
click → type → screenshot). Saves the screenshots to the scratchpad. Spends
NO tokens: uses run_mock().

If ANTHROPIC_API_KEY is set, it also runs the real loop with Claude on the
same task ("open a browser and search for something").

Usage:  python3 scripts/computer_agent_demo.py
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.core.integrations.computer_agent import (  # noqa: E402
    BrowserComputer,
    ComputerUseAgent,
)

OUT = Path(os.getenv("ARIA_SCRATCH", "/tmp/claude-0/-home-user-aria-ai/scratchpad"))
OUT.mkdir(parents=True, exist_ok=True)


async def main() -> None:
    print("=" * 64)
    print("1) Starting the sandbox (headless Chromium, 1024x768) and opening a page")
    print("=" * 64)
    computer = BrowserComputer(headless=True)
    await computer.start()
    agent = ComputerUseAgent(computer)

    # Local page (no network dependency): a simulated search bar.
    await computer.load_html(
        """
        <html><body style="font-family:sans-serif;margin:0;background:#f4f1ea">
          <div style="padding:40px">
            <h1 style="color:#c65d3b">ARIA — Sandboxed Browser</h1>
            <input id="q" placeholder="Search for something..."
                   style="width:420px;padding:12px;font-size:18px" />
            <button style="padding:12px 20px;font-size:18px">Search</button>
          </div>
        </body></html>
        """
    )

    try:
        # Action sequence in the style Computer Use itself returns.
        actions = [
            {"action": "screenshot"},
            {"action": "mouse_move", "coordinate": [200, 150]},
            {"action": "left_click", "coordinate": [200, 150]},
            {"action": "type", "text": "ARIA uses the computer"},
            {"action": "screenshot"},
        ]
        print("\n2) Running the visual feedback loop (run_mock):")
        run = await agent.run_mock(actions)
        for i, step in enumerate(run.steps):
            print(f"   step {i}: {step.action.get('action'):12s} -> {step.kind}")

        # Verify the final screenshot is a valid base64 PNG, and save it.
        b64 = await computer.screenshot_b64()
        png = base64.b64decode(b64)
        assert png[:8] == b"\x89PNG\r\n\x1a\n", "screenshot is not a valid PNG"
        shot = OUT / "computer_agent_demo.png"
        shot.write_bytes(png)
        print(f"\n3) Valid final screenshot: {len(png)} bytes -> {shot}")

        if os.getenv("ANTHROPIC_API_KEY"):
            print("\n4) Real loop with Claude (Computer Use):")
            real = await agent.run(
                "You're on example.com. Take a screenshot and tell me what title the page shows.",
                max_steps=6,
            )
            print(f"   Reply: {real.final_text}")
            print(f"   Steps: {len(real.steps)} | stop_reason={real.stop_reason}")
        else:
            print("\n4) [skipped] Set ANTHROPIC_API_KEY to run the real loop with Claude.")
    finally:
        await computer.close()

    print("\nOK — computer use agent operational (sandbox + visual feedback).")


if __name__ == "__main__":
    asyncio.run(main())
