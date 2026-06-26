"""
ARIA Platform Self-Onboarder.

Uses ARIA_EMAIL + ARIA_PASSWORD (already in Fly.io secrets) to autonomously:
  1. Detect which platforms have missing API tokens
  2. Login (or register) on each platform using the browser automation engine
  3. Extract API tokens / access keys from account settings pages
  4. Store them in Redis for immediate use by all strategies
  5. Report newly acquired credentials via Telegram

Platforms supported:
  - HuggingFace   → User Access Token (read/write)
  - Dev.to        → API Key (from Settings > Account)
  - Gumroad       → Access Token (from Settings > Advanced)
  - Reddit        → marks as "manual PRAW setup needed" (OAuth is complex)
  - Mailchimp     → API Key (from Account > Extras > API Keys)

Security note: tokens are stored in Redis with TTL=30 days and in-memory,
never logged to stdout. The raw secrets are NEVER committed to git.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

from apps.core.config import settings

logger = logging.getLogger("aria.platform_onboarder")

# Redis keys for dynamically acquired tokens
_REDIS_PREFIX = "aria:dyntoken:"
_TOKEN_TTL = 86400 * 30  # 30 days

# In-memory cache so a restart doesn't lose tokens before Redis is warm
_mem_tokens: dict[str, str] = {}


@dataclass
class OnboardResult:
    platform: str
    success: bool
    token_acquired: bool = False
    token_key: str = ""  # e.g. "DEVTO_API_KEY"
    message: str = ""
    already_had_token: bool = False


@dataclass
class OnboardReport:
    results: list[OnboardResult] = field(default_factory=list)

    @property
    def new_tokens(self) -> list[OnboardResult]:
        return [r for r in self.results if r.token_acquired and not r.already_had_token]

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.success)


async def _store_token(key: str, value: str) -> None:
    """Persist a dynamically acquired token to Redis + in-memory cache."""
    _mem_tokens[key] = value
    try:
        from apps.core.memory.redis_client import get_cache

        cache = get_cache()
        if cache:
            await cache.set(f"{_REDIS_PREFIX}{key}", value, ttl_seconds=_TOKEN_TTL)
    except Exception as exc:
        logger.debug("[Onboarder] Redis store failed for %s: %s", key, exc)


async def get_dynamic_token(key: str) -> str | None:
    """
    Retrieve a dynamically acquired token.
    Checks in-memory first, then Redis, then falls back to settings attribute.
    """
    # 1. In-memory
    if key in _mem_tokens:
        return _mem_tokens[key]

    # 2. Redis
    try:
        from apps.core.memory.redis_client import get_cache

        cache = get_cache()
        if cache:
            val = await cache.get(f"{_REDIS_PREFIX}{key}")
            if val:
                _mem_tokens[key] = str(val)
                return str(val)
    except Exception:
        pass

    # 3. Settings (Fly.io secret already configured)
    env_val = getattr(settings, key, None)
    if env_val:
        return str(env_val)

    return None


def _has_token(attr: str) -> bool:
    """Check if a platform token is already configured in settings."""
    val = getattr(settings, attr, None)
    if val:
        return True
    return attr in _mem_tokens


class PlatformOnboarder:
    """
    Autonomous platform credential acquisition.
    Uses ARIA_EMAIL + ARIA_PASSWORD to login and extract tokens.
    """

    def __init__(self) -> None:
        self._email = getattr(settings, "ARIA_EMAIL", None) or getattr(settings, "EMAIL_FROM", None)
        self._password = getattr(settings, "ARIA_PASSWORD", None)

    def _can_automate(self) -> bool:
        return bool(self._email and self._password)

    async def onboard_all(self) -> OnboardReport:
        """
        Check all supported platforms and onboard those missing tokens.
        Returns a report of what was acquired.
        """
        report = OnboardReport()

        if not self._can_automate():
            logger.warning(
                "[Onboarder] ARIA_EMAIL or ARIA_PASSWORD not set — skipping browser automation"
            )
            return report

        platforms = [
            ("huggingface", "HUGGINGFACE_API_KEY", self._onboard_huggingface),
            ("devto", "DEVTO_API_KEY", self._onboard_devto),
            ("gumroad", "GUMROAD_ACCESS_TOKEN", self._onboard_gumroad),
            ("mailchimp", "MAILCHIMP_API_KEY", self._onboard_mailchimp),
        ]

        for platform, token_key, fn in platforms:
            if _has_token(token_key):
                result = OnboardResult(
                    platform=platform,
                    success=True,
                    token_acquired=True,
                    token_key=token_key,
                    message="already configured",
                    already_had_token=True,
                )
                report.results.append(result)
                logger.debug("[Onboarder] %s: already has %s", platform, token_key)
                continue

            logger.info("[Onboarder] %s: no token found — attempting self-onboard", platform)
            try:
                result = await asyncio.wait_for(fn(token_key), timeout=120)
            except TimeoutError:
                result = OnboardResult(
                    platform=platform,
                    success=False,
                    token_key=token_key,
                    message="timed out after 120s",
                )
            except Exception as exc:
                result = OnboardResult(
                    platform=platform,
                    success=False,
                    token_key=token_key,
                    message=str(exc)[:120],
                )

            report.results.append(result)
            if result.token_acquired:
                logger.info("[Onboarder] %s: NEW token acquired (%s)", platform, token_key)
            else:
                logger.warning("[Onboarder] %s: failed — %s", platform, result.message)

        return report

    async def _onboard_huggingface(self, token_key: str) -> OnboardResult:
        """
        Login to HuggingFace, navigate to Settings > Access Tokens,
        create a new write token and extract it.
        """
        try:
            from apps.core.tools.human_browser import get_platform_login

            plat = await get_platform_login()
            page = await plat._browser.new_page("huggingface")

            await page.goto("https://huggingface.co/login")
            await page._random_pause("read")

            # Fill login form
            await page.type_human("input[name='username']", self._email)
            await page.type_human("input[name='password']", self._password)
            await page._random_pause("think")
            await page.click("button[type='submit']")
            await page._random_pause("navigate")

            # Check if logged in
            await asyncio.sleep(3)
            if "huggingface.co" not in page.url:
                return OnboardResult(
                    platform="huggingface",
                    success=False,
                    token_key=token_key,
                    message="login failed — not on HF after submit",
                )

            # Navigate to token settings
            await page.goto("https://huggingface.co/settings/tokens/new")
            await asyncio.sleep(2)

            # Fill token name
            token_name = "aria-auto"
            name_sel = "input[placeholder*='name' i], input[name='tokenName'], input[id*='token']"
            try:
                await page.type_human(name_sel, token_name)
            except Exception:
                # Try generic text input
                await page.evaluate(
                    f"document.querySelector('input[type=\"text\"]').value = '{token_name}'"
                )

            # Select write scope if available
            with contextlib.suppress(Exception):
                await page.click("input[value='write'], label[for*='write']")

            await page._random_pause("think")

            # Submit
            await page.click("button[type='submit'], button[data-target*='create']")
            await asyncio.sleep(3)

            # Extract the token from the page
            page_text = await page.get_page_text(max_chars=3000)
            hf_token_match = re.search(r"hf_[A-Za-z0-9]{20,}", page_text)

            if hf_token_match:
                token = hf_token_match.group(0)
                await _store_token(token_key, token)
                await page.save_session()
                return OnboardResult(
                    platform="huggingface",
                    success=True,
                    token_acquired=True,
                    token_key=token_key,
                    message=f"token acquired: hf_***{token[-4:]}",
                )

            # Also try looking for the token in input fields
            try:
                token_val = await page.evaluate(
                    "document.querySelector('input[value^=\"hf_\"]')?.value || ''"
                )
                if token_val and token_val.startswith("hf_"):
                    await _store_token(token_key, token_val)
                    return OnboardResult(
                        platform="huggingface",
                        success=True,
                        token_acquired=True,
                        token_key=token_key,
                        message=f"token from input: hf_***{token_val[-4:]}",
                    )
            except Exception:
                pass

            return OnboardResult(
                platform="huggingface",
                success=False,
                token_key=token_key,
                message="logged in but could not extract token from page",
            )

        except Exception as exc:
            return OnboardResult(
                platform="huggingface",
                success=False,
                token_key=token_key,
                message=str(exc)[:120],
            )

    async def _onboard_devto(self, token_key: str) -> OnboardResult:
        """
        Login to Dev.to, go to Settings > Account > DEV Community API Keys,
        generate a new key and extract it.
        """
        try:
            from apps.core.tools.human_browser import get_platform_login

            plat = await get_platform_login()
            page = await plat.devto(self._email, self._password)

            # Navigate to API key settings
            await page.goto("https://dev.to/settings/extensions")
            await asyncio.sleep(2)

            # Find API key section and generate
            page_text = await page.get_page_text(max_chars=4000)

            # Try to generate new key if none visible
            try:
                await page.type_human(
                    "input[id*='api-key'], input[placeholder*='description']",
                    "aria-bot",
                )
                await page._random_pause("action")
                await page.click(
                    "button[data-action*='api-key'], button[class*='api'], input[type='submit']"
                )
                await asyncio.sleep(2)
                page_text = await page.get_page_text(max_chars=4000)
            except Exception:
                pass

            # Extract key — Dev.to keys are typically 64-char hex
            key_match = re.search(r"\b([a-f0-9]{60,70})\b", page_text)
            if not key_match:
                # Try input fields
                try:
                    key_val = await page.evaluate(
                        "Array.from(document.querySelectorAll('input[readonly], input[class*=\"key\"]'))"
                        ".map(el => el.value).find(v => v && v.length > 30) || ''"
                    )
                    if key_val and len(key_val) > 30:
                        await _store_token(token_key, key_val)
                        return OnboardResult(
                            platform="devto",
                            success=True,
                            token_acquired=True,
                            token_key=token_key,
                            message=f"API key from input: ***{key_val[-4:]}",
                        )
                except Exception:
                    pass

                return OnboardResult(
                    platform="devto",
                    success=False,
                    token_key=token_key,
                    message="logged in but could not find API key on settings page",
                )

            key = key_match.group(1)
            await _store_token(token_key, key)
            await page.save_session()
            return OnboardResult(
                platform="devto",
                success=True,
                token_acquired=True,
                token_key=token_key,
                message=f"API key acquired: ***{key[-4:]}",
            )

        except Exception as exc:
            return OnboardResult(
                platform="devto",
                success=False,
                token_key=token_key,
                message=str(exc)[:120],
            )

    async def _onboard_gumroad(self, token_key: str) -> OnboardResult:
        """
        Login to Gumroad, go to Settings > Advanced to get the access token.
        Gumroad shows the OAuth access token on the advanced settings page.
        """
        try:
            from apps.core.tools.human_browser import get_platform_login

            plat = await get_platform_login()
            page = await plat.gumroad(self._email, self._password)

            # Navigate to advanced settings where the access token lives
            await page.goto("https://app.gumroad.com/settings/advanced")
            await asyncio.sleep(2)

            # Try to extract token from page text
            # Gumroad access tokens look like: [a-zA-Z0-9_-]{20,60}
            # Try to find something that looks like a Gumroad token
            try:
                token_val = await page.evaluate(
                    "Array.from(document.querySelectorAll('input[readonly], input[type=\"text\"], code'))"
                    ".map(el => el.value || el.textContent).find(v => v && v.length > 20 && /^[a-zA-Z0-9_-]+$/.test(v.trim())) || ''"
                )
                if token_val and len(token_val.strip()) > 20:
                    clean = token_val.strip()
                    await _store_token(token_key, clean)
                    await page.save_session()
                    return OnboardResult(
                        platform="gumroad",
                        success=True,
                        token_acquired=True,
                        token_key=token_key,
                        message=f"access token: ***{clean[-4:]}",
                    )
            except Exception:
                pass

            # If no token visible, try the API with email/password to get OAuth token
            try:
                import httpx as _hx

                async with _hx.AsyncClient(timeout=15) as _hc:
                    r = await _hc.post(
                        "https://api.gumroad.com/oauth/token",
                        data={
                            "grant_type": "password",
                            "email": self._email,
                            "password": self._password,
                            "client_id": "gumroad",
                        },
                    )
                    if r.status_code == 200:
                        data = r.json()
                        token = data.get("access_token", "")
                        if token:
                            await _store_token(token_key, token)
                            return OnboardResult(
                                platform="gumroad",
                                success=True,
                                token_acquired=True,
                                token_key=token_key,
                                message=f"OAuth token via API: ***{token[-4:]}",
                            )
            except Exception:
                pass

            # Save session anyway so future logins are faster
            await page.save_session()
            return OnboardResult(
                platform="gumroad",
                success=True,
                token_acquired=False,
                token_key=token_key,
                message="logged in successfully — token not extractable from UI (use GUMROAD_ACCESS_TOKEN secret)",
            )

        except Exception as exc:
            return OnboardResult(
                platform="gumroad",
                success=False,
                token_key=token_key,
                message=str(exc)[:120],
            )

    async def _onboard_mailchimp(self, token_key: str) -> OnboardResult:
        """
        Login to Mailchimp, navigate to Account > Extras > API Keys,
        create a new key and extract it.
        """
        try:
            from apps.core.tools.human_browser import get_platform_login

            plat = await get_platform_login()
            page = await plat._browser.new_page("mailchimp")

            await page.goto("https://login.mailchimp.com/")
            await asyncio.sleep(1)

            # Check session
            if await page.load_session():
                await page.goto("https://us1.admin.mailchimp.com/account/api/")
                await asyncio.sleep(2)
            else:
                await page.type_human("input[name='username']", self._email)
                await page.type_human("input[name='password']", self._password)
                await page._random_pause("think")
                await page.click("button[type='submit'], #loginButton")
                await asyncio.sleep(4)

                # Navigate to API keys
                await page.goto("https://us1.admin.mailchimp.com/account/api/")
                await asyncio.sleep(2)

            # Create new API key
            try:
                await page.click("a[data-bind*='create'], button[class*='create'], #createKey")
                await asyncio.sleep(2)
            except Exception:
                pass

            # Extract the key
            page_text = await page.get_page_text(max_chars=4000)

            # Mailchimp API keys look like: [a-z0-9]{32}-us[0-9]+
            mc_match = re.search(r"[a-z0-9]{32}-us\d+", page_text)
            if mc_match:
                key = mc_match.group(0)
                await _store_token(token_key, key)
                await page.save_session()
                return OnboardResult(
                    platform="mailchimp",
                    success=True,
                    token_acquired=True,
                    token_key=token_key,
                    message=f"API key acquired: ***{key[-6:]}",
                )

            # Try input fields
            try:
                key_val = await page.evaluate(
                    "Array.from(document.querySelectorAll('input[readonly], td.copyable'))"
                    ".map(el => el.value || el.textContent).find(v => v && /-us\\d/.test(v)) || ''"
                )
                if key_val:
                    clean = key_val.strip()
                    await _store_token(token_key, clean)
                    return OnboardResult(
                        platform="mailchimp",
                        success=True,
                        token_acquired=True,
                        token_key=token_key,
                        message=f"API key from input: ***{clean[-6:]}",
                    )
            except Exception:
                pass

            return OnboardResult(
                platform="mailchimp",
                success=False,
                token_key=token_key,
                message="logged in but could not find/create API key",
            )

        except Exception as exc:
            return OnboardResult(
                platform="mailchimp",
                success=False,
                token_key=token_key,
                message=str(exc)[:120],
            )


# ── Income Loop Strategy Helper ───────────────────────────────────────────────


async def run_self_onboard_strategy() -> dict:
    """
    Called by income_loop._exec_platform_self_onboard().
    Returns the standard income loop result dict.
    """
    onboarder = PlatformOnboarder()

    if not onboarder._can_automate():
        return {
            "success": False,
            "summary": "ARIA_EMAIL or ARIA_PASSWORD not configured — cannot self-onboard",
            "revenue_potential": 0.0,
            "urls": [],
        }

    report = await onboarder.onboard_all()
    new_tokens = report.new_tokens
    total_platforms = len(report.results)
    already_had = sum(1 for r in report.results if r.already_had_token)

    # Build summary
    if new_tokens:
        new_list = ", ".join([f"{r.platform}({r.token_key})" for r in new_tokens])
        summary = (
            f"Self-onboard: {len(new_tokens)} new tokens acquired [{new_list}] | "
            f"{already_had}/{total_platforms} already configured"
        )
    else:
        summary = (
            f"Self-onboard: no new tokens — {already_had}/{total_platforms} already configured. "
            f"Check logs for details."
        )

    # Telegram notification if new tokens acquired
    if new_tokens:
        try:
            from apps.core.tools.telegram_bot import get_bot

            lines = ["🔑 <b>ARIA SELF-ONBOARD</b>\n"]
            for r in new_tokens:
                lines.append(f"  ✅ <b>{r.platform}</b>: {r.message}")
            if already_had:
                lines.append(f"\n  ℹ️ {already_had} platforms already configured")
            lines.append("\n<i>Tokens stored in Redis — active for all strategies immediately.</i>")
            await get_bot().notify_owner("\n".join(lines), already_html=True)
        except Exception:
            pass

    # Revenue potential: each new token unlocks a revenue channel
    # Conservative: each new platform is worth $50/mo in revenue potential
    revenue = len(new_tokens) * 50.0

    return {
        "success": bool(new_tokens or already_had > 0),
        "summary": summary,
        "revenue_potential": revenue,
        "urls": [],
    }


# ── Contextlib import for the suppress pattern ────────────────────────────────
import contextlib  # noqa: E402
