"""Regression test: AffiliateTools.inject_affiliate_links() called
build_amazon_link("", tag) — an empty ASIN — producing a broken link
(https://www.amazon.com/dp/?tag=...) with no product path, since this
function only has content/topic strings and no real ASIN. Fixed to link to
an Amazon search results page for the topic instead, which is a real,
working, tag-attributed URL.
"""

from __future__ import annotations

from apps.core.tools.affiliate_tools import AffiliateTools


def test_inject_affiliate_links_produces_a_working_amazon_url(monkeypatch):
    monkeypatch.setattr(
        "apps.core.tools.affiliate_tools.settings.AMAZON_ASSOCIATE_TAG", "mytag-20"
    )

    tools = AffiliateTools()
    result = tools.inject_affiliate_links("Some article content", "wireless earbuds")

    assert result["success"] is True
    assert "/dp/?tag=" not in result["content"]
    assert "amazon.com/s?k=" in result["content"]
    assert "mytag-20" in result["content"]
