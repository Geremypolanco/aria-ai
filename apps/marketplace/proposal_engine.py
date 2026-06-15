"""
ARIA Proposal Engine — AI-powered project proposal generator for client acquisition.
Generates Fiverr gigs, Upwork profiles, service pricing, and project proposals.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_PROPOSALS_KEY = "marketplace:proposals:v1"
_PROPOSALS_TTL = 86400 * 90  # 90 days


@dataclass
class Proposal:
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    lead_id: str = ""
    title: str = ""
    executive_summary: str = ""
    scope_of_work: list = field(default_factory=list)   # list of deliverable strings
    timeline_days: int = 0
    price_usd: float = 0.0
    payment_terms: str = ""
    why_us: str = ""
    next_steps: list = field(default_factory=list)
    status: str = "draft"   # "draft"|"sent"|"accepted"|"rejected"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "lead_id": self.lead_id,
            "title": self.title,
            "executive_summary": self.executive_summary,
            "scope_of_work": self.scope_of_work,
            "timeline_days": self.timeline_days,
            "price_usd": round(self.price_usd, 4),
            "payment_terms": self.payment_terms,
            "why_us": self.why_us,
            "next_steps": self.next_steps,
            "status": self.status,
            "created_at": self.created_at,
        }


class ProposalEngine:
    """AI-powered project proposal generator."""

    def __init__(self) -> None:
        self._proposals: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_PROPOSALS_KEY)
                if data and isinstance(data, dict):
                    self._proposals = data.get("proposals", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(
                _PROPOSALS_KEY,
                {"proposals": self._proposals},
                ttl_seconds=_PROPOSALS_TTL,
            )
        except Exception:
            pass

    async def generate_proposal(
        self,
        lead_id: str,
        service_type: str,
        client_requirements: dict,
        budget_usd: float,
    ) -> Proposal:
        """AI generates a full project proposal."""
        await self._load()

        title = f"{service_type} Proposal"
        executive_summary = f"We propose to deliver {service_type} tailored to your requirements."
        scope_of_work = ["Project setup and discovery", "Core development", "Testing and QA", "Delivery and support"]
        timeline_days = 14
        payment_terms = "50% upfront, 50% on delivery"
        why_us = "Expert team with proven track record in AI-powered solutions."
        next_steps = ["Review this proposal", "Schedule kickoff call", "Sign agreement", "Begin work"]

        try:
            ai = get_ai_client()
            requirements_text = json.dumps(client_requirements, indent=2)
            resp = await ai.complete(
                system=(
                    "You are an expert proposal writer for a tech agency. "
                    "Create compelling, professional project proposals. Return valid JSON."
                ),
                user=(
                    f"Create a project proposal for:\n"
                    f"Service: {service_type}\n"
                    f"Budget: ${budget_usd}\n"
                    f"Requirements: {requirements_text}\n\n"
                    f"Return JSON: {{\n"
                    f"  \"title\": str,\n"
                    f"  \"executive_summary\": str,\n"
                    f"  \"scope_of_work\": [str, ...],\n"
                    f"  \"timeline_days\": int,\n"
                    f"  \"price_usd\": float,\n"
                    f"  \"payment_terms\": str,\n"
                    f"  \"why_us\": str,\n"
                    f"  \"next_steps\": [str, ...]\n"
                    f"}}"
                ),
                model=AIModel.STRATEGY,
                max_tokens=600,
            )

            if resp.success:
                content = resp.content.strip()
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(content[start:end])
                    title = str(data.get("title", title))
                    executive_summary = str(data.get("executive_summary", executive_summary))
                    scope_of_work = list(data.get("scope_of_work", scope_of_work))
                    timeline_days = int(data.get("timeline_days", timeline_days))
                    price_usd_raw = data.get("price_usd", budget_usd)
                    budget_usd = float(price_usd_raw) if price_usd_raw else budget_usd
                    payment_terms = str(data.get("payment_terms", payment_terms))
                    why_us = str(data.get("why_us", why_us))
                    next_steps = list(data.get("next_steps", next_steps))
        except Exception:
            pass

        proposal = Proposal(
            lead_id=lead_id,
            title=title,
            executive_summary=executive_summary,
            scope_of_work=scope_of_work,
            timeline_days=timeline_days,
            price_usd=budget_usd,
            payment_terms=payment_terms,
            why_us=why_us,
            next_steps=next_steps,
        )
        self._proposals.append(proposal.to_dict())
        await self._save()
        return proposal

    async def generate_fiverr_gig(self, service_category: str, niche: str) -> dict:
        """AI generates a complete Fiverr gig listing."""
        default_result = {
            "title": f"Professional {service_category} for {niche}",
            "description": f"Expert {service_category} services tailored for {niche} businesses.",
            "packages": {
                "basic": {"name": "Starter", "price_usd": 25, "delivery_days": 3, "description": "Basic package"},
                "standard": {"name": "Professional", "price_usd": 75, "delivery_days": 5, "description": "Standard package"},
                "premium": {"name": "Enterprise", "price_usd": 200, "delivery_days": 10, "description": "Full service"},
            },
            "tags": [service_category.lower(), niche.lower(), "professional", "quality", "fast-delivery"],
        }

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    "You are a Fiverr gig optimization expert. Create high-converting gig listings. "
                    "Return valid JSON only."
                ),
                user=(
                    f"Create a complete Fiverr gig for:\n"
                    f"Category: {service_category}\n"
                    f"Niche: {niche}\n\n"
                    f"Return JSON with keys: title, description, packages (basic/standard/premium with "
                    f"price_usd, delivery_days, description), tags (list of 5)"
                ),
                model=AIModel.CREATIVE,
                max_tokens=500,
            )

            if resp.success:
                content = resp.content.strip()
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(content[start:end])
                    return {
                        "title": str(data.get("title", default_result["title"])),
                        "description": str(data.get("description", default_result["description"])),
                        "packages": data.get("packages", default_result["packages"]),
                        "tags": list(data.get("tags", default_result["tags"])),
                    }
        except Exception:
            pass

        return default_result

    async def generate_upwork_profile(self, skills: list, specialization: str) -> dict:
        """AI generates an Upwork profile overview and title."""
        skills_str = ", ".join(skills)
        default_result = {
            "title": f"Expert {specialization} Specialist",
            "overview": (
                f"I am a specialized {specialization} expert with skills in {skills_str}. "
                f"I deliver high-quality results on time and within budget."
            ),
            "skills": skills,
        }

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    "You are an Upwork profile optimization expert. Create compelling profiles "
                    "that win clients. Return valid JSON only."
                ),
                user=(
                    f"Create an Upwork profile for a freelancer with:\n"
                    f"Specialization: {specialization}\n"
                    f"Skills: {skills_str}\n\n"
                    f"Return JSON: {{\"title\": str, \"overview\": str (200-300 words), \"skills\": [str, ...]}}"
                ),
                model=AIModel.CREATIVE,
                max_tokens=500,
            )

            if resp.success:
                content = resp.content.strip()
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(content[start:end])
                    return {
                        "title": str(data.get("title", default_result["title"])),
                        "overview": str(data.get("overview", default_result["overview"])),
                        "skills": list(data.get("skills", default_result["skills"])),
                    }
        except Exception:
            pass

        return default_result

    async def price_service(
        self,
        service_type: str,
        complexity: str = "medium",
        market_rate_research: dict = {},
    ) -> dict:
        """AI suggests pricing with rationale."""
        # Base pricing by complexity
        base_prices = {"low": 150, "medium": 500, "high": 1500, "enterprise": 5000}
        base_price = base_prices.get(complexity, 500)

        default_result = {
            "price_usd": float(base_price),
            "rationale": f"{service_type} at {complexity} complexity typically costs ${base_price}.",
            "competitor_range": f"${int(base_price * 0.7)}-${int(base_price * 1.5)}",
            "positioning": "competitive",
        }

        try:
            ai = get_ai_client()
            research_text = json.dumps(market_rate_research) if market_rate_research else "No market data provided"
            resp = await ai.complete(
                system=(
                    "You are a pricing strategy expert for digital services. "
                    "Provide data-driven pricing recommendations. Return valid JSON only."
                ),
                user=(
                    f"Suggest pricing for:\n"
                    f"Service: {service_type}\n"
                    f"Complexity: {complexity}\n"
                    f"Market research: {research_text}\n\n"
                    f"Return JSON: {{\"price_usd\": float, \"rationale\": str, "
                    f"\"competitor_range\": str, \"positioning\": str}}"
                ),
                model=AIModel.STRATEGY,
                max_tokens=300,
            )

            if resp.success:
                content = resp.content.strip()
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(content[start:end])
                    return {
                        "price_usd": float(data.get("price_usd", default_result["price_usd"])),
                        "rationale": str(data.get("rationale", default_result["rationale"])),
                        "competitor_range": str(data.get("competitor_range", default_result["competitor_range"])),
                        "positioning": str(data.get("positioning", "competitive")),
                    }
        except Exception:
            pass

        return default_result

    def update_proposal_status(self, proposal_id: str, status: str) -> bool:
        """Update proposal status."""
        valid_statuses = {"draft", "sent", "accepted", "rejected"}
        if status not in valid_statuses:
            return False

        for i, p in enumerate(self._proposals):
            if p.get("proposal_id") == proposal_id:
                p["status"] = status
                self._proposals[i] = p
                return True
        return False

    def proposal_analytics(self) -> dict:
        """Analytics on all proposals."""
        if not self._proposals:
            return {
                "total_proposals": 0,
                "by_status": {},
                "avg_price_usd": 0.0,
                "win_rate_pct": 0.0,
                "total_pipeline_value": 0.0,
            }

        by_status: dict[str, int] = {}
        for p in self._proposals:
            status = p.get("status", "draft")
            by_status[status] = by_status.get(status, 0) + 1

        prices = [p.get("price_usd", 0.0) for p in self._proposals]
        avg_price = sum(prices) / max(len(prices), 1)

        accepted = by_status.get("accepted", 0)
        sent = by_status.get("sent", 0) + accepted + by_status.get("rejected", 0)
        win_rate = (accepted / max(sent, 1)) * 100

        pipeline_value = sum(
            p.get("price_usd", 0.0)
            for p in self._proposals
            if p.get("status") not in ("rejected",)
        )

        return {
            "total_proposals": len(self._proposals),
            "by_status": by_status,
            "avg_price_usd": round(avg_price, 4),
            "win_rate_pct": round(win_rate, 4),
            "total_pipeline_value": round(pipeline_value, 4),
        }

    def recent_proposals(self, limit: int = 10) -> list[dict]:
        """Return most recent proposals."""
        return sorted(self._proposals, key=lambda p: p.get("created_at", 0), reverse=True)[:limit]


_instance: Optional[ProposalEngine] = None


def get_proposal_engine() -> ProposalEngine:
    global _instance
    if _instance is None:
        _instance = ProposalEngine()
    return _instance
