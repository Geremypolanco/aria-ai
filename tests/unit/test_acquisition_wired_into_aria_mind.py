"""Regression test: LeadScraper, LeadEngine (apps/acquisition/{scraper,leads}/)
and LinkedInOutreach (apps/acquisition/linkedin/) — complete implementations
with their own singleton getters — had zero live callers. Found via the same
full-repo dead-code audit as the Shopify Revenue Suite.

LeadEngine.discover_leads() was deliberately NOT wired: it invents placeholder
company names ("SaaS Business 1") without labeling them as synthetic, unlike
LeadScraper.scrape_leads(), which tags every lead's source as "duckduckgo" or
"synthetic" and whose synthetic-generator docstring explicitly disclaims that
these are archetypes, not real companies. Wiring the unlabeled version would
have ARIA present made-up company names to the user as if they were real,
contactable leads — the same fabricated-success/fabricated-data problem
flagged elsewhere this session. discover_leads (the chat tool) uses
LeadScraper; LeadEngine is only used for generate_proposal_brief, which
doesn't claim anything about lead provenance.

Wired into aria_mind.py's tool dispatcher as: discover_leads,
generate_sales_proposal, add_linkedin_prospect, score_linkedin_prospect,
generate_linkedin_connection_request, generate_linkedin_outreach_sequence,
linkedin_outreach_pipeline.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, not by calling the engines directly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.acquisition.linkedin.linkedin_outreach import LinkedInOutreach
from apps.acquisition.scraper.lead_scraper import RawLead, ScrapedBatch
from apps.core.cognition.aria_mind import AriaMind
from apps.core.tools.ai_client import AIProvider, AIResponse

pytestmark = pytest.mark.asyncio


class _FakeCache:
    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ttl_seconds=3600):
        self._store[key] = value
        return True


def _fake_ai_response(content: str) -> AIResponse:
    return AIResponse(content=content, provider=AIProvider.ANTHROPIC, model="fast", success=True)


async def test_discover_leads_labels_synthetic_vs_real():
    batch = ScrapedBatch(
        niche="fitness",
        leads_found=2,
        leads_qualified=2,
        sources_checked=["duckduckgo", "synthetic"],
        raw_leads=[
            RawLead(
                company_name="Real Gym Co",
                source="duckduckgo",
                signals=["weak SEO", "no automation"],
            ).to_dict(),
            RawLead(
                company_name="Peak Yoga Studio",
                source="synthetic",
                signals=["no online booking"],
            ).to_dict(),
        ],
    )
    with patch(
        "apps.acquisition.scraper.lead_scraper.get_lead_scraper",
        return_value=AsyncMock(scrape_leads=AsyncMock(return_value=batch)),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("discover_leads", {"niche": "fitness"})

    assert media == {}
    assert "Real Gym Co" in obs and "web search" in obs
    assert "Peak Yoga Studio" in obs and "illustrative example" in obs


async def test_discover_leads_requires_niche():
    mind = AriaMind()
    obs, media = await mind._execute_tool("discover_leads", {})

    assert media == {}
    assert "niche" in obs.lower()


async def test_generate_sales_proposal_reachable_from_tool_dispatch():
    fake_ai = AsyncMock()
    fake_ai.complete = AsyncMock(
        return_value=_fake_ai_response(
            "Quick question for Acme Yoga\n"
            "Noticed you're growing fast\n"
            "more content here that becomes the solution summary"
        )
    )
    with (
        patch("apps.acquisition.leads.lead_engine.get_cache", return_value=_FakeCache()),
        patch("apps.acquisition.leads.lead_engine.get_ai_client", return_value=fake_ai),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "generate_sales_proposal",
            {
                "company_name": "Acme Yoga",
                "niche": "fitness",
                "pain_points": ["weak SEO"],
                "services_needed": ["SEO"],
                "estimated_value_usd": 800,
            },
        )

    assert media == {}
    assert "Acme Yoga" in obs
    assert "Subject:" in obs and "CTA:" in obs


async def test_generate_sales_proposal_requires_company_name():
    mind = AriaMind()
    obs, media = await mind._execute_tool("generate_sales_proposal", {})

    assert media == {}
    assert "company" in obs.lower()


@pytest.fixture
def _linkedin_cache():
    with patch("apps.acquisition.linkedin.linkedin_outreach.get_cache", return_value=_FakeCache()):
        yield


async def test_add_linkedin_prospect_reachable_from_tool_dispatch(_linkedin_cache):
    outreach = LinkedInOutreach()
    with patch(
        "apps.acquisition.linkedin.linkedin_outreach.get_linkedin_outreach", return_value=outreach
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "add_linkedin_prospect",
            {"name": "Jane Doe", "title": "CEO", "company": "Acme Yoga", "industry": "fitness"},
        )

    assert media == {}
    assert "Jane Doe" in obs
    assert "Acme Yoga" in obs


async def test_add_linkedin_prospect_requires_name_and_company():
    mind = AriaMind()
    obs, media = await mind._execute_tool("add_linkedin_prospect", {"name": "Jane"})

    assert media == {}
    assert "company" in obs.lower()


async def test_score_linkedin_prospect_reachable_from_tool_dispatch(_linkedin_cache):
    outreach = LinkedInOutreach()
    fake_ai = AsyncMock()
    fake_ai.complete = AsyncMock(
        return_value=_fake_ai_response("Score: 0.8. Pain point: manual scheduling.")
    )
    with (
        patch(
            "apps.acquisition.linkedin.linkedin_outreach.get_linkedin_outreach",
            return_value=outreach,
        ),
        patch("apps.acquisition.linkedin.linkedin_outreach.get_ai_client", return_value=fake_ai),
    ):
        mind = AriaMind()
        prospect = await outreach.add_prospect("Jane Doe", "CEO", "Acme Yoga", "fitness")
        obs, media = await mind._execute_tool(
            "score_linkedin_prospect",
            {"prospect_id": prospect.prospect_id, "service_offered": "SEO automation"},
        )

    assert media == {}
    assert "Jane Doe" in obs
    assert "80%" in obs


async def test_generate_linkedin_connection_request_reachable_from_tool_dispatch(_linkedin_cache):
    outreach = LinkedInOutreach()
    fake_ai = AsyncMock()
    fake_ai.complete = AsyncMock(
        return_value=_fake_ai_response("Hi Jane, loved your work at Acme Yoga — let's connect!")
    )
    with (
        patch(
            "apps.acquisition.linkedin.linkedin_outreach.get_linkedin_outreach",
            return_value=outreach,
        ),
        patch("apps.acquisition.linkedin.linkedin_outreach.get_ai_client", return_value=fake_ai),
    ):
        mind = AriaMind()
        prospect = await outreach.add_prospect("Jane Doe", "CEO", "Acme Yoga", "fitness")
        obs, media = await mind._execute_tool(
            "generate_linkedin_connection_request",
            {"prospect_id": prospect.prospect_id, "service": "SEO automation"},
        )

    assert media == {}
    assert "Connection request" in obs


async def test_linkedin_outreach_pipeline_empty_state(_linkedin_cache):
    outreach = LinkedInOutreach()
    with patch(
        "apps.acquisition.linkedin.linkedin_outreach.get_linkedin_outreach", return_value=outreach
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("linkedin_outreach_pipeline", {})

    assert media == {}
    assert "no linkedin prospects" in obs.lower()


async def test_linkedin_outreach_pipeline_reachable_from_tool_dispatch(_linkedin_cache):
    outreach = LinkedInOutreach()
    with patch(
        "apps.acquisition.linkedin.linkedin_outreach.get_linkedin_outreach", return_value=outreach
    ):
        mind = AriaMind()
        prospect = await outreach.add_prospect("Jane Doe", "CEO", "Acme Yoga", "fitness")
        outreach._prospects[0]["relevance_score"] = 0.9
        obs, media = await mind._execute_tool("linkedin_outreach_pipeline", {"min_score": 0.5})

    assert media == {}
    assert "LinkedIn pipeline" in obs
    assert "Jane Doe" in obs
