"""Phase 11 tests — Acquisition Layer (LinkedIn, Upwork, Fiverr, Outreach Sequencer)."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content="Hi there! I noticed your work at ACME and think we could collaborate."):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


# ── LinkedIn Outreach ─────────────────────────────────────────────────────────

class TestLinkedInOutreach:
    @pytest.fixture
    def outreach(self):
        with patch("apps.acquisition.linkedin.linkedin_outreach.get_cache", return_value=_mock_cache()):
            with patch("apps.acquisition.linkedin.linkedin_outreach.get_ai_client",
                       return_value=_mock_ai("0.8 This prospect is highly relevant as they manage marketing budgets.")):
                from apps.acquisition.linkedin.linkedin_outreach import LinkedInOutreach
                return LinkedInOutreach()

    @pytest.mark.asyncio
    async def test_add_prospect_returns_prospect(self, outreach):
        from apps.acquisition.linkedin.linkedin_outreach import LinkedInProspect
        p = await outreach.add_prospect("Alice Smith", "CMO", "TechCorp", "SaaS")
        assert isinstance(p, LinkedInProspect)
        assert p.prospect_id

    @pytest.mark.asyncio
    async def test_add_prospect_stores_data(self, outreach):
        await outreach.add_prospect("Bob Jones", "CTO", "StartupX", "fintech")
        assert len(outreach._prospects) == 1
        assert outreach._prospects[0]["name"] == "Bob Jones"

    @pytest.mark.asyncio
    async def test_score_prospect_returns_prospect(self, outreach):
        from apps.acquisition.linkedin.linkedin_outreach import LinkedInProspect
        p = await outreach.add_prospect("Carol", "VP Marketing", "MegaCorp", "ecommerce")
        scored = await outreach.score_prospect(p.prospect_id, "AI marketing tools")
        assert isinstance(scored, LinkedInProspect)

    @pytest.mark.asyncio
    async def test_score_prospect_has_valid_score(self, outreach):
        p = await outreach.add_prospect("Dave", "Founder", "StartupY", "health")
        scored = await outreach.score_prospect(p.prospect_id, "health tech")
        assert 0.0 <= scored.relevance_score <= 1.0

    @pytest.mark.asyncio
    async def test_generate_connection_request_returns_message(self, outreach):
        from apps.acquisition.linkedin.linkedin_outreach import LinkedInMessage
        p = await outreach.add_prospect("Eve", "Director", "Corp", "finance")
        msg = await outreach.generate_connection_request(p.prospect_id, "financial analytics")
        assert isinstance(msg, LinkedInMessage)
        assert msg.message_id

    @pytest.mark.asyncio
    async def test_connection_request_under_300_chars(self, outreach):
        p = await outreach.add_prospect("Frank", "CEO", "Startup", "tech")
        msg = await outreach.generate_connection_request(p.prospect_id, "AI tools")
        assert len(msg.body) <= 300

    @pytest.mark.asyncio
    async def test_generate_outreach_sequence_returns_4_messages(self, outreach):
        p = await outreach.add_prospect("Grace", "COO", "BigCo", "logistics")
        msgs = await outreach.generate_outreach_sequence(p.prospect_id, "logistics AI")
        assert isinstance(msgs, list)
        assert len(msgs) == 4

    @pytest.mark.asyncio
    async def test_sequence_message_types(self, outreach):
        p = await outreach.add_prospect("Hank", "VP Sales", "SalesCo", "SaaS")
        msgs = await outreach.generate_outreach_sequence(p.prospect_id, "sales automation")
        types = [m.message_type for m in msgs]
        assert "connection_request" in types
        assert "intro" in types

    def test_update_prospect_status(self, outreach):
        import asyncio
        loop = asyncio.get_event_loop()
        p = loop.run_until_complete(outreach.add_prospect("Iris", "Manager", "Corp", "retail"))
        result = outreach.update_prospect_status(p.prospect_id, "connected")
        assert result is True
        updated = next(x for x in outreach._prospects if x["prospect_id"] == p.prospect_id)
        assert updated["status"] == "connected"

    def test_hot_prospects_returns_high_scorers(self, outreach):
        outreach._prospects = [
            {"prospect_id": "a1", "relevance_score": 0.9, "status": "identified"},
            {"prospect_id": "a2", "relevance_score": 0.4, "status": "identified"},
        ]
        hot = outreach.hot_prospects(min_score=0.7)
        assert len(hot) == 1
        assert hot[0]["prospect_id"] == "a1"

    def test_outreach_analytics_has_required_keys(self, outreach):
        stats = outreach.outreach_analytics()
        assert "total_prospects" in stats
        assert "by_status" in stats
        assert "avg_relevance_score" in stats


# ── Upwork Bidder ─────────────────────────────────────────────────────────────

class TestUpworkBidder:
    @pytest.fixture
    def bidder(self):
        with patch("apps.acquisition.upwork.upwork_bidder.get_cache", return_value=_mock_cache()):
            with patch("apps.acquisition.upwork.upwork_bidder.get_ai_client",
                       return_value=_mock_ai("fit_score: 0.85 — strong match for this project budget $500")):
                from apps.acquisition.upwork.upwork_bidder import UpworkBidder
                return UpworkBidder()

    @pytest.mark.asyncio
    async def test_evaluate_job_returns_job(self, bidder):
        from apps.acquisition.upwork.upwork_bidder import UpworkJob
        job = await bidder.evaluate_job(
            "Build REST API", "Need FastAPI developer",
            500.0, 1500.0, ["python", "fastapi"], ["python", "fastapi", "postgresql"]
        )
        assert isinstance(job, UpworkJob)
        assert job.job_id

    @pytest.mark.asyncio
    async def test_evaluate_job_fit_score_in_range(self, bidder):
        job = await bidder.evaluate_job(
            "ML Model", "Train classification model",
            200.0, 800.0, ["python", "sklearn"], ["python", "sklearn", "pytorch"]
        )
        assert 0.0 <= job.fit_score <= 1.0

    @pytest.mark.asyncio
    async def test_evaluate_job_sets_bid_price(self, bidder):
        job = await bidder.evaluate_job(
            "Content Writer", "Blog posts",
            100.0, 300.0, ["writing"], ["writing", "seo"]
        )
        assert job.bid_price > 0.0

    @pytest.mark.asyncio
    async def test_write_proposal_returns_proposal(self, bidder):
        from apps.acquisition.upwork.upwork_bidder import UpworkProposal
        job = await bidder.evaluate_job("Dev job", "desc", 500.0, 1000.0, ["react"], ["react"])
        proposal = await bidder.write_proposal(job.job_id, "React development")
        assert isinstance(proposal, UpworkProposal)
        assert proposal.proposal_id

    @pytest.mark.asyncio
    async def test_proposal_has_hook_and_body(self, bidder):
        job = await bidder.evaluate_job("Design job", "desc", 200.0, 500.0, ["figma"], ["figma"])
        proposal = await bidder.write_proposal(job.job_id, "UI/UX design")
        assert isinstance(proposal.opening_hook, str)
        assert isinstance(proposal.body, str)

    @pytest.mark.asyncio
    async def test_generate_profile_optimization_returns_dict(self, bidder):
        profile = await bidder.generate_profile_optimization(
            ["python", "fastapi", "postgresql"], "Backend Development"
        )
        assert "headline" in profile
        assert "overview" in profile
        assert "portfolio_suggestions" in profile

    def test_filter_jobs_by_fit_score(self, bidder):
        bidder._jobs = [
            {"job_id": "j1", "fit_score": 0.8, "budget_max": 500.0},
            {"job_id": "j2", "fit_score": 0.4, "budget_max": 200.0},
        ]
        filtered = bidder.filter_jobs(min_fit_score=0.7)
        assert len(filtered) == 1
        assert filtered[0]["job_id"] == "j1"

    def test_bidding_analytics_has_required_keys(self, bidder):
        stats = bidder.bidding_analytics()
        assert "total_jobs" in stats
        assert "win_rate_pct" in stats
        assert "avg_bid" in stats


# ── Fiverr Optimizer ──────────────────────────────────────────────────────────

class TestFiverrOptimizer:
    @pytest.fixture
    def optimizer(self):
        with patch("apps.acquisition.fiverr.fiverr_optimizer.get_cache", return_value=_mock_cache()):
            with patch("apps.acquisition.fiverr.fiverr_optimizer.get_ai_client",
                       return_value=_mock_ai("I will create professional AI content for your fitness brand")):
                from apps.acquisition.fiverr.fiverr_optimizer import FiverrOptimizer
                return FiverrOptimizer()

    @pytest.mark.asyncio
    async def test_create_gig_returns_gig(self, optimizer):
        from apps.acquisition.fiverr.fiverr_optimizer import FiverrGig
        gig = await optimizer.create_gig("content writing", "fitness")
        assert isinstance(gig, FiverrGig)
        assert gig.gig_id

    @pytest.mark.asyncio
    async def test_gig_has_packages(self, optimizer):
        gig = await optimizer.create_gig("logo design", "tech")
        assert isinstance(gig.packages, dict)
        assert "basic" in gig.packages
        assert "standard" in gig.packages
        assert "premium" in gig.packages

    @pytest.mark.asyncio
    async def test_gig_has_tags(self, optimizer):
        gig = await optimizer.create_gig("SEO writing", "health")
        assert isinstance(gig.tags, list)
        assert len(gig.tags) >= 3

    @pytest.mark.asyncio
    async def test_gig_has_faq(self, optimizer):
        gig = await optimizer.create_gig("video editing", "lifestyle")
        assert isinstance(gig.faq, list)
        assert len(gig.faq) >= 3

    @pytest.mark.asyncio
    async def test_optimize_gig_title_returns_string(self, optimizer):
        title = await optimizer.optimize_gig_title("I write blogs", "SEO content writing")
        assert isinstance(title, str)
        assert len(title) > 0
        assert len(title) <= 80

    @pytest.mark.asyncio
    async def test_price_packages_returns_tiers(self, optimizer):
        pricing = await optimizer.price_packages("content writing", "low-high")
        assert "basic" in pricing
        assert "standard" in pricing
        assert "premium" in pricing

    @pytest.mark.asyncio
    async def test_generate_portfolio_description_returns_string(self, optimizer):
        desc = await optimizer.generate_portfolio_description(
            {"type": "website", "client": "StartupX", "result": "200% traffic increase"}
        )
        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_gig_analytics_has_required_keys(self, optimizer):
        stats = optimizer.gig_analytics()
        assert "total_gigs" in stats
        assert "active" in stats
        assert "avg_seo_score" in stats


# ── Outreach Sequencer ────────────────────────────────────────────────────────

class TestOutreachSequencer:
    @pytest.fixture
    def sequencer(self):
        with patch("apps.acquisition.outreach.outreach_sequencer.get_cache", return_value=_mock_cache()):
            with patch("apps.acquisition.outreach.outreach_sequencer.get_ai_client",
                       return_value=_mock_ai("MSG1: Hi there!\nMSG2: Just following up.\nMSG3: Here's an insight.\nMSG4: Would love to chat!")):
                from apps.acquisition.outreach.outreach_sequencer import OutreachSequencer
                return OutreachSequencer()

    @pytest.mark.asyncio
    async def test_create_sequence_returns_sequence(self, sequencer):
        from apps.acquisition.outreach.outreach_sequencer import OutreachSequence
        seq = await sequencer.create_sequence(
            "SaaS Founders", "email", "startup_founders", "book demo", steps=5
        )
        assert isinstance(seq, OutreachSequence)
        assert seq.sequence_id

    @pytest.mark.asyncio
    async def test_sequence_has_steps(self, sequencer):
        seq = await sequencer.create_sequence(
            "Agency Owners", "linkedin", "agency_owners", "schedule call", steps=4
        )
        assert isinstance(seq.steps, list)
        assert len(seq.steps) == 4

    @pytest.mark.asyncio
    async def test_sequence_has_channel(self, sequencer):
        seq = await sequencer.create_sequence(
            "Ecommerce Brands", "email", "ecom_managers", "free audit", steps=3
        )
        assert seq.channel == "email"
        assert seq.target_persona == "ecom_managers"

    @pytest.mark.asyncio
    async def test_enroll_contact_returns_contact(self, sequencer):
        from apps.acquisition.outreach.outreach_sequencer import OutreachContact
        seq = await sequencer.create_sequence("Test", "email", "cto", "demo", steps=3)
        contact = await sequencer.enroll_contact("John Doe", "john@corp.com", "Corp", seq.sequence_id)
        assert isinstance(contact, OutreachContact)
        assert contact.contact_id

    @pytest.mark.asyncio
    async def test_enrolled_contact_has_active_status(self, sequencer):
        seq = await sequencer.create_sequence("Test2", "email", "ceo", "call", steps=3)
        contact = await sequencer.enroll_contact("Jane Smith", "jane@co.com", "Co", seq.sequence_id)
        assert contact.status == "active"

    @pytest.mark.asyncio
    async def test_personalize_step_returns_dict(self, sequencer):
        seq = await sequencer.create_sequence("Personalise Test", "linkedin", "founder", "meeting", steps=3)
        contact = await sequencer.enroll_contact("Pete", "pete@x.com", "X Corp", seq.sequence_id)
        result = await sequencer.personalize_step(contact.contact_id, 0)
        assert isinstance(result, dict)
        assert "body" in result

    def test_contacts_due_today_returns_list(self, sequencer):
        import time
        sequencer._contacts = [
            {"contact_id": "c1", "status": "active", "next_action_at": time.time() - 100},
            {"contact_id": "c2", "status": "active", "next_action_at": time.time() + 9999},
        ]
        due = sequencer.contacts_due_today()
        assert len(due) == 1
        assert due[0]["contact_id"] == "c1"

    def test_advance_contact_moves_to_next_step(self, sequencer):
        sequencer._sequences = [{"sequence_id": "s1", "total_steps": 3}]
        sequencer._contacts = [
            {"contact_id": "c1", "sequence_id": "s1", "current_step": 0, "status": "active"}
        ]
        result = sequencer.advance_contact("c1")
        assert result is True
        assert sequencer._contacts[0]["current_step"] == 1

    def test_sequence_analytics_has_required_keys(self, sequencer):
        stats = sequencer.sequence_analytics()
        assert "total_sequences" in stats
        assert "total_contacts" in stats
        assert "reply_rate_pct" in stats
        assert "by_channel" in stats

    @pytest.mark.asyncio
    async def test_multiple_sequences_tracked(self, sequencer):
        await sequencer.create_sequence("Seq A", "email", "cto", "demo", steps=3)
        await sequencer.create_sequence("Seq B", "linkedin", "cmo", "call", steps=4)
        assert len(sequencer._sequences) == 2
