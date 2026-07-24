"""End-to-end test: browser_sandbox.py's BrowserSession — ARIA's
general-purpose "browse any page" tool (browse_page/interact_browser in
aria_mind.py) — used a vanilla, un-patched Playwright session with none of
human_browser.py's anti-detection measures. navigator.webdriver alone is
checked by essentially all basic bot-detection (Cloudflare, DataDome,
PerimeterX, and plenty of sites' own JS), so every real-world page ARIA
"browsed like a human" was trivially flagged as an automated browser.
This actually launches Chromium (not mocked) and inspects real page state.
"""

from __future__ import annotations

import pytest

from apps.core.tools.browser_sandbox import BrowserSession


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            browser.close()
        return True
    except Exception:
        return False


requires_chromium = pytest.mark.skipif(
    not _chromium_available(), reason="Chromium not available in this environment"
)


@requires_chromium
@pytest.mark.asyncio
async def test_navigator_webdriver_is_hidden():
    session = BrowserSession()
    try:
        assert await session._ensure_browser()
        await session._page.goto("about:blank")
        webdriver_flag = await session._page.evaluate("() => navigator.webdriver")
        assert webdriver_flag is None or webdriver_flag is False
    finally:
        await session.close()


@requires_chromium
@pytest.mark.asyncio
async def test_plugins_are_spoofed_to_look_like_a_real_browser():
    session = BrowserSession()
    try:
        assert await session._ensure_browser()
        await session._page.goto("about:blank")
        plugin_count = await session._page.evaluate("() => navigator.plugins.length")
        assert plugin_count > 0
    finally:
        await session.close()


@requires_chromium
@pytest.mark.asyncio
async def test_click_and_fill_still_work_with_added_human_timing():
    """Sanity check: the added randomized delays/typing must not break the
    actual interaction — this is still the primary use case."""
    session = BrowserSession()
    try:
        assert await session._ensure_browser()
        await session._page.set_content(
            "<html><body><input id='name' /><button id='go'>Go</button></body></html>"
        )
        fill_result = await session.fill_field("#name", "ARIA")
        assert fill_result["success"] is True
        value = await session._page.eval_on_selector("#name", "el => el.value")
        assert value == "ARIA"

        click_result = await session.click("#go")
        assert click_result["success"] is True
    finally:
        await session.close()
