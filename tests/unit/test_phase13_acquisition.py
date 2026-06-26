"""Phase 13 tests — Acquisition (LeadEngine, CRMEngine)."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content="7\nSend personalized case study email\nSchedule a discovery call"):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


# ── Lead Engine ───────────────────────────────────────────────────────────────

class TestLeadEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.acquisition.leads.lead_engine.get_cache", return_value=_mock_cache()):
            with patch("apps.acquisition.leads.lead_engine.get_ai_client",
                       return_value=_mock_ai("Fitness Studio A — weak SEO, no automation\nE-commerce Brand B — low conversion rate\nLocal Gym C — no email list")):
                from apps.acquisition.leads.lead_engine import LeadEngine
                return LeadEngine()

    @pytest.mark.asyncio
    async def test_discover_leads_returns_list(self, engine):
        leads = await engine.discover_leads("fitness", count=3)
        assert isinstance(leads, list)
        assert len(leads) >= 1

    @pytest.mark.asyncio
    async def test_discover_leads_are_lead_objects(self, engine):
        from apps.acquisition.leads.lead_engine import Lead
        leads = await engine.discover_leads("ecommerce", count=2)
        assert all(isinstance(l, Lead) for l in leads)

    @pytest.mark.asyncio
    async def test_discover_leads_have_lead_id(self, engine):
        leads = await engine.discover_leads("saas", count=2)
        assert all(l.lead_id for l in leads)

    @pytest.mark.asyncio
    async def test_discover_leads_stored_in_memory(self, engine):
        await engine.discover_leads("fitness", count=3)
        assert len(engine._leads) >= 1

    @pytest.mark.asyncio
    async def test_discover_leads_have_niche(self, engine):
        leads = await engine.discover_leads("restaurant", count=2)
        assert all(l.niche == "restaurant" for l in leads)

    @pytest.mark.asyncio
    async def test_discover_leads_have_pain_points(self, engine):
        leads = await engine.discover_leads("retail", count=2)
        assert all(isinstance(l.pain_points, list) for l in leads)

    @pytest.mark.asyncio
    async def test_discover_leads_have_opportunity_score(self, engine):
        leads = await engine.discover_leads("gym", count=2)
        assert all(0.0 <= l.opportunity_score <= 1.0 for l in leads)

    @pytest.mark.asyncio
    async def test_score_lead_updates_score(self, engine):
        from apps.acquisition.leads.lead_engine import Lead
        lead = Lead(
            company_name="Test Co",
            niche="fitness",
            pain_points=["no SEO", "no automation"],
            services_needed=["SEO", "content"],
        )
        scored = await engine.score_lead(lead)
        assert 0.0 <= scored.opportunity_score <= 1.0

    @pytest.mark.asyncio
    async def test_generate_proposal_brief_returns_brief(self, engine):
        from apps.acquisition.leads.lead_engine import Lead, ProposalBrief
        lead = Lead(
            lead_id="test1",
            company_name="Acme Fitness",
            niche="fitness",
            pain_points=["no online presence"],
            services_needed=["SEO", "content"],
            estimated_value_usd=800.0,
        )
        engine._leads.append(lead.to_dict())
        brief = await engine.generate_proposal_brief(lead)
        assert isinstance(brief, ProposalBrief)
        assert brief.brief_id

    @pytest.mark.asyncio
    async def test_proposal_brief_has_subject_line(self, engine):
        from apps.acquisition.leads.lead_engine import Lead
        lead = Lead(company_name="FitCo", niche="fitness", pain_points=["weak SEO"])
        brief = await engine.generate_proposal_brief(lead)
        assert len(brief.subject_line) > 0

    @pytest.mark.asyncio
    async def test_proposal_brief_has_cta(self, engine):
        from apps.acquisition.leads.lead_engine import Lead
        lead = Lead(company_name="GymX", niche="fitness", services_needed=["automation"])
        brief = await engine.generate_proposal_brief(lead)
        assert len(brief.cta) > 0

    @pytest.mark.asyncio
    async def test_proposal_brief_has_social_proof(self, engine):
        from apps.acquisition.leads.lead_engine import Lead
        lead = Lead(company_name="StoreX", niche="ecommerce")
        brief = await engine.generate_proposal_brief(lead)
        assert len(brief.social_proof) > 0

    @pytest.mark.asyncio
    async def test_update_lead_status_valid(self, engine):
        leads = await engine.discover_leads("tech", count=1)
        if leads:
            result = await engine.update_lead_status(leads[0].lead_id, "contacted")
            assert result is True

    @pytest.mark.asyncio
    async def test_update_lead_status_invalid_returns_false(self, engine):
        result = await engine.update_lead_status("nonexistent", "invalid_status")
        assert result is False

    def test_qualified_leads_filters_by_score(self, engine):
        engine._leads = [
            {"lead_id": "a", "opportunity_score": 0.8, "company_name": "A"},
            {"lead_id": "b", "opportunity_score": 0.3, "company_name": "B"},
            {"lead_id": "c", "opportunity_score": 0.7, "company_name": "C"},
        ]
        qualified = engine.qualified_leads(min_score=0.6)
        assert len(qualified) == 2

    def test_leads_by_status(self, engine):
        engine._leads = [
            {"lead_id": "a", "status": "contacted"},
            {"lead_id": "b", "status": "new"},
            {"lead_id": "c", "status": "contacted"},
        ]
        contacted = engine.leads_by_status("contacted")
        assert len(contacted) == 2

    def test_lead_analytics_has_required_keys(self, engine):
        analytics = engine.lead_analytics()
        assert "total_leads" in analytics
        assert "qualified_leads" in analytics
        assert "by_status" in analytics
        assert "avg_opportunity_score" in analytics
        assert "total_pipeline_value_usd" in analytics

    @pytest.mark.asyncio
    async def test_multiple_discover_accumulate(self, engine):
        await engine.discover_leads("fitness", count=2)
        await engine.discover_leads("tech", count=2)
        assert len(engine._leads) >= 2

    def test_recent_leads_returns_list(self, engine):
        engine._leads = [{"lead_id": "x", "created_at": 1000.0, "company_name": "X"}]
        result = engine.recent_leads(limit=5)
        assert isinstance(result, list)


# ── CRM Engine ────────────────────────────────────────────────────────────────

class TestCRMEngine:
    @pytest.fixture
    def crm(self):
        with patch("apps.acquisition.crm.crm_engine.get_cache", return_value=_mock_cache()):
            with patch("apps.acquisition.crm.crm_engine.get_ai_client",
                       return_value=_mock_ai("Send personalized case study + book 20-min call")):
                from apps.acquisition.crm.crm_engine import CRMEngine
                return CRMEngine()

    @pytest.mark.asyncio
    async def test_add_contact_returns_contact(self, crm):
        from apps.acquisition.crm.crm_engine import CRMContact
        contact = await crm.add_contact("Alice", "FitCo", email="alice@fitco.com", niche="fitness")
        assert isinstance(contact, CRMContact)
        assert contact.contact_id

    @pytest.mark.asyncio
    async def test_add_contact_default_stage_is_new(self, crm):
        contact = await crm.add_contact("Bob", "TechCo")
        assert contact.stage == "new"

    @pytest.mark.asyncio
    async def test_add_contact_sets_weighted_value(self, crm):
        contact = await crm.add_contact("Carol", "Corp", deal_value_usd=1000.0)
        assert contact.weighted_value_usd > 0.0

    @pytest.mark.asyncio
    async def test_add_contact_stored_in_memory(self, crm):
        await crm.add_contact("Dave", "DaveCo")
        assert len(crm._contacts) == 1

    @pytest.mark.asyncio
    async def test_advance_stage_moves_forward(self, crm):
        contact = await crm.add_contact("Eve", "EveCo")
        updated = await crm.advance_stage(contact.contact_id)
        assert updated is not None
        assert updated.get("stage") == "contacted"

    @pytest.mark.asyncio
    async def test_advance_stage_updates_probability(self, crm):
        contact = await crm.add_contact("Frank", "FrankCo")
        updated = await crm.advance_stage(contact.contact_id)
        assert updated is not None
        assert updated.get("probability_pct") > 5.0

    @pytest.mark.asyncio
    async def test_advance_stage_nonexistent_returns_none(self, crm):
        result = await crm.advance_stage("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_log_interaction_returns_true(self, crm):
        contact = await crm.add_contact("Grace", "GraceCo")
        result = await crm.log_interaction(contact.contact_id, "email", "Sent intro email", "no reply yet")
        assert result is True

    @pytest.mark.asyncio
    async def test_log_interaction_stores_in_contact(self, crm):
        contact = await crm.add_contact("Hank", "HankCo")
        await crm.log_interaction(contact.contact_id, "call", "Had discovery call", "interested")
        updated = next(c for c in crm._contacts if c["contact_id"] == contact.contact_id)
        assert len(updated["interactions"]) == 1

    @pytest.mark.asyncio
    async def test_log_interaction_nonexistent_returns_false(self, crm):
        result = await crm.log_interaction("fake-id", "email", "test")
        assert result is False

    @pytest.mark.asyncio
    async def test_suggest_next_action_returns_string(self, crm):
        contact = await crm.add_contact("Iris", "IrisCo")
        action = await crm.suggest_next_action(contact.contact_id)
        assert isinstance(action, str)
        assert len(action) > 0

    @pytest.mark.asyncio
    async def test_suggest_next_action_nonexistent(self, crm):
        result = await crm.suggest_next_action("nonexistent")
        assert "No contact" in result

    def test_contacts_by_stage(self, crm):
        crm._contacts = [
            {"contact_id": "a", "stage": "new"},
            {"contact_id": "b", "stage": "contacted"},
            {"contact_id": "c", "stage": "new"},
        ]
        new_contacts = crm.contacts_by_stage("new")
        assert len(new_contacts) == 2

    def test_pipeline_value_has_required_keys(self, crm):
        pv = crm.pipeline_value()
        assert "total_potential_usd" in pv
        assert "weighted_pipeline_usd" in pv
        assert "closed_won_usd" in pv

    def test_crm_dashboard_has_required_keys(self, crm):
        dash = crm.crm_dashboard()
        assert "total_contacts" in dash
        assert "by_stage" in dash
        assert "by_source" in dash

    @pytest.mark.asyncio
    async def test_multiple_contacts_accumulate(self, crm):
        await crm.add_contact("A", "AComp")
        await crm.add_contact("B", "BComp")
        await crm.add_contact("C", "CComp")
        assert len(crm._contacts) == 3

    def test_recent_contacts_returns_list(self, crm):
        result = crm.recent_contacts(limit=5)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_pipeline_value_reflects_closed_won(self, crm):
        crm._contacts = [
            {"contact_id": "x", "stage": "closed_won", "deal_value_usd": 1000.0, "weighted_value_usd": 1000.0, "probability_pct": 100.0},
        ]
        pv = crm.pipeline_value()
        assert pv["closed_won_usd"] == 1000.0
