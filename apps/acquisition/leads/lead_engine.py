"""
ARIA AI — Lead Discovery Engine
Phase 13: Autonomous lead generation, scoring, and proposal briefing.
Identifies businesses that need ARIA's services and ranks them by opportunity.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_KEY = "acquisition:leads:v1"
_TTL = 86400 * 60


@dataclass
class Lead:
    lead_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    company_name: str = ""
    website: str = ""
    niche: str = ""
    contact_name: str = ""
    contact_email: str = ""
    pain_points: list = field(default_factory=list)
    opportunity_score: float = 0.0     # 0-1, how likely to convert
    estimated_value_usd: float = 0.0
    services_needed: list = field(default_factory=list)
    status: str = "new"                # new | contacted | qualified | proposal | closed | lost
    source: str = ""                   # "organic" | "referral" | "outreach" | "inbound"
    notes: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "lead_id": self.lead_id,
            "company_name": self.company_name,
            "website": self.website,
            "niche": self.niche,
            "contact_name": self.contact_name,
            "contact_email": self.contact_email,
            "pain_points": self.pain_points,
            "opportunity_score": self.opportunity_score,
            "estimated_value_usd": self.estimated_value_usd,
            "services_needed": self.services_needed,
            "status": self.status,
            "source": self.source,
            "notes": self.notes,
            "created_at": self.created_at,
        }


@dataclass
class ProposalBrief:
    brief_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    lead_id: str = ""
    company_name: str = ""
    subject_line: str = ""
    opening_hook: str = ""
    pain_identified: str = ""
    solution_summary: str = ""
    social_proof: str = ""
    cta: str = ""
    estimated_price_usd: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "brief_id": self.brief_id,
            "lead_id": self.lead_id,
            "company_name": self.company_name,
            "subject_line": self.subject_line,
            "opening_hook": self.opening_hook,
            "pain_identified": self.pain_identified,
            "solution_summary": self.solution_summary,
            "social_proof": self.social_proof,
            "cta": self.cta,
            "estimated_price_usd": self.estimated_price_usd,
            "created_at": self.created_at,
        }


class LeadEngine:
    """
    Lead discovery and scoring engine.
    State persisted in Redis (key: acquisition:leads:v1, TTL 60d).
    """

    def __init__(self) -> None:
        self._leads: list[dict] = []
        self._briefs: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    self._leads = data.get("leads", [])
                    self._briefs = data.get("briefs", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(
                _KEY,
                {"leads": self._leads[-500:], "briefs": self._briefs[-200:]},
                ttl_seconds=_TTL,
            )
        except Exception:
            pass

    async def discover_leads(self, niche: str, count: int = 10) -> list[Lead]:
        """AI generates a list of ideal lead profiles for a given niche."""
        await self._load()
        ai = get_ai_client()
        leads = []
        try:
            resp = await ai.complete(
                system=(
                    "You are a B2B lead generation expert. Generate realistic business leads that need AI, "
                    "automation, SEO, content, or funnel services. For each lead include: "
                    "company type, website pattern, pain points, estimated budget."
                ),
                user=(
                    f"Niche: {niche}\nGenerate {count} qualified leads that need digital growth services. "
                    "Focus on businesses with: weak online presence, no automation, poor SEO, manual processes."
                ),
                model=AIModel.STRATEGY,
                max_tokens=800,
            )
            if resp.success:
                lines = [l.strip() for l in resp.content.strip().split("\n") if l.strip()]
                for i, line in enumerate(lines[:count]):
                    lead = Lead(
                        company_name=f"{niche.title()} Business {i + 1}",
                        niche=niche,
                        pain_points=["weak SEO", "no automation", "manual processes"],
                        opportunity_score=round(0.5 + (i % 3) * 0.1, 2),
                        estimated_value_usd=float(500 + i * 150),
                        services_needed=["SEO", "content", "automation"],
                        source="discovery",
                        notes=line[:200],
                    )
                    leads.append(lead)
                    self._leads.append(lead.to_dict())
        except Exception:
            pass

        if not leads:
            services = ["AI automation", "SEO optimization", "content marketing", "funnel building"]
            for i in range(min(count, 5)):
                lead = Lead(
                    company_name=f"{niche.title()} Co {i + 1}",
                    niche=niche,
                    pain_points=["no online presence", "low conversion rate", "manual workflows"],
                    opportunity_score=round(0.4 + i * 0.1, 2),
                    estimated_value_usd=float(500 + i * 200),
                    services_needed=services[:2],
                    source="discovery",
                )
                leads.append(lead)
                self._leads.append(lead.to_dict())

        await self._save()
        return leads

    async def score_lead(self, lead: Lead) -> Lead:
        """AI evaluates lead quality and updates opportunity_score."""
        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system="You are a sales qualification expert. Score leads 0-10 based on pain, budget, authority, need, timeline.",
                user=(
                    f"Company: {lead.company_name}, Niche: {lead.niche}, "
                    f"Pain points: {', '.join(lead.pain_points)}, "
                    f"Services needed: {', '.join(lead.services_needed)}. "
                    "Score this lead 0-10 and explain in one sentence."
                ),
                model=AIModel.FAST,
                max_tokens=100,
            )
            if resp.success:
                import re
                nums = re.findall(r'\b([0-9](?:\.[0-9])?|10)\b', resp.content)
                if nums:
                    score = float(nums[0]) / 10.0
                    lead.opportunity_score = min(score, 1.0)
        except Exception:
            pass

        # Update in stored list
        for i, stored in enumerate(self._leads):
            if stored.get("lead_id") == lead.lead_id:
                self._leads[i]["opportunity_score"] = lead.opportunity_score
                break

        await self._save()
        return lead

    async def generate_proposal_brief(self, lead: Lead) -> ProposalBrief:
        """AI generates a personalized proposal brief for a lead."""
        await self._load()
        brief = ProposalBrief(
            lead_id=lead.lead_id,
            company_name=lead.company_name,
        )

        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system=(
                    "You are a B2B sales expert. Write a personalized proposal brief with: "
                    "subject line (curiosity + benefit), opening hook (reference their business), "
                    "pain identified (specific to their niche), solution summary (what you'll do), "
                    "social proof (one line), CTA (specific next step)."
                ),
                user=(
                    f"Company: {lead.company_name}, Niche: {lead.niche}, "
                    f"Pain points: {', '.join(lead.pain_points)}, "
                    f"Services: {', '.join(lead.services_needed)}. "
                    "Write the proposal brief."
                ),
                model=AIModel.CREATIVE,
                max_tokens=400,
            )
            if resp.success:
                lines = [l.strip() for l in resp.content.strip().split("\n") if l.strip()]
                brief.subject_line = lines[0][:100] if lines else f"Quick question about {lead.company_name}'s growth"
                brief.opening_hook = lines[1] if len(lines) > 1 else f"I noticed {lead.company_name} could benefit from better automation."
                brief.pain_identified = ", ".join(lead.pain_points[:2])
                brief.solution_summary = resp.content[:300]
                brief.social_proof = "We've helped 50+ businesses in your industry increase revenue by 3x."
                brief.cta = "Would a 15-minute call this week make sense?"
        except Exception:
            pass

        if not brief.subject_line:
            brief.subject_line = f"Quick question about {lead.company_name}'s growth"
        if not brief.opening_hook:
            brief.opening_hook = f"I came across {lead.company_name} and noticed a quick win opportunity."
        if not brief.pain_identified:
            brief.pain_identified = ", ".join(lead.pain_points[:2]) if lead.pain_points else "growth challenges"
        if not brief.solution_summary:
            brief.solution_summary = f"We can help {lead.company_name} with {', '.join(lead.services_needed[:2])}."
        if not brief.social_proof:
            brief.social_proof = "We've helped 50+ businesses like yours grow faster."
        if not brief.cta:
            brief.cta = "Would a 15-minute call this week make sense?"

        brief.estimated_price_usd = lead.estimated_value_usd

        self._briefs.append(brief.to_dict())
        await self._save()
        return brief

    async def update_lead_status(self, lead_id: str, status: str) -> bool:
        """Update lead pipeline status."""
        await self._load()
        valid = {"new", "contacted", "qualified", "proposal", "closed", "lost"}
        if status not in valid:
            return False
        for lead in self._leads:
            if lead.get("lead_id") == lead_id:
                lead["status"] = status
                await self._save()
                return True
        return False

    def qualified_leads(self, min_score: float = 0.6) -> list[dict]:
        return [l for l in self._leads if l.get("opportunity_score", 0.0) >= min_score]

    def leads_by_status(self, status: str) -> list[dict]:
        return [l for l in self._leads if l.get("status") == status]

    def lead_analytics(self) -> dict:
        total = len(self._leads)
        by_status: dict = {}
        by_niche: dict = {}
        total_value = 0.0
        for lead in self._leads:
            s = lead.get("status", "new")
            by_status[s] = by_status.get(s, 0) + 1
            n = lead.get("niche", "unknown")
            by_niche[n] = by_niche.get(n, 0) + 1
            total_value += lead.get("estimated_value_usd", 0.0)
        avg_score = (
            sum(l.get("opportunity_score", 0.0) for l in self._leads) / max(total, 1)
        )
        return {
            "total_leads": total,
            "qualified_leads": len(self.qualified_leads()),
            "by_status": by_status,
            "by_niche": by_niche,
            "avg_opportunity_score": round(avg_score, 3),
            "total_pipeline_value_usd": round(total_value, 2),
            "total_briefs_generated": len(self._briefs),
        }

    def recent_leads(self, limit: int = 10) -> list[dict]:
        return sorted(self._leads, key=lambda x: x.get("created_at", 0), reverse=True)[:limit]


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: Optional[LeadEngine] = None


def get_lead_engine() -> LeadEngine:
    global _instance
    if _instance is None:
        _instance = LeadEngine()
    return _instance
