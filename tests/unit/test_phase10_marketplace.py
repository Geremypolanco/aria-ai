"""
Phase 10 tests — Marketplace + Client Acquisition Layer.

Covers:
  - ClientAcquisition: add_lead, score_lead, generate_outreach,
    generate_follow_up_sequence, qualify_lead, update_lead_status,
    hot_leads, pipeline_report, leads_by_platform
  - ProposalEngine: generate_proposal, generate_fiverr_gig,
    generate_upwork_profile, price_service, update_proposal_status,
    proposal_analytics, recent_proposals
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Shared mock helpers ────────────────────────────────────────────────────────

def _mock_cache():
    """In-memory cache mock — get returns None, set returns True."""
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content: str = "ROI analysis: Double down on content marketing. Best ROI: 320%"):
    """Sync AI client mock whose .complete() is async."""
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


def _mock_ai_failed():
    """AI client mock that always returns a failed response."""
    ai = MagicMock()
    r = MagicMock()
    r.success = False
    r.content = ""
    ai.complete = AsyncMock(return_value=r)
    return ai


# ══════════════════════════════════════════════════════════════════════════════
# 1. ClientAcquisition
# ══════════════════════════════════════════════════════════════════════════════

class TestClientAcquisition:
    """15+ tests for ClientAcquisition."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.marketplace.client_acquisition as m
        m._instance = None
        yield
        m._instance = None

    @pytest.mark.asyncio
    async def test_add_lead_returns_lead_with_id(self):
        """add_lead returns a Lead with a valid ID."""
        from apps.marketplace.client_acquisition import ClientAcquisition, Lead

        cache = _mock_cache()
        with patch("apps.marketplace.client_acquisition.get_cache", return_value=cache):
            ca = ClientAcquisition()
            lead = await ca.add_lead(
                name="Alice Smith",
                company="Acme Corp",
                email="alice@acme.com",
                platform="upwork",
                niche="e-commerce",
                pain_points=["low conversion", "poor SEO"],
                budget=2000.0,
            )

        assert isinstance(lead, Lead)
        assert lead.lead_id is not None
        assert len(lead.lead_id) > 0
        assert lead.name == "Alice Smith"
        assert lead.company == "Acme Corp"
        assert lead.email == "alice@acme.com"
        assert lead.platform == "upwork"
        assert lead.status == "new"

    @pytest.mark.asyncio
    async def test_add_lead_persists_to_internal_list(self):
        """add_lead appends to internal _leads list."""
        from apps.marketplace.client_acquisition import ClientAcquisition

        cache = _mock_cache()
        with patch("apps.marketplace.client_acquisition.get_cache", return_value=cache):
            ca = ClientAcquisition()
            await ca.add_lead("Bob", "BobCo", "bob@bob.com", "fiverr", "design")
            await ca.add_lead("Carol", "CarolInc", "carol@c.com", "linkedin", "SaaS")

        assert len(ca._leads) == 2

    @pytest.mark.asyncio
    async def test_add_lead_budget_is_float(self):
        """add_lead stores budget as float."""
        from apps.marketplace.client_acquisition import ClientAcquisition

        cache = _mock_cache()
        with patch("apps.marketplace.client_acquisition.get_cache", return_value=cache):
            ca = ClientAcquisition()
            lead = await ca.add_lead("Test", "TestCo", "t@t.com", "email", "tech", budget=1500.0)

        assert isinstance(lead.budget_estimate_usd, float)
        assert lead.budget_estimate_usd == 1500.0

    @pytest.mark.asyncio
    async def test_score_lead_returns_lead_with_score(self):
        """score_lead returns Lead with lead_score in [0, 1]."""
        from apps.marketplace.client_acquisition import ClientAcquisition, Lead

        cache = _mock_cache()
        ai = _mock_ai(content="0.85")

        with patch("apps.marketplace.client_acquisition.get_cache", return_value=cache), \
             patch("apps.marketplace.client_acquisition.get_ai_client", return_value=ai):
            ca = ClientAcquisition()
            lead = await ca.add_lead(
                "Dave", "DaveCo", "d@d.com", "upwork", "marketing",
                pain_points=["no leads", "bad funnel", "low revenue"],
                budget=5000.0,
            )
            scored = await ca.score_lead(lead.lead_id)

        assert isinstance(scored, Lead)
        assert 0.0 <= scored.lead_score <= 1.0

    @pytest.mark.asyncio
    async def test_score_lead_updates_internal_storage(self):
        """score_lead updates lead_score in internal _leads list."""
        from apps.marketplace.client_acquisition import ClientAcquisition

        cache = _mock_cache()
        ai = _mock_ai(content="0.9")

        with patch("apps.marketplace.client_acquisition.get_cache", return_value=cache), \
             patch("apps.marketplace.client_acquisition.get_ai_client", return_value=ai):
            ca = ClientAcquisition()
            lead = await ca.add_lead("Eve", "EveCo", "e@e.com", "fiverr", "art")
            await ca.score_lead(lead.lead_id)

        # Find the updated record
        stored = next((l for l in ca._leads if l["lead_id"] == lead.lead_id), None)
        assert stored is not None
        assert stored["lead_score"] > 0.0

    @pytest.mark.asyncio
    async def test_generate_outreach_returns_message(self):
        """generate_outreach returns an OutreachMessage with content."""
        from apps.marketplace.client_acquisition import ClientAcquisition, OutreachMessage

        ai_content = '{"subject": "AI Solutions for your e-commerce", "body": "Hi Frank, I can help with your conversion issues."}'
        cache = _mock_cache()
        ai = _mock_ai(content=ai_content)

        with patch("apps.marketplace.client_acquisition.get_cache", return_value=cache), \
             patch("apps.marketplace.client_acquisition.get_ai_client", return_value=ai):
            ca = ClientAcquisition()
            lead = await ca.add_lead(
                "Frank", "FrankCo", "f@f.com", "upwork", "e-commerce",
                pain_points=["low conversion rates"]
            )
            msg = await ca.generate_outreach(lead.lead_id, "AI-powered CRO")

        assert isinstance(msg, OutreachMessage)
        assert msg.message_id is not None
        assert msg.lead_id == lead.lead_id
        assert len(msg.subject) > 0
        assert len(msg.body) > 0
        assert msg.follow_up_day == 0

    @pytest.mark.asyncio
    async def test_generate_outreach_fallback_on_ai_failure(self):
        """generate_outreach falls back to default message when AI fails."""
        from apps.marketplace.client_acquisition import ClientAcquisition, OutreachMessage

        cache = _mock_cache()
        ai = _mock_ai_failed()

        with patch("apps.marketplace.client_acquisition.get_cache", return_value=cache), \
             patch("apps.marketplace.client_acquisition.get_ai_client", return_value=ai):
            ca = ClientAcquisition()
            lead = await ca.add_lead("Grace", "GraceCo", "g@g.com", "email", "SaaS")
            msg = await ca.generate_outreach(lead.lead_id, "automation")

        assert isinstance(msg, OutreachMessage)
        assert len(msg.body) > 0

    @pytest.mark.asyncio
    async def test_generate_follow_up_sequence_returns_three_messages(self):
        """generate_follow_up_sequence returns exactly 3 messages."""
        from apps.marketplace.client_acquisition import ClientAcquisition, OutreachMessage

        ai_content = '{"subject": "Follow up", "body": "Hi, checking in!"}'
        cache = _mock_cache()
        ai = _mock_ai(content=ai_content)

        with patch("apps.marketplace.client_acquisition.get_cache", return_value=cache), \
             patch("apps.marketplace.client_acquisition.get_ai_client", return_value=ai):
            ca = ClientAcquisition()
            lead = await ca.add_lead("Henry", "HenryCo", "h@h.com", "linkedin", "B2B")
            sequence = await ca.generate_follow_up_sequence(lead.lead_id, "lead generation")

        assert len(sequence) == 3
        assert all(isinstance(m, OutreachMessage) for m in sequence)

    @pytest.mark.asyncio
    async def test_follow_up_sequence_has_correct_days(self):
        """follow_up_sequence has messages with days 0, 3, and 7."""
        from apps.marketplace.client_acquisition import ClientAcquisition

        ai_content = '{"subject": "Msg", "body": "Body"}'
        cache = _mock_cache()
        ai = _mock_ai(content=ai_content)

        with patch("apps.marketplace.client_acquisition.get_cache", return_value=cache), \
             patch("apps.marketplace.client_acquisition.get_ai_client", return_value=ai):
            ca = ClientAcquisition()
            lead = await ca.add_lead("Ivy", "IvyCo", "i@i.com", "email", "coaching")
            sequence = await ca.generate_follow_up_sequence(lead.lead_id, "coaching services")

        days = sorted([m.follow_up_day for m in sequence])
        assert days == [0, 3, 7]

    @pytest.mark.asyncio
    async def test_qualify_lead_returns_dict_with_required_keys(self):
        """qualify_lead returns dict with qualified, reason, recommended_service, estimated_value_usd."""
        from apps.marketplace.client_acquisition import ClientAcquisition

        ai_content = '{"qualified": true, "reason": "High budget and clear requirements", "recommended_service": "AI automation", "estimated_value_usd": 3000.0}'
        cache = _mock_cache()
        ai = _mock_ai(content=ai_content)

        with patch("apps.marketplace.client_acquisition.get_cache", return_value=cache), \
             patch("apps.marketplace.client_acquisition.get_ai_client", return_value=ai):
            ca = ClientAcquisition()
            lead = await ca.add_lead("Jack", "JackCo", "j@j.com", "upwork", "fintech", budget=5000.0)
            result = await ca.qualify_lead(lead.lead_id, "Client needs full AI integration, has $5k budget, decision maker on call")

        assert isinstance(result, dict)
        assert "qualified" in result
        assert "reason" in result
        assert "recommended_service" in result
        assert "estimated_value_usd" in result
        assert isinstance(result["qualified"], bool)
        assert isinstance(result["estimated_value_usd"], float)

    @pytest.mark.asyncio
    async def test_qualify_lead_fallback_on_ai_failure(self):
        """qualify_lead uses heuristic fallback when AI fails."""
        from apps.marketplace.client_acquisition import ClientAcquisition

        cache = _mock_cache()
        ai = _mock_ai_failed()

        with patch("apps.marketplace.client_acquisition.get_cache", return_value=cache), \
             patch("apps.marketplace.client_acquisition.get_ai_client", return_value=ai):
            ca = ClientAcquisition()
            lead = await ca.add_lead("Karen", "KarenCo", "k@k.com", "email", "retail", budget=1000.0)
            result = await ca.qualify_lead(lead.lead_id, "Strong interest, has budget approved by CFO")

        assert "qualified" in result
        # Budget >= 500 and notes > 20 chars → should qualify
        assert result["qualified"] is True

    def test_update_lead_status_valid_status(self):
        """update_lead_status returns True for valid status transitions."""
        from apps.marketplace.client_acquisition import ClientAcquisition

        ca = ClientAcquisition()
        ca._loaded = True
        ca._leads = [
            {"lead_id": "abc123", "name": "Test", "status": "new", "last_contact_at": 0.0}
        ]

        result = ca.update_lead_status("abc123", "contacted")

        assert result is True
        assert ca._leads[0]["status"] == "contacted"

    def test_update_lead_status_invalid_status(self):
        """update_lead_status returns False for invalid status."""
        from apps.marketplace.client_acquisition import ClientAcquisition

        ca = ClientAcquisition()
        ca._loaded = True
        ca._leads = [{"lead_id": "abc123", "status": "new", "last_contact_at": 0.0}]

        result = ca.update_lead_status("abc123", "invalid_status")

        assert result is False

    def test_hot_leads_filters_by_score(self):
        """hot_leads returns only leads with score >= min_score."""
        from apps.marketplace.client_acquisition import ClientAcquisition

        ca = ClientAcquisition()
        ca._loaded = True
        ca._leads = [
            {"lead_id": "a", "lead_score": 0.9, "status": "new"},
            {"lead_id": "b", "lead_score": 0.5, "status": "new"},
            {"lead_id": "c", "lead_score": 0.8, "status": "contacted"},
        ]

        hot = ca.hot_leads(min_score=0.7)

        assert len(hot) == 2
        scores = [l["lead_score"] for l in hot]
        assert all(s >= 0.7 for s in scores)

    def test_pipeline_report_has_required_keys(self):
        """pipeline_report returns all required keys."""
        from apps.marketplace.client_acquisition import ClientAcquisition

        ca = ClientAcquisition()
        ca._loaded = True
        ca._leads = [
            {"lead_id": "a", "status": "new", "platform": "upwork", "lead_score": 0.8, "budget_estimate_usd": 1000.0},
            {"lead_id": "b", "status": "contacted", "platform": "fiverr", "lead_score": 0.6, "budget_estimate_usd": 500.0},
        ]

        report = ca.pipeline_report()

        assert "total_leads" in report
        assert "by_status" in report
        assert "by_platform" in report
        assert "pipeline_value_usd" in report
        assert "avg_lead_score" in report
        assert report["total_leads"] == 2

    def test_pipeline_report_pipeline_value_calculation(self):
        """pipeline_value_usd = sum of budget * lead_score."""
        from apps.marketplace.client_acquisition import ClientAcquisition

        ca = ClientAcquisition()
        ca._loaded = True
        ca._leads = [
            {"lead_id": "a", "status": "new", "platform": "upwork", "lead_score": 0.8, "budget_estimate_usd": 1000.0},
            {"lead_id": "b", "status": "new", "platform": "fiverr", "lead_score": 0.5, "budget_estimate_usd": 2000.0},
        ]

        report = ca.pipeline_report()

        # 1000*0.8 + 2000*0.5 = 800 + 1000 = 1800
        assert report["pipeline_value_usd"] == pytest.approx(1800.0, rel=0.01)

    def test_leads_by_platform_groups_correctly(self):
        """leads_by_platform groups leads by platform."""
        from apps.marketplace.client_acquisition import ClientAcquisition

        ca = ClientAcquisition()
        ca._loaded = True
        ca._leads = [
            {"lead_id": "a", "platform": "upwork"},
            {"lead_id": "b", "platform": "fiverr"},
            {"lead_id": "c", "platform": "upwork"},
        ]

        result = ca.leads_by_platform()

        assert "upwork" in result
        assert "fiverr" in result
        assert len(result["upwork"]) == 2
        assert len(result["fiverr"]) == 1


# ══════════════════════════════════════════════════════════════════════════════
# 2. ProposalEngine
# ══════════════════════════════════════════════════════════════════════════════

class TestProposalEngine:
    """10+ tests for ProposalEngine."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.marketplace.proposal_engine as m
        m._instance = None
        yield
        m._instance = None

    @pytest.mark.asyncio
    async def test_generate_proposal_returns_proposal(self):
        """generate_proposal returns a Proposal with all required fields."""
        from apps.marketplace.proposal_engine import ProposalEngine, Proposal

        ai_content = '{"title": "AI Integration Proposal", "executive_summary": "We will integrate AI into your workflow.", "scope_of_work": ["Setup", "Integration", "Testing"], "timeline_days": 21, "price_usd": 3000.0, "payment_terms": "50/50", "why_us": "Expert team", "next_steps": ["Schedule call", "Sign contract"]}'
        cache = _mock_cache()
        ai = _mock_ai(content=ai_content)

        with patch("apps.marketplace.proposal_engine.get_cache", return_value=cache), \
             patch("apps.marketplace.proposal_engine.get_ai_client", return_value=ai):
            pe = ProposalEngine()
            proposal = await pe.generate_proposal(
                lead_id="lead123",
                service_type="AI Integration",
                client_requirements={"systems": ["CRM", "ERP"], "timeline": "1 month"},
                budget_usd=3000.0,
            )

        assert isinstance(proposal, Proposal)
        assert proposal.proposal_id is not None
        assert len(proposal.proposal_id) > 0
        assert proposal.lead_id == "lead123"
        assert proposal.status == "draft"

    @pytest.mark.asyncio
    async def test_generate_proposal_has_scope_of_work(self):
        """generate_proposal includes scope_of_work as a list."""
        from apps.marketplace.proposal_engine import ProposalEngine

        ai_content = '{"title": "Test", "executive_summary": "Summary", "scope_of_work": ["Phase 1", "Phase 2"], "timeline_days": 14, "price_usd": 1000.0, "payment_terms": "Net 30", "why_us": "Best", "next_steps": ["Call"]}'
        cache = _mock_cache()
        ai = _mock_ai(content=ai_content)

        with patch("apps.marketplace.proposal_engine.get_cache", return_value=cache), \
             patch("apps.marketplace.proposal_engine.get_ai_client", return_value=ai):
            pe = ProposalEngine()
            proposal = await pe.generate_proposal("l1", "Dev", {}, 1000.0)

        assert isinstance(proposal.scope_of_work, list)
        assert len(proposal.scope_of_work) > 0

    @pytest.mark.asyncio
    async def test_generate_proposal_fallback_on_ai_failure(self):
        """generate_proposal uses default values when AI fails."""
        from apps.marketplace.proposal_engine import ProposalEngine, Proposal

        cache = _mock_cache()
        ai = _mock_ai_failed()

        with patch("apps.marketplace.proposal_engine.get_cache", return_value=cache), \
             patch("apps.marketplace.proposal_engine.get_ai_client", return_value=ai):
            pe = ProposalEngine()
            proposal = await pe.generate_proposal("l2", "Consulting", {}, 500.0)

        assert isinstance(proposal, Proposal)
        assert proposal.price_usd == 500.0  # Falls back to budget_usd

    @pytest.mark.asyncio
    async def test_generate_fiverr_gig_returns_required_keys(self):
        """generate_fiverr_gig returns dict with title, description, packages, tags."""
        from apps.marketplace.proposal_engine import ProposalEngine

        ai_content = '{"title": "Professional AI Chatbot for E-commerce", "description": "Build a smart chatbot for your store.", "packages": {"basic": {"price_usd": 50, "delivery_days": 3, "description": "Basic bot"}, "standard": {"price_usd": 150, "delivery_days": 7, "description": "Pro bot"}, "premium": {"price_usd": 500, "delivery_days": 14, "description": "Enterprise bot"}}, "tags": ["chatbot", "ai", "ecommerce", "automation", "bot"]}'
        cache = _mock_cache()
        ai = _mock_ai(content=ai_content)

        with patch("apps.marketplace.proposal_engine.get_cache", return_value=cache), \
             patch("apps.marketplace.proposal_engine.get_ai_client", return_value=ai):
            pe = ProposalEngine()
            gig = await pe.generate_fiverr_gig("AI Chatbot", "e-commerce")

        assert "title" in gig
        assert "description" in gig
        assert "packages" in gig
        assert "tags" in gig
        assert isinstance(gig["tags"], list)
        assert len(gig["tags"]) > 0

    @pytest.mark.asyncio
    async def test_generate_fiverr_gig_has_three_packages(self):
        """generate_fiverr_gig includes basic, standard, premium packages."""
        from apps.marketplace.proposal_engine import ProposalEngine

        ai_content = '{"title": "Gig", "description": "Desc", "packages": {"basic": {"price_usd": 25, "delivery_days": 3, "description": "B"}, "standard": {"price_usd": 75, "delivery_days": 7, "description": "S"}, "premium": {"price_usd": 200, "delivery_days": 14, "description": "P"}}, "tags": ["a", "b", "c", "d", "e"]}'
        cache = _mock_cache()
        ai = _mock_ai(content=ai_content)

        with patch("apps.marketplace.proposal_engine.get_cache", return_value=cache), \
             patch("apps.marketplace.proposal_engine.get_ai_client", return_value=ai):
            pe = ProposalEngine()
            gig = await pe.generate_fiverr_gig("SEO", "blogs")

        packages = gig.get("packages", {})
        assert "basic" in packages
        assert "standard" in packages
        assert "premium" in packages

    @pytest.mark.asyncio
    async def test_generate_upwork_profile_returns_required_keys(self):
        """generate_upwork_profile returns title, overview, and skills list."""
        from apps.marketplace.proposal_engine import ProposalEngine

        ai_content = '{"title": "Senior AI Engineer | Python | ML", "overview": "I am an expert AI engineer with 5+ years experience building production ML systems.", "skills": ["Python", "Machine Learning", "PyTorch", "FastAPI"]}'
        cache = _mock_cache()
        ai = _mock_ai(content=ai_content)

        with patch("apps.marketplace.proposal_engine.get_cache", return_value=cache), \
             patch("apps.marketplace.proposal_engine.get_ai_client", return_value=ai):
            pe = ProposalEngine()
            profile = await pe.generate_upwork_profile(
                skills=["Python", "ML", "PyTorch"],
                specialization="AI Engineering",
            )

        assert "title" in profile
        assert "overview" in profile
        assert "skills" in profile
        assert isinstance(profile["skills"], list)

    @pytest.mark.asyncio
    async def test_price_service_returns_pricing_dict(self):
        """price_service returns dict with price_usd, rationale, competitor_range, positioning."""
        from apps.marketplace.proposal_engine import ProposalEngine

        ai_content = '{"price_usd": 750.0, "rationale": "Medium complexity AI work typically runs $600-900.", "competitor_range": "$500-$1200", "positioning": "competitive"}'
        cache = _mock_cache()
        ai = _mock_ai(content=ai_content)

        with patch("apps.marketplace.proposal_engine.get_cache", return_value=cache), \
             patch("apps.marketplace.proposal_engine.get_ai_client", return_value=ai):
            pe = ProposalEngine()
            pricing = await pe.price_service("AI Chatbot Development", "medium")

        assert "price_usd" in pricing
        assert "rationale" in pricing
        assert "competitor_range" in pricing
        assert "positioning" in pricing
        assert isinstance(pricing["price_usd"], float)
        assert pricing["price_usd"] >= 0.0

    @pytest.mark.asyncio
    async def test_price_service_fallback_on_ai_failure(self):
        """price_service returns reasonable defaults when AI fails."""
        from apps.marketplace.proposal_engine import ProposalEngine

        cache = _mock_cache()
        ai = _mock_ai_failed()

        with patch("apps.marketplace.proposal_engine.get_cache", return_value=cache), \
             patch("apps.marketplace.proposal_engine.get_ai_client", return_value=ai):
            pe = ProposalEngine()
            pricing = await pe.price_service("Consulting", "high")

        assert "price_usd" in pricing
        assert pricing["price_usd"] >= 0.0

    def test_update_proposal_status_valid(self):
        """update_proposal_status returns True for valid status."""
        from apps.marketplace.proposal_engine import ProposalEngine

        pe = ProposalEngine()
        pe._loaded = True
        pe._proposals = [
            {"proposal_id": "p1", "status": "draft", "price_usd": 1000.0}
        ]

        result = pe.update_proposal_status("p1", "sent")

        assert result is True
        assert pe._proposals[0]["status"] == "sent"

    def test_update_proposal_status_invalid_returns_false(self):
        """update_proposal_status returns False for invalid status."""
        from apps.marketplace.proposal_engine import ProposalEngine

        pe = ProposalEngine()
        pe._loaded = True
        pe._proposals = [{"proposal_id": "p1", "status": "draft"}]

        result = pe.update_proposal_status("p1", "invalid_status")

        assert result is False

    def test_proposal_analytics_complete_structure(self):
        """proposal_analytics returns all required keys."""
        from apps.marketplace.proposal_engine import ProposalEngine

        pe = ProposalEngine()
        pe._loaded = True
        pe._proposals = [
            {"proposal_id": "p1", "status": "sent", "price_usd": 1000.0, "created_at": time.time()},
            {"proposal_id": "p2", "status": "accepted", "price_usd": 2000.0, "created_at": time.time()},
            {"proposal_id": "p3", "status": "rejected", "price_usd": 500.0, "created_at": time.time()},
        ]

        analytics = pe.proposal_analytics()

        assert "total_proposals" in analytics
        assert "by_status" in analytics
        assert "avg_price_usd" in analytics
        assert "win_rate_pct" in analytics
        assert "total_pipeline_value" in analytics
        assert analytics["total_proposals"] == 3

    def test_proposal_analytics_avg_price(self):
        """proposal_analytics calculates avg_price_usd correctly."""
        from apps.marketplace.proposal_engine import ProposalEngine

        pe = ProposalEngine()
        pe._loaded = True
        pe._proposals = [
            {"proposal_id": "p1", "status": "draft", "price_usd": 1000.0, "created_at": time.time()},
            {"proposal_id": "p2", "status": "draft", "price_usd": 2000.0, "created_at": time.time()},
        ]

        analytics = pe.proposal_analytics()

        assert analytics["avg_price_usd"] == pytest.approx(1500.0, rel=0.01)

    def test_proposal_analytics_empty(self):
        """proposal_analytics handles empty proposals list."""
        from apps.marketplace.proposal_engine import ProposalEngine

        pe = ProposalEngine()
        pe._loaded = True
        pe._proposals = []

        analytics = pe.proposal_analytics()

        assert analytics["total_proposals"] == 0
        assert analytics["avg_price_usd"] == 0.0

    def test_recent_proposals_sorted_by_date(self):
        """recent_proposals returns proposals sorted by created_at descending."""
        from apps.marketplace.proposal_engine import ProposalEngine

        now = time.time()
        pe = ProposalEngine()
        pe._loaded = True
        pe._proposals = [
            {"proposal_id": "p1", "status": "draft", "price_usd": 100.0, "created_at": now - 100},
            {"proposal_id": "p2", "status": "sent", "price_usd": 200.0, "created_at": now - 10},
            {"proposal_id": "p3", "status": "accepted", "price_usd": 300.0, "created_at": now - 50},
        ]

        recent = pe.recent_proposals(limit=2)

        assert len(recent) == 2
        assert recent[0]["proposal_id"] == "p2"  # Most recent first
        assert recent[1]["proposal_id"] == "p3"

    @pytest.mark.asyncio
    async def test_generate_proposal_persists_to_list(self):
        """generate_proposal adds to internal _proposals list."""
        from apps.marketplace.proposal_engine import ProposalEngine

        cache = _mock_cache()
        ai = _mock_ai_failed()  # Use fallback

        with patch("apps.marketplace.proposal_engine.get_cache", return_value=cache), \
             patch("apps.marketplace.proposal_engine.get_ai_client", return_value=ai):
            pe = ProposalEngine()
            await pe.generate_proposal("l1", "Design", {}, 500.0)
            await pe.generate_proposal("l2", "Dev", {}, 1000.0)

        assert len(pe._proposals) == 2
