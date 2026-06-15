"""
ARIA AI — Upwork Bidder
Phase 11: AI-powered Upwork job evaluation, proposal writing, and profile optimization.

Capabilities:
  - Job fit scoring
  - Proposal writing
  - Profile optimization
  - Bidding analytics
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

# ── Redis configuration ────────────────────────────────────────────────────────
_REDIS_KEY = "acquisition:upwork:v1"
_TTL_90D = 60 * 60 * 24 * 90


# ══════════════════════════════════════════════════════════════════════════════
# Domain objects
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class UpworkJob:
    job_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = ""
    description: str = ""
    budget_min: float = 0.0
    budget_max: float = 0.0
    skills_required: list = field(default_factory=list)
    client_rating: float = 0.0
    fit_score: float = 0.0
    bid_price: float = 0.0
    status: str = "identified"
    url: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "title": self.title,
            "description": self.description,
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "skills_required": self.skills_required,
            "client_rating": self.client_rating,
            "fit_score": self.fit_score,
            "bid_price": self.bid_price,
            "status": self.status,
            "url": self.url,
            "created_at": self.created_at,
        }


@dataclass
class UpworkProposal:
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    job_id: str = ""
    opening_hook: str = ""
    body: str = ""
    relevant_experience: str = ""
    cta: str = ""
    bid_amount: float = 0.0
    delivery_days: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "job_id": self.job_id,
            "opening_hook": self.opening_hook,
            "body": self.body,
            "relevant_experience": self.relevant_experience,
            "cta": self.cta,
            "bid_amount": self.bid_amount,
            "delivery_days": self.delivery_days,
            "created_at": self.created_at,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Upwork Bidder
# ══════════════════════════════════════════════════════════════════════════════

class UpworkBidder:
    """
    AI-powered Upwork bidding system.
    State persisted in Redis (key: acquisition:upwork:v1, TTL 90d).
    """

    def __init__(self):
        self._jobs: list[dict] = []
        self._proposals: list[dict] = []

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _load(self) -> None:
        cache = get_cache()
        data = await cache.get(_REDIS_KEY)
        if isinstance(data, dict):
            self._jobs = data.get("jobs", [])
            self._proposals = data.get("proposals", [])

    async def _save(self) -> None:
        cache = get_cache()
        await cache.set(
            _REDIS_KEY,
            {"jobs": self._jobs, "proposals": self._proposals},
            ttl_seconds=_TTL_90D,
        )

    def _find_job(self, job_id: str) -> Optional[dict]:
        for j in self._jobs:
            if j.get("job_id") == job_id:
                return j
        return None

    def _calculate_fit(self, skills_required: list, our_skills: list) -> float:
        """Calculate skill overlap fit score."""
        if not skills_required:
            return 0.5
        our_lower = {s.lower() for s in our_skills}
        req_lower = {s.lower() for s in skills_required}
        overlap = len(our_lower & req_lower)
        return min(overlap / len(req_lower) + 0.2, 0.95)

    # ── Public methods ─────────────────────────────────────────────────────────

    async def evaluate_job(
        self,
        title: str,
        description: str,
        budget_min: float,
        budget_max: float,
        skills_required: list,
        our_skills: list,
    ) -> UpworkJob:
        """AI evaluates job fit score and suggests bid price."""
        await self._load()

        # Base fit from skill overlap
        base_fit = self._calculate_fit(skills_required, our_skills)

        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are an Upwork bidding strategist. Evaluate a job's fit and recommend "
                "a bid price. Consider: skill match, budget, competition, and value delivery. "
                "Respond with fit_score (0-1) and bid_price recommendation."
            ),
            user=(
                f"Job: {title}\nBudget: ${budget_min}-${budget_max}\n"
                f"Skills needed: {', '.join(skills_required)}\n"
                f"Our skills: {', '.join(our_skills)}\n\n"
                "Evaluate fit and recommend bid."
            ),
            model=AIModel.FAST,
            max_tokens=200,
        )

        # Extract fit score from AI
        fit_score = base_fit
        if resp.success:
            for token in resp.content.split():
                try:
                    val = float(token.strip(".,()"))
                    if 0.0 <= val <= 1.0:
                        fit_score = val
                        break
                except ValueError:
                    pass

        # Suggest bid at midpoint of budget range
        bid_price = (budget_min + budget_max) / 2 if budget_max > 0 else budget_min * 1.2

        job = UpworkJob(
            title=title,
            description=description,
            budget_min=budget_min,
            budget_max=budget_max,
            skills_required=skills_required,
            fit_score=round(fit_score, 2),
            bid_price=round(bid_price, 2),
        )
        self._jobs.append(job.to_dict())
        await self._save()
        return job

    async def write_proposal(self, job_id: str, our_expertise: str) -> UpworkProposal:
        """AI writes a winning Upwork proposal."""
        await self._load()
        job_dict = self._find_job(job_id)
        title = job_dict.get("title", "this project") if job_dict else "this project"
        budget_max = job_dict.get("budget_max", 100.0) if job_dict else 100.0

        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are an Upwork proposal expert with 95% success rate. Write a winning proposal "
                "with: 1) Hook (show you read the job), 2) Body (how you'll solve the problem), "
                "3) Relevant experience (specific and credible), 4) CTA (clear next step). "
                "Be direct, confident, and client-focused."
            ),
            user=(
                f"Job: {title}\nBudget: up to ${budget_max}\n"
                f"Our expertise: {our_expertise}\n\n"
                "Write the proposal."
            ),
            model=AIModel.CREATIVE,
            max_tokens=600,
        )
        content = resp.content if resp.success else f"Proposal for {title}"
        lines = content.split("\n")

        proposal = UpworkProposal(
            job_id=job_id,
            opening_hook=lines[0].strip() if lines else f"I noticed you need help with {title}",
            body=content,
            relevant_experience=f"I have extensive experience with {our_expertise}",
            cta="Let's schedule a quick call to discuss your project. Available today!",
            bid_amount=round(budget_max * 0.9, 2),
            delivery_days=7,
        )
        self._proposals.append(proposal.to_dict())
        await self._save()
        return proposal

    async def generate_profile_optimization(
        self, skills: list, specialization: str
    ) -> dict:
        """AI optimizes Upwork profile."""
        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are an Upwork profile optimization expert. Create a compelling profile "
                "that attracts high-paying clients. Include headline, overview, skills to highlight, "
                "and portfolio suggestions."
            ),
            user=(
                f"Skills: {', '.join(skills)}\nSpecialization: {specialization}\n\n"
                "Optimize profile for maximum client attraction."
            ),
            model=AIModel.STRATEGY,
            max_tokens=600,
        )
        content = resp.content if resp.success else f"Expert {specialization} specialist"
        return {
            "headline": f"Expert {specialization} | {skills[0] if skills else 'Professional'} Specialist | Top Rated",
            "overview": content,
            "skills_to_highlight": skills[:10],
            "portfolio_suggestions": [
                f"Case study: {specialization} project with measurable results",
                "Before/after transformation showcase",
                "Client testimonial compilation",
            ],
        }

    def filter_jobs(
        self, min_fit_score: float = 0.6, min_budget: float = 50.0
    ) -> list[dict]:
        """Filter jobs by fit score and minimum budget."""
        return [
            j for j in self._jobs
            if j.get("fit_score", 0.0) >= min_fit_score
            and j.get("budget_max", 0.0) >= min_budget
        ]

    def bidding_analytics(self) -> dict:
        """Return bidding analytics."""
        bids_sent = sum(1 for j in self._jobs if j.get("status") in ("bid_sent", "interview", "won", "lost"))
        won = sum(1 for j in self._jobs if j.get("status") == "won")
        bid_amounts = [j.get("bid_price", 0.0) for j in self._jobs if j.get("bid_price", 0.0) > 0]
        won_values = [j.get("bid_price", 0.0) for j in self._jobs if j.get("status") == "won"]

        win_rate = (won / bids_sent * 100) if bids_sent > 0 else 0.0
        avg_bid = sum(bid_amounts) / len(bid_amounts) if bid_amounts else 0.0

        return {
            "total_jobs": len(self._jobs),
            "bids_sent": bids_sent,
            "win_rate_pct": round(win_rate, 1),
            "avg_bid": round(avg_bid, 2),
            "total_won_value": round(sum(won_values), 2),
        }


# ── Singleton ──────────────────────────────────────────────────────────────────
_instance: Optional[UpworkBidder] = None


def get_upwork_bidder() -> UpworkBidder:
    global _instance
    if _instance is None:
        _instance = UpworkBidder()
    return _instance
