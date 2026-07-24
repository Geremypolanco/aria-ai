"""Regression tests for three bugs found while auditing income_loop.py
(via a chunked multi-agent sweep of this 22k-line file):

1. _exec_social_blitz() (line ~2685) indexed ls.listing_urls[0] — but
   listing_urls is a dict keyed by platform name (e.g. "gumroad"), not a
   list. Indexing it with an int raised KeyError whenever it was non-empty
   — exactly the condition that put the listing into `live` in the first
   place — aborting the whole social_blitz strategy every time any real
   product listing existed.
2. _announce_product_on_blog() (line ~765) called
   hashnode_publish_article(..., content=body, ...) — but the real method
   signature (human_browser.py) takes `content_markdown`, not `content`.
   This raised TypeError on every call, silently swallowed by a bare
   except, so Hashnode announcements never actually published.
3. _exec_partner_outreach() (line ~7593) called
   plat.linkedin_post(page, text) — but HumanBrowser's real method is
   named linkedin_create_post (confirmed: every other LinkedIn-posting call
   site in this same file correctly uses linkedin_create_post). This raised
   AttributeError on every call, silently swallowed, so the LinkedIn
   browser-fallback for partner-outreach never posted anything.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.tools.income_loop import IncomeLoop
from apps.core.tools.niche_revenue_engine import ServiceListing

pytestmark = pytest.mark.asyncio


def _make_listing(listing_urls: dict) -> ServiceListing:
    return ServiceListing(
        niche_key="test-niche",
        title="Test Product",
        tagline="A great product",
        description="desc",
        deliverables=["thing"],
        pricing_tiers={"basic": {"price": 29, "desc": "basic tier"}},
        keywords=["kw"],
        target_audience="everyone",
        portfolio_samples=[],
        faq=[],
        turnaround_days=3,
        revision_policy="none",
        platforms=["gumroad"],
        category="digital",
        tags=["tag"],
        listing_urls=listing_urls,
    )


async def test_social_blitz_extracts_url_from_listing_urls_dict():
    loop = IncomeLoop.__new__(IncomeLoop)
    listing = _make_listing({"gumroad": "https://gumroad.com/l/xyz"})

    mock_engine = MagicMock()
    mock_engine._load_listings = AsyncMock(return_value=[listing])

    with patch(
        "apps.core.tools.niche_revenue_engine.get_niche_revenue_engine", return_value=mock_engine
    ), patch(
        "apps.distribution.publishers.api_publisher.get_api_publisher"
    ) as mock_pub, patch(
        "apps.core.tools.ai_client.get_ai_client", return_value=None
    ), patch(
        "apps.core.tools.zapier_connector.ZapierConnector"
    ) as mock_zap_cls, patch(
        "apps.core.tools.income_loop.settings"
    ) as mock_settings:
        mock_settings.ARIA_EMAIL = None
        mock_settings.ARIA_PASSWORD = None
        mock_settings.DISCORD_WEBHOOK_URL = None
        mock_pub.return_value.publish_to_twitter = AsyncMock(
            return_value=MagicMock(success=False)
        )
        mock_zap_cls.return_value.dispatch_event = AsyncMock()

        # Must not raise KeyError: 0 — the bug being regression-tested.
        result = await loop._exec_social_blitz()

    assert isinstance(result, dict)


async def test_hashnode_publish_article_call_site_matches_real_signature():
    """_announce_product_on_blog's call to hashnode_publish_article() must
    bind against the REAL method signature in human_browser.py — it used to
    pass content=body, but the real parameter is content_markdown."""
    import inspect
    import re

    from apps.core.tools.human_browser import PlatformLogin

    sig = inspect.signature(PlatformLogin.hashnode_publish_article)

    source = inspect.getsource(IncomeLoop._announce_product_on_blog)
    m = re.search(r"hashnode_publish_article\(\s*([^)]*)\)", source, re.DOTALL)
    assert m, "hashnode_publish_article call site not found"
    call_args = f"hashnode_publish_article({m.group(1)})"

    # Build a fake call using the exact argument text captured from the
    # source and bind it against the real signature (minus `self`).
    ns = {
        "hashnode_publish_article": lambda *a, **k: sig.bind(
            None, *a, **k
        ),  # None stands in for self
        "_dt_ae": "email",
        "_dt_ap": "pw",
        "title": "t",
        "body": "b",
        "tags": ["a", "b", "c"],
    }
    eval(call_args, ns)  # raises TypeError if kwargs don't match the real signature


async def test_partner_outreach_linkedin_call_site_matches_real_method_name():
    """_exec_partner_outreach's LinkedIn browser-fallback must call a method
    that actually exists on HumanBrowser — it used to call linkedin_post,
    which doesn't exist (the real method is linkedin_create_post)."""
    import inspect

    from apps.core.tools.human_browser import PlatformLogin

    source = inspect.getsource(IncomeLoop._exec_partner_outreach)
    assert "linkedin_post(" not in source
    assert "linkedin_create_post(" in source
    assert hasattr(PlatformLogin, "linkedin_create_post")
    assert not hasattr(PlatformLogin, "linkedin_post")
