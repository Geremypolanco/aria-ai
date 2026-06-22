"""
ARIA Human Browser — Stealth automation engine.

Simulates a real human interacting with a browser:
  - Mouse movement via Bezier curves with natural jitter
  - Typing character-by-character with human timing variance
  - Random micro-pauses between every action
  - JS patches that hide all headless/automation signals
  - Session persistence (cookies + localStorage survive restarts)
  - Canvas, WebGL, and font fingerprint spoofing
  - Realistic browser profile (viewport, timezone, language, plugins)

Drop-in replacement for browser_sandbox.py when stealth is required.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("aria.human_browser")

# ── Stealth JS injected on every page ────────────────────────────────────────
# Patches all known headless detection vectors before any page script runs.

_STEALTH_JS = """
(function() {
  // 1. Hide navigator.webdriver
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

  // 2. Fake plugins (real Chrome has several)
  const fakePlugins = [
    { name: 'Chrome PDF Plugin',    filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
    { name: 'Chrome PDF Viewer',    filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
    { name: 'Native Client',        filename: 'internal-nacl-plugin', description: '' },
  ];
  Object.defineProperty(navigator, 'plugins', {
    get: () => {
      const arr = fakePlugins.map(p => {
        const plugin = Object.create(Plugin.prototype);
        Object.defineProperty(plugin, 'name', { get: () => p.name });
        Object.defineProperty(plugin, 'filename', { get: () => p.filename });
        Object.defineProperty(plugin, 'description', { get: () => p.description });
        return plugin;
      });
      arr.refresh = () => {};
      arr.item = (i) => arr[i];
      arr.namedItem = (n) => arr.find(p => p.name === n);
      Object.defineProperty(arr, 'length', { get: () => fakePlugins.length });
      return arr;
    }
  });

  // 3. Languages
  Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'es'] });

  // 4. Permissions API — headless returns 'denied' for notifications; spoof to 'default'
  if (navigator.permissions) {
    const origQuery = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (params) => {
      if (params.name === 'notifications') {
        return Promise.resolve({ state: 'default', onchange: null });
      }
      return origQuery(params);
    };
  }

  // 5. Chrome object (absent in headless)
  if (!window.chrome) {
    window.chrome = {
      runtime: {},
      loadTimes: function() {},
      csi: function() {},
      app: {},
    };
  }

  // 6. Hide automation-related properties
  const propsToHide = ['__driver_evaluate', '__webdriver_evaluate', '__selenium_evaluate',
    '__fxdriver_evaluate', '__driver_unwrapped', '__webdriver_unwrapped',
    '__selenium_unwrapped', '__fxdriver_unwrapped', '_phantom', '__nightmare',
    '_selenium', 'callPhantom', 'callSelenium', '_Selenium_IDE_Recorder'];
  propsToHide.forEach(prop => {
    try { delete window[prop]; } catch(e) {}
  });

  // 7. Canvas fingerprint noise (tiny, imperceptible noise per session)
  const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = function(type) {
    if (this.width > 16 && this.height > 16) {
      const ctx = this.getContext('2d');
      if (ctx) {
        const imageData = ctx.getImageData(0, 0, this.width, this.height);
        const noise = 3;
        for (let i = 0; i < imageData.data.length; i += 4) {
          imageData.data[i]   = Math.min(255, imageData.data[i]   + (Math.random() * noise | 0));
          imageData.data[i+1] = Math.min(255, imageData.data[i+1] + (Math.random() * noise | 0));
          imageData.data[i+2] = Math.min(255, imageData.data[i+2] + (Math.random() * noise | 0));
        }
        ctx.putImageData(imageData, 0, 0);
      }
    }
    return origToDataURL.apply(this, arguments);
  };

  // 8. WebGL vendor/renderer spoof
  const getParam = WebGLRenderingContext.prototype.getParameter;
  WebGLRenderingContext.prototype.getParameter = function(param) {
    if (param === 37445) return 'Intel Inc.';
    if (param === 37446) return 'Intel Iris OpenGL Engine';
    return getParam.call(this, param);
  };
  if (window.WebGL2RenderingContext) {
    const getParam2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(param) {
      if (param === 37445) return 'Intel Inc.';
      if (param === 37446) return 'Intel Iris OpenGL Engine';
      return getParam2.call(this, param);
    };
  }

  // 9. window.outerWidth / outerHeight (headless defaults to 0)
  if (window.outerWidth === 0) {
    Object.defineProperty(window, 'outerWidth',  { get: () => window.innerWidth });
    Object.defineProperty(window, 'outerHeight', { get: () => window.innerHeight + 74 });
  }
})();
"""

# ── Human timing profiles ─────────────────────────────────────────────────────

def _human_typing_delay(char: str) -> float:
    """Returns delay in seconds before typing this character."""
    base = random.gauss(0.12, 0.04)  # ~120ms avg, 40ms std
    # Space and punctuation are faster
    if char in (' ', '.', ',', '!', '?'):
        base *= 0.7
    # Numbers and special chars are slower
    if char.isdigit() or char in ('@', '#', '$', '%', '&'):
        base *= 1.3
    # Occasional burst (thinking paused, then types fast)
    if random.random() < 0.05:
        base *= 0.3
    # Occasional hesitation
    if random.random() < 0.03:
        base += random.uniform(0.3, 1.2)
    return max(0.04, base)


def _human_pause(mode: str = "action") -> float:
    """Returns a human-realistic pause duration in seconds."""
    if mode == "micro":       # between actions
        return random.uniform(0.1, 0.4)
    if mode == "read":        # reading content
        return random.uniform(0.8, 2.5)
    if mode == "think":       # deciding what to do
        return random.uniform(1.5, 4.0)
    if mode == "action":      # before clicking/typing
        return random.uniform(0.3, 0.9)
    if mode == "navigate":    # waiting for page
        return random.uniform(0.5, 1.5)
    return random.uniform(0.2, 0.6)


def _bezier_points(
    start: tuple[float, float],
    end: tuple[float, float],
    n: int = 20,
) -> list[tuple[float, float]]:
    """
    Generate n points along a cubic Bezier curve from start to end.
    Control points are randomized to simulate natural hand movement.
    """
    sx, sy = start
    ex, ey = end

    # Two random control points that pull the path off a straight line
    dist = math.hypot(ex - sx, ey - sy)
    cp1x = sx + (ex - sx) * random.uniform(0.2, 0.4) + random.uniform(-dist * 0.15, dist * 0.15)
    cp1y = sy + (ey - sy) * random.uniform(0.2, 0.4) + random.uniform(-dist * 0.15, dist * 0.15)
    cp2x = sx + (ex - sx) * random.uniform(0.6, 0.8) + random.uniform(-dist * 0.15, dist * 0.15)
    cp2y = sy + (ey - sy) * random.uniform(0.6, 0.8) + random.uniform(-dist * 0.15, dist * 0.15)

    points = []
    for i in range(n + 1):
        t = i / n
        # Cubic bezier formula
        x = (1-t)**3*sx + 3*(1-t)**2*t*cp1x + 3*(1-t)*t**2*cp2x + t**3*ex
        y = (1-t)**3*sy + 3*(1-t)**2*t*cp1y + 3*(1-t)*t**2*cp2y + t**3*ey
        # Add micro jitter to simulate hand tremor
        x += random.gauss(0, 0.8)
        y += random.gauss(0, 0.8)
        points.append((x, y))

    return points


# ── Session storage ───────────────────────────────────────────────────────────

_SESSION_DIR = Path(os.environ.get("ARIA_SESSION_DIR", "/tmp/aria_sessions"))
_SESSION_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class SessionData:
    cookies: list[dict] = field(default_factory=list)
    local_storage: dict[str, dict] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "cookies": self.cookies,
            "local_storage": self.local_storage,
            "created_at": self.created_at,
            "last_used": self.last_used,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SessionData:
        return cls(
            cookies=d.get("cookies", []),
            local_storage=d.get("local_storage", {}),
            created_at=d.get("created_at", time.time()),
            last_used=d.get("last_used", time.time()),
        )


def _load_session(name: str) -> Optional[SessionData]:
    path = _SESSION_DIR / f"{name}.json"
    if not path.exists():
        return None
    try:
        return SessionData.from_dict(json.loads(path.read_text()))
    except Exception:
        return None


def _save_session(name: str, data: SessionData) -> None:
    data.last_used = time.time()
    path = _SESSION_DIR / f"{name}.json"
    path.write_text(json.dumps(data.to_dict(), indent=2))


# ── Core classes ──────────────────────────────────────────────────────────────

class HumanPage:
    """
    Wraps a Playwright page with human-like interaction methods.
    All actions include natural timing, mouse movement, and random pauses.
    """

    def __init__(self, page, session_name: str = "default") -> None:
        self._page = page
        self._session_name = session_name
        self._mouse_x: float = 400.0
        self._mouse_y: float = 300.0

    # ── Navigation ────────────────────────────────────────────────────────────

    async def goto(self, url: str, wait: str = "domcontentloaded") -> None:
        logger.debug("[HumanBrowser] navigate → %s", url)
        await self._page.goto(url, wait_until=wait, timeout=30_000)
        await self._random_pause("navigate")
        # Simulate reading the page after it loads
        await self._scroll_naturally(random.randint(100, 400))
        await self._random_pause("read")

    # ── Mouse movement ────────────────────────────────────────────────────────

    async def _move_mouse_human(self, x: float, y: float) -> None:
        """Move mouse from current position to (x, y) along a Bezier curve."""
        points = _bezier_points((self._mouse_x, self._mouse_y), (x, y),
                                n=random.randint(15, 30))
        # Accelerate in middle, decelerate at end (easing)
        for i, (px, py) in enumerate(points):
            progress = i / len(points)
            # Ease-in-out: slow at start and end, fast in middle
            speed_factor = 1.0 - abs(progress - 0.5) * 1.2
            delay = random.uniform(0.005, 0.018) * (1.0 + speed_factor * 0.5)
            await self._page.mouse.move(px, py)
            await asyncio.sleep(delay)
        self._mouse_x = x
        self._mouse_y = y

    async def _get_element_center(self, selector: str) -> tuple[float, float]:
        """Returns the center coordinates of an element."""
        el = await self._page.wait_for_selector(selector, timeout=10_000)
        if not el:
            raise ValueError(f"Element not found: {selector}")
        box = await el.bounding_box()
        if not box:
            raise ValueError(f"Element has no bounding box: {selector}")
        # Aim slightly off-center (humans don't click exactly center)
        x = box["x"] + box["width"]  * random.uniform(0.35, 0.65)
        y = box["y"] + box["height"] * random.uniform(0.35, 0.65)
        return x, y

    # ── Click ─────────────────────────────────────────────────────────────────

    async def click(self, selector: str) -> None:
        """Move mouse naturally to element, pause, then click."""
        await self._random_pause("action")
        x, y = await self._get_element_center(selector)
        await self._move_mouse_human(x, y)
        # Brief hover before clicking
        await asyncio.sleep(random.uniform(0.08, 0.25))
        await self._page.mouse.click(x, y)
        await self._random_pause("micro")
        logger.debug("[HumanBrowser] clicked %s", selector)

    async def click_text(self, text: str) -> None:
        """Click the first element containing this visible text."""
        await self.click(f"text={text}")

    # ── Typing ────────────────────────────────────────────────────────────────

    async def type_human(self, selector: str, text: str,
                          clear_first: bool = True) -> None:
        """Click field, then type character by character with human timing."""
        await self.click(selector)
        await asyncio.sleep(random.uniform(0.1, 0.3))

        if clear_first:
            # Select all and delete (human way: Ctrl+A then Delete)
            await self._page.keyboard.press("Control+a")
            await asyncio.sleep(random.uniform(0.05, 0.15))
            await self._page.keyboard.press("Delete")
            await asyncio.sleep(random.uniform(0.08, 0.2))

        for char in text:
            # Occasional typo + correction (3% of characters)
            if random.random() < 0.03 and char.isalpha():
                wrong = random.choice("qwertyuiopasdfghjklzxcvbnm")
                await self._page.keyboard.type(wrong)
                await asyncio.sleep(_human_typing_delay(wrong))
                await self._page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.1, 0.3))

            await self._page.keyboard.type(char)
            await asyncio.sleep(_human_typing_delay(char))

        logger.debug("[HumanBrowser] typed %d chars into %s", len(text), selector)

    # ── Scrolling ─────────────────────────────────────────────────────────────

    async def _scroll_naturally(self, pixels: int) -> None:
        """Scroll smoothly in multiple steps, like a human using a mouse wheel."""
        steps = random.randint(3, 8)
        per_step = pixels / steps
        for _ in range(steps):
            delta = per_step + random.gauss(0, per_step * 0.2)
            await self._page.mouse.wheel(0, delta)
            await asyncio.sleep(random.uniform(0.05, 0.2))

    async def scroll_down(self, pixels: int = 500) -> None:
        await self._random_pause("micro")
        await self._scroll_naturally(pixels)

    async def scroll_up(self, pixels: int = 300) -> None:
        await self._random_pause("micro")
        await self._scroll_naturally(-pixels)

    # ── Idle / random behavior ────────────────────────────────────────────────

    async def _random_pause(self, mode: str = "action") -> None:
        await asyncio.sleep(_human_pause(mode))

    async def idle_behavior(self) -> None:
        """
        Random idle activity — moves mouse aimlessly, maybe scrolls a bit.
        Call this while waiting for something to look more human.
        """
        action = random.choice(["move", "scroll", "wait"])
        if action == "move":
            x = random.uniform(100, 1200)
            y = random.uniform(100, 700)
            await self._move_mouse_human(x, y)
        elif action == "scroll":
            direction = random.choice([100, -100, 200, -50])
            await self._scroll_naturally(direction)
        else:
            await asyncio.sleep(random.uniform(0.5, 2.0))

    # ── Wait for navigation ───────────────────────────────────────────────────

    async def wait_for_url(self, pattern: str, timeout: float = 15.0) -> bool:
        """Wait until the URL matches a substring."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if pattern in self._page.url:
                return True
            await self.idle_behavior()
            await asyncio.sleep(0.5)
        return False

    async def wait_for_selector(self, selector: str, timeout: float = 10.0):
        return await self._page.wait_for_selector(selector, timeout=int(timeout * 1000))

    # ── Content extraction ────────────────────────────────────────────────────

    async def get_text(self, selector: str) -> str:
        el = await self._page.query_selector(selector)
        if el:
            return (await el.text_content() or "").strip()
        return ""

    async def get_page_text(self, max_chars: int = 5000) -> str:
        return (await self._page.inner_text("body"))[:max_chars]

    async def screenshot(self) -> bytes:
        return await self._page.screenshot(type="png", full_page=False)

    async def evaluate(self, js: str):
        return await self._page.evaluate(js)

    @property
    def url(self) -> str:
        return self._page.url

    # ── Session management ────────────────────────────────────────────────────

    async def save_session(self) -> None:
        """Persist cookies and localStorage so login survives restarts."""
        try:
            context = self._page.context
            cookies = await context.cookies()

            # Grab localStorage for known domains
            local_storage: dict[str, dict] = {}
            try:
                storage = await self._page.evaluate(
                    "() => Object.fromEntries(Object.entries(localStorage))"
                )
                domain = self._page.url.split("/")[2] if self._page.url.startswith("http") else "unknown"
                local_storage[domain] = storage or {}
            except Exception:
                pass

            session = SessionData(cookies=cookies, local_storage=local_storage)
            _save_session(self._session_name, session)
            logger.info("[HumanBrowser] session saved: %s (%d cookies)", self._session_name, len(cookies))
        except Exception as exc:
            logger.warning("[HumanBrowser] save_session failed: %s", exc)

    async def load_session(self) -> bool:
        """Restore a previous session. Returns True if session was found."""
        session = _load_session(self._session_name)
        if not session:
            return False
        try:
            context = self._page.context
            if session.cookies:
                await context.add_cookies(session.cookies)

            # Restore localStorage after navigating to the domain
            for domain, storage in session.local_storage.items():
                if storage:
                    js = "items => { for (const [k,v] of Object.entries(items)) localStorage.setItem(k, v); }"
                    await self._page.evaluate(js, storage)

            logger.info("[HumanBrowser] session loaded: %s (%d cookies)", self._session_name, len(session.cookies))
            return True
        except Exception as exc:
            logger.warning("[HumanBrowser] load_session failed: %s", exc)
            return False


class HumanBrowser:
    """
    Stealth browser manager. Launches Chromium with all anti-detection measures.

    Usage:
        async with HumanBrowser() as browser:
            page = await browser.new_page("gumroad_session")
            await page.goto("https://gumroad.com/login")
            await page.type_human("#email", "user@example.com")
            await page.type_human("#password", "mypassword")
            await page.click("button[type=submit]")
            await page.save_session()
    """

    # Realistic user agents (rotate per session)
    _USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    ]

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._contexts: dict[str, object] = {}

    async def start(self) -> None:
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--no-zygote",
                "--disable-gpu",
                "--window-size=1366,768",
                "--disable-extensions",
                # Remove automation flags from navigator
                "--exclude-switches=enable-automation",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        logger.info("[HumanBrowser] launched")

    async def new_page(self, session_name: str = "default") -> HumanPage:
        """Create a new stealth page, optionally restoring a saved session."""
        ua = random.choice(self._USER_AGENTS)

        context = await self._browser.new_context(
            user_agent=ua,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/New_York",
            # Fake screen size (outerWidth/outerHeight)
            screen={"width": 1366, "height": 768},
            java_script_enabled=True,
            accept_downloads=True,
            color_scheme="light",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            },
        )
        self._contexts[session_name] = context

        page = await context.new_page()

        # Inject stealth patches before ANY page script executes
        await page.add_init_script(_STEALTH_JS)

        # Override navigator properties that Playwright sets
        await page.add_init_script("""
            Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 4 });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
        """)

        human_page = HumanPage(page, session_name)
        return human_page

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("[HumanBrowser] closed")

    async def __aenter__(self) -> "HumanBrowser":
        await self.start()
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()


# ── High-level login flows ────────────────────────────────────────────────────

class PlatformLogin:
    """
    Ready-to-use login flows for common platforms.
    Saves session after login so subsequent runs skip the login step.
    """

    def __init__(self, browser: HumanBrowser) -> None:
        self._browser = browser

    async def gumroad(self, email: str, password: str) -> HumanPage:
        """Login to Gumroad. Returns an authenticated page."""
        page = await self._browser.new_page("gumroad")

        # Try restoring saved session first
        await page.goto("https://gumroad.com")
        if await page.load_session():
            await page.goto("https://gumroad.com/dashboard")
            await asyncio.sleep(2)
            if "dashboard" in page.url or "gumroad.com" in page.url:
                logger.info("[HumanBrowser] Gumroad: session restored, skipping login")
                return page

        # Fresh login
        await page.goto("https://gumroad.com/login")
        await page._random_pause("read")
        await page.type_human("input[name='email']", email)
        await page.type_human("input[name='password']", password)
        await page._random_pause("think")
        await page.click("button[type='submit']")
        await page._random_pause("navigate")

        if await page.wait_for_url("dashboard", timeout=15.0):
            logger.info("[HumanBrowser] Gumroad: login successful")
            await page.save_session()
        else:
            logger.warning("[HumanBrowser] Gumroad: login may have failed — url: %s", page.url)
        return page

    async def devto(self, email: str, password: str) -> HumanPage:
        """Login to Dev.to."""
        page = await self._browser.new_page("devto")
        await page.goto("https://dev.to")
        if await page.load_session():
            logger.info("[HumanBrowser] Dev.to: session restored")
            return page

        await page.goto("https://dev.to/enter")
        await page._random_pause("read")
        await page.click("button[data-name='email']")
        await page._random_pause("action")
        await page.type_human("#user_email", email)
        await page.type_human("#user_password", password)
        await page._random_pause("think")
        await page.click("input[type='submit'][value='Log in']")
        await page._random_pause("navigate")

        if await page.wait_for_url("dev.to", timeout=15.0):
            logger.info("[HumanBrowser] Dev.to: login successful")
            await page.save_session()
        return page

    async def medium(self, email: str, password: str) -> HumanPage:
        """Login to Medium via Google or email link."""
        page = await self._browser.new_page("medium")
        await page.goto("https://medium.com")
        if await page.load_session():
            logger.info("[HumanBrowser] Medium: session restored")
            return page

        await page.goto("https://medium.com/m/signin")
        await page._random_pause("read")
        # Medium uses email magic link — click "sign in with email"
        try:
            await page.click("text=Sign in with email")
            await page._random_pause("action")
            await page.type_human("input[type='email']", email)
            await page.click("button[type='submit']")
            logger.info("[HumanBrowser] Medium: magic link sent to %s", email)
        except Exception as exc:
            logger.warning("[HumanBrowser] Medium login flow issue: %s", exc)
        return page

    async def hashnode(self, email: str, password: str) -> HumanPage:
        """Login to Hashnode."""
        page = await self._browser.new_page("hashnode")
        await page.goto("https://hashnode.com")
        if await page.load_session():
            logger.info("[HumanBrowser] Hashnode: session restored")
            return page

        await page.goto("https://hashnode.com/login")
        await page._random_pause("read")
        await page.type_human("input[name='username']", email)
        await page.type_human("input[name='password']", password)
        await page._random_pause("think")
        await page.click("button[type='submit']")
        await page._random_pause("navigate")

        if await page.wait_for_url("hashnode.com", timeout=15.0):
            logger.info("[HumanBrowser] Hashnode: login successful")
            await page.save_session()
        return page

    async def linkedin(self, email: str, password: str) -> HumanPage:
        """
        Login to LinkedIn.
        NOTE: LinkedIn has strong bot detection. Sessions are valuable — save them.
        Use sparingly (1-2 actions per session) to avoid triggering reviews.
        """
        page = await self._browser.new_page("linkedin")
        await page.goto("https://www.linkedin.com")
        if await page.load_session():
            await page.goto("https://www.linkedin.com/feed/")
            await asyncio.sleep(2)
            if "feed" in page.url or "linkedin.com" in page.url:
                logger.info("[HumanBrowser] LinkedIn: session restored")
                return page

        await page.goto("https://www.linkedin.com/login")
        await page._random_pause("read")
        await page.type_human("#username", email)
        await page.type_human("#password", password)
        await page._random_pause("think")
        await page.click("button[type='submit']")
        await page._random_pause("navigate")

        if await page.wait_for_url("linkedin.com/feed", timeout=20.0):
            logger.info("[HumanBrowser] LinkedIn: login successful")
            await page.save_session()
        else:
            logger.warning("[HumanBrowser] LinkedIn: may require CAPTCHA verification at %s", page.url)
        return page

    async def twitter(self, email: str, password: str, username: str = "") -> HumanPage:
        """
        Login to Twitter/X.
        NOTE: Twitter requires username in the flow. Pass username if you have one.
        """
        page = await self._browser.new_page("twitter")
        await page.goto("https://twitter.com")
        if await page.load_session():
            await page.goto("https://twitter.com/home")
            await asyncio.sleep(2)
            if "home" in page.url:
                logger.info("[HumanBrowser] Twitter: session restored")
                return page

        await page.goto("https://twitter.com/i/flow/login")
        await page._random_pause("read")

        # Step 1: email
        await page.type_human("input[autocomplete='username']", email)
        await page._random_pause("action")
        await page.click("text=Next")
        await page._random_pause("navigate")

        # Step 2: Twitter may ask for username if it detects unusual login
        try:
            username_input = await page.wait_for_selector("input[data-testid='ocfEnterTextTextInput']", timeout=4_000)
            if username_input and username:
                await page.type_human("input[data-testid='ocfEnterTextTextInput']", username)
                await page.click("text=Next")
                await page._random_pause("action")
        except Exception:
            pass

        # Step 3: password
        try:
            await page.type_human("input[name='password']", password)
            await page._random_pause("think")
            await page.click("[data-testid='LoginForm_Login_Button']")
            await page._random_pause("navigate")
        except Exception as exc:
            logger.warning("[HumanBrowser] Twitter password step: %s", exc)

        if await page.wait_for_url("twitter.com/home", timeout=20.0):
            logger.info("[HumanBrowser] Twitter: login successful")
            await page.save_session()
        else:
            logger.warning("[HumanBrowser] Twitter: may require 2FA or CAPTCHA at %s", page.url)
        return page

    async def reddit(self, email: str, password: str) -> HumanPage:
        """Login to Reddit using email/password."""
        page = await self._browser.new_page("reddit")
        await page.goto("https://www.reddit.com")
        if await page.load_session():
            await page.goto("https://www.reddit.com/")
            await asyncio.sleep(2)
            if "reddit.com" in page.url and "login" not in page.url:
                logger.info("[HumanBrowser] Reddit: session restored")
                return page

        await page.goto("https://www.reddit.com/login")
        await page._random_pause("read")
        try:
            await page.type_human("input[name='username']", email)
            await page.type_human("input[name='password']", password)
            await page._random_pause("think")
            await page.click("button[type='submit']")
            await page._random_pause("navigate")
        except Exception as exc:
            logger.warning("[HumanBrowser] Reddit login step: %s", exc)

        if await page.wait_for_url("reddit.com", timeout=20.0):
            logger.info("[HumanBrowser] Reddit: login successful")
            await page.save_session()
        else:
            logger.warning("[HumanBrowser] Reddit: login may have failed at %s", page.url)
        return page

    async def hackernews_show_hn(self, email: str, password: str, title: str, url: str, text: str = "") -> str:
        """
        Submit a 'Show HN:' post to Hacker News. Returns the post URL or empty string.
        HN is the best single source of tech early-adopter traffic.
        """
        page = await self._browser.new_page("hackernews")
        try:
            await page.goto("https://news.ycombinator.com")
            if await page.load_session():
                await page.goto("https://news.ycombinator.com")
                await asyncio.sleep(2)
                if "news.ycombinator.com" in page.url:
                    logger.info("[HumanBrowser] HN: session restored")
                    # Skip re-login
                else:
                    raise Exception("session expired")
            else:
                await page.goto("https://news.ycombinator.com/login")
                await page._random_pause("read")
                await page.type_human("input[name='acct']", email)
                await page.type_human("input[name='pw']", password)
                await page._random_pause("think")
                await page.click("input[type='submit'][value='login']")
                await page._random_pause("navigate")
                await page.save_session()

            # Navigate to submit page
            await page.goto("https://news.ycombinator.com/submit")
            await page._random_pause("read")

            hn_title = f"Show HN: {title}"[:80]
            await page.type_human("input[name='title']", hn_title)
            await asyncio.sleep(0.5)
            if url:
                await page.type_human("input[name='url']", url)
            elif text:
                await page.type_human("textarea[name='text']", text[:2000])
            await page._random_pause("think")
            await page.click("input[type='submit'][value='submit']")
            await page._random_pause("navigate")
            await asyncio.sleep(3)
            current = page.url
            if "item?id=" in current:
                logger.info("[HumanBrowser] HN submitted: %s", current)
                return current
            return ""
        except Exception as exc:
            logger.warning("[HumanBrowser] HN submission failed: %s", exc)
            return ""

    async def reddit_post(self, page: HumanPage, subreddit: str, title: str, body: str) -> str:
        """
        Submit a text post to a subreddit. Returns the post URL or empty string on failure.
        Must call reddit() first to get an authenticated page.
        """
        try:
            await page.goto(f"https://www.reddit.com/r/{subreddit}/submit?type=self")
            await page._random_pause("read")

            # Fill title
            title_selector = "textarea[name='title'], input[name='title'], #title-textarea"
            await page.type_human(title_selector, title[:300])
            await page._random_pause("action")

            # Fill body — Reddit uses a draft.js / prosemirror editor
            try:
                body_selector = "div[contenteditable='true'], .public-DraftEditor-content, div[role='textbox']"
                await page.click(body_selector)
                await page._random_pause("action")
                await page.type_human(body_selector, body[:5000])
            except Exception:
                # Fallback: try textarea for legacy editor
                try:
                    await page.type_human("textarea[name='text']", body[:5000])
                except Exception:
                    pass

            await page._random_pause("think")

            # Click submit
            await page.click("button[type='submit']:has-text('Post'), button:has-text('Submit')")
            await page._random_pause("navigate")

            await asyncio.sleep(3)
            url = page.url
            if f"r/{subreddit}/comments" in url:
                logger.info("[HumanBrowser] Reddit: posted to r/%s → %s", subreddit, url)
                return url
            return ""
        except Exception as exc:
            logger.warning("[HumanBrowser] Reddit post to r/%s failed: %s", subreddit, exc)
            return ""

    async def twitter_thread_post(self, page: HumanPage, tweets: list) -> str:
        """
        Post a thread of tweets on an authenticated Twitter/X page.
        Returns URL of the home feed after posting, or '' on failure.
        Must call twitter() first to get an authenticated page.
        """
        try:
            await page.goto("https://twitter.com/home")
            await page._random_pause("read")

            # Open compose dialog via the floating button
            for compose_sel in [
                "[data-testid='SideNav_NewTweet_Button']",
                "[aria-label='Post']",
                "[aria-label='Tweet']",
                "a[href='/compose/tweet']",
            ]:
                try:
                    await page.click(compose_sel)
                    break
                except Exception:
                    continue
            await page._random_pause("action")

            for i, tweet_text in enumerate(tweets[:10]):
                tweet_text = str(tweet_text)[:280]
                selector = f"[data-testid='tweetTextarea_{i}']"
                try:
                    await page.click(selector)
                except Exception:
                    # fallback selector for the active text area
                    await page.click("div[data-testid^='tweetTextarea']")
                await page._random_pause("action")
                await page.type_human(selector, tweet_text)
                await page._random_pause("think")

                if i < len(tweets) - 1:
                    # Add next tweet slot to thread
                    for add_sel in ["[data-testid='addButton']", "button[aria-label='Add']"]:
                        try:
                            await page.click(add_sel)
                            break
                        except Exception:
                            continue
                    await page._random_pause("action")

            # Post the full thread
            for post_sel in ["[data-testid='tweetButton']", "button[aria-label='Tweet all']"]:
                try:
                    await page.click(post_sel)
                    break
                except Exception:
                    continue

            await page._random_pause("navigate")
            await asyncio.sleep(4)
            logger.info("[HumanBrowser] Twitter: thread of %d tweets posted", len(tweets))
            await page.save_session()
            return "https://twitter.com/home"
        except Exception as exc:
            logger.warning("[HumanBrowser] Twitter thread_post failed: %s", exc)
            return ""

    async def linkedin_create_post(self, page: HumanPage, content: str) -> str:
        """
        Create a LinkedIn post on an authenticated page.
        Returns feed URL after posting, or '' on failure.
        Must call linkedin() first to get an authenticated page.
        """
        try:
            await page.goto("https://www.linkedin.com/feed/")
            await page._random_pause("read")

            # Open the post composer
            for btn_sel in [
                "[aria-label='Start a post']",
                "button.share-box-feed-entry__trigger",
                "button[class*='share-box']",
            ]:
                try:
                    await page.click(btn_sel)
                    break
                except Exception:
                    continue
            await page._random_pause("action")

            # Type content in the modal editor (LinkedIn uses contenteditable)
            editor_typed = False
            for sel in [
                "div.ql-editor",
                "div[contenteditable='true'][role='textbox']",
                "div[contenteditable='true']",
                ".editor-content div[contenteditable]",
            ]:
                try:
                    await page.click(sel)
                    await page._random_pause("action")
                    await page.type_human(sel, content[:3000])
                    editor_typed = True
                    break
                except Exception:
                    continue

            if not editor_typed:
                logger.warning("[HumanBrowser] LinkedIn: text editor not found")
                return ""

            await page._random_pause("think")

            # Click the Post button
            for post_sel in [
                "button.share-actions__primary-action",
                "button[aria-label='Post']",
                "button:has-text('Post')",
            ]:
                try:
                    await page.click(post_sel)
                    break
                except Exception:
                    continue

            await page._random_pause("navigate")
            await asyncio.sleep(4)
            logger.info("[HumanBrowser] LinkedIn: post created successfully")
            await page.save_session()
            return "https://www.linkedin.com/feed/"
        except Exception as exc:
            logger.warning("[HumanBrowser] LinkedIn create_post failed: %s", exc)
            return ""

    async def hashnode_publish_article(
        self,
        email: str,
        password: str,
        title: str,
        content_markdown: str,
        tags: list | None = None,
    ) -> str:
        """
        Publish an article to Hashnode via browser.
        Returns the published article URL or '' on failure.
        """
        page = await self._browser.new_page("hashnode")
        try:
            await page.goto("https://hashnode.com")
            if not await page.load_session():
                await page.goto("https://hashnode.com/login")
                await page._random_pause("read")
                await page.type_human("input[name='username']", email)
                await page.type_human("input[name='password']", password)
                await page._random_pause("think")
                await page.click("button[type='submit']")
                await page._random_pause("navigate")
                await page.save_session()

            # Navigate to new article
            await page.goto("https://hashnode.com/draft/new")
            await page._random_pause("read")

            # Fill title
            for title_sel in ["textarea[placeholder*='Title']", "div[role='textbox'][data-testid='title']", "input[placeholder*='Title']"]:
                try:
                    await page.click(title_sel)
                    await page._random_pause("action")
                    await page.type_human(title_sel, title[:150])
                    break
                except Exception:
                    continue
            await page._random_pause("action")

            # Fill content (Hashnode uses a rich text / markdown editor)
            for content_sel in [
                "div.ProseMirror",
                "div[contenteditable='true']",
                "div.cm-content",
                "textarea[placeholder*='content' i]",
            ]:
                try:
                    await page.click(content_sel)
                    await page._random_pause("action")
                    await page.type_human(content_sel, content_markdown[:5000])
                    break
                except Exception:
                    continue

            await page._random_pause("think")

            # Publish
            for pub_sel in [
                "button:has-text('Publish')",
                "button[aria-label='Publish']",
                "button:has-text('Submit')",
            ]:
                try:
                    await page.click(pub_sel)
                    break
                except Exception:
                    continue

            await page._random_pause("navigate")
            await asyncio.sleep(4)
            url = page.url
            if "hashnode.com" in url and ("draft" not in url or "published" in url):
                logger.info("[HumanBrowser] Hashnode: article published → %s", url)
                await page.save_session()
                return url
            return ""
        except Exception as exc:
            logger.warning("[HumanBrowser] Hashnode publish failed: %s", exc)
            return ""

    async def gumroad_create_product(
        self,
        page: HumanPage,
        name: str,
        price_cents: int,
        description: str,
    ) -> str:
        """
        Create a new Gumroad product via browser.
        Returns the product/edit URL on success, or '' on failure.
        Must call gumroad() first to get an authenticated page.
        """
        try:
            await page.goto("https://gumroad.com/products/new")
            await page._random_pause("read")

            # Product name
            for name_sel in [
                "input[name='name']",
                "input[placeholder*='name' i]",
                "input[placeholder*='Name' i]",
            ]:
                try:
                    await page.type_human(name_sel, name[:100])
                    break
                except Exception:
                    continue
            await page._random_pause("action")

            # Price (dollars)
            price_str = f"{price_cents / 100:.2f}"
            for price_sel in ["input[name='price']", "input[placeholder*='rice' i]"]:
                try:
                    await page.type_human(price_sel, price_str, clear_first=True)
                    break
                except Exception:
                    continue
            await page._random_pause("action")

            # Description / content
            for desc_sel in [
                "div.ProseMirror",
                "div[contenteditable='true']",
                "textarea[name='description']",
                ".editor-content",
            ]:
                try:
                    await page.click(desc_sel)
                    await page._random_pause("action")
                    await page.type_human(desc_sel, description[:2000])
                    break
                except Exception:
                    continue

            await page._random_pause("think")

            # Save / Create
            for save_sel in [
                "button:has-text('Save')",
                "button[type='submit']",
                "button:has-text('Create')",
                "button:has-text('Publish')",
            ]:
                try:
                    await page.click(save_sel)
                    break
                except Exception:
                    continue

            await page._random_pause("navigate")
            await asyncio.sleep(4)
            url = page.url
            if "gumroad.com/products" in url or "gumroad.com/l/" in url:
                logger.info("[HumanBrowser] Gumroad: product created → %s", url)
                await page.save_session()
                return url
            return ""
        except Exception as exc:
            logger.warning("[HumanBrowser] Gumroad create_product failed: %s", exc)
            return ""


# ── Singleton ─────────────────────────────────────────────────────────────────

_browser_instance: Optional[HumanBrowser] = None
_browser_lock = asyncio.Lock()


async def get_human_browser() -> HumanBrowser:
    """Get or create the shared HumanBrowser instance."""
    global _browser_instance
    async with _browser_lock:
        if _browser_instance is None or _browser_instance._browser is None:
            _browser_instance = HumanBrowser()
            await _browser_instance.start()
    return _browser_instance


async def get_platform_login() -> PlatformLogin:
    browser = await get_human_browser()
    return PlatformLogin(browser)
