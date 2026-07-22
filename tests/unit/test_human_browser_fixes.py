"""Regression tests for bugs found auditing human_browser.py.

Login-success checks across gumroad/devto/hashnode/reddit/linkedin/HN were
vacuous: they tested "domain in url" right after navigating to a page on
that same domain (e.g. the /login page itself), so the check was true
before the login attempt even happened. A genuinely failed/expired session
was reported as "restored"/"successful," and every downstream post/publish
call against it then silently failed. Fixed with a new wait_for_url_leaving()
helper that requires both being on the right domain AND having left the
specific login/compose page.

Also fixed: LinkedIn/Twitter post-success reported unconditionally with no
check that the Post button was ever actually clicked; Twitter's thread-typing
loop reused a failed selector instead of the fallback that actually
succeeded; Dev.to's publish check false-negatived on any URL containing
"new" as a substring (e.g. a username like dev.to/newbie123/...); Substack's
publish check false-positived on almost any non-editor URL; Hashnode's
tags parameter was accepted but never used; and a 4_000 (ms-style) timeout
was passed to a helper whose contract is seconds, turning a short optional
wait into a ~66-minute one.
"""

from __future__ import annotations

import asyncio
import inspect
import re

import pytest

from apps.core.tools.human_browser import HumanPage, PlatformLogin


class _FakeRawPage:
    def __init__(self, urls: list[str]):
        self._urls = list(urls)
        self.url = self._urls[0]

    def advance(self):
        if len(self._urls) > 1:
            self._urls.pop(0)
            self.url = self._urls[0]


@pytest.mark.asyncio
async def test_wait_for_url_leaving_true_only_after_leaving_the_page():
    raw = _FakeRawPage(["https://dev.to/enter", "https://dev.to/enter", "https://dev.to/"])
    page = HumanPage(raw, "test")

    async def fake_idle():
        raw.advance()

    page.idle_behavior = fake_idle  # type: ignore[method-assign]

    ok = await page.wait_for_url_leaving("dev.to", "/enter", timeout=5.0)
    assert ok is True
    assert "/enter" not in raw.url


@pytest.mark.asyncio
async def test_wait_for_url_leaving_times_out_if_never_leaving():
    raw = _FakeRawPage(["https://dev.to/enter"])
    page = HumanPage(raw, "test")
    page.idle_behavior = lambda: asyncio.sleep(0)  # type: ignore[method-assign]

    ok = await page.wait_for_url_leaving("dev.to", "/enter", timeout=1.0)
    assert ok is False


def test_twitter_login_timeout_is_in_seconds_not_milliseconds():
    """wait_for_selector's contract is seconds (it multiplies by 1000
    internally) — passing 4_000 meant a ~66-minute wait instead of 4s."""
    source = inspect.getsource(PlatformLogin.twitter)
    m = re.search(r"ocfEnterTextTextInput'\]\",\s*timeout=([\d._]+)", source)
    assert m, "timeout arg not found for the optional username step"
    assert float(m.group(1)) < 100, "timeout looks like milliseconds, not seconds"


def test_linkedin_create_post_tracks_whether_post_button_was_clicked():
    source = inspect.getsource(PlatformLogin.linkedin_create_post)
    assert "post_clicked" in source
    assert "if not post_clicked" in source


def test_twitter_thread_post_uses_the_selector_that_actually_succeeded():
    source = inspect.getsource(PlatformLogin.twitter_thread_post)
    # The fallback branch must reassign `selector` before typing into it.
    fallback_block = source[source.index("except Exception:") : source.index("await page.type_human(selector, tweet_text)")]
    assert "selector = " in fallback_block
    assert "post_clicked" in source


def test_devto_publish_check_does_not_false_negative_on_username_containing_new():
    source = inspect.getsource(PlatformLogin.devto_publish_article)
    assert '"new" not in url' not in source
    assert "urlparse" in source


def test_substack_publish_check_requires_real_published_url_pattern():
    source = inspect.getsource(PlatformLogin.substack_publish_post)
    assert 'or "/publish/post/" not in url' not in source
    assert 'if "substack.com/p/" in url:' in source


def test_hashnode_publish_article_actually_uses_tags_parameter():
    source = inspect.getsource(PlatformLogin.hashnode_publish_article)
    # Must reference tags somewhere in the body beyond the parameter list.
    body = source[source.index("Publish an article"):]
    assert "tags" in body and "for tag in tags" in body


def test_hackernews_restore_check_verifies_actual_auth_state():
    source = inspect.getsource(PlatformLogin.hackernews_show_hn)
    assert 'if "news.ycombinator.com" in page.url:' not in source
    assert "get_text" in source


def test_gumroad_and_linkedin_restore_checks_no_longer_vacuous():
    gumroad_src = inspect.getsource(PlatformLogin.gumroad)
    assert 'or "gumroad.com" in page.url' not in gumroad_src

    linkedin_src = inspect.getsource(PlatformLogin.linkedin)
    assert 'or "linkedin.com" in page.url' not in linkedin_src
