"""
ARIA AI — CRM Engine
Phase 13: Pipeline tracking, interaction logging, and revenue attribution
for all acquisition channels.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_KEY = "acquisition:crm:v1"
_TTL = 86400 * 90

_PIPELINE_STAGES = [
    "new",
    "contacted",
    "qualified",
    "proposal",
    "negotiation",
    "closed_won",
    "closed_lost",
]


@dataclass
class CRMContact:
    contact_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    company: str = ""
    email: str = ""
    phone: str = ""
    niche: str = ""
    source: str = ""
    stage: str = "new"
    deal_value_usd: float = 0.0
    probability_pct: float = 10.0
    weighted_value_usd: float = 0.0
    interactions: list = field(default_factory=list)
    next_action: str = ""
    next_action_date: float = 0.0
    tags: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "contact_id": self.contact_id,
            "name": self.name,
            "company": self.company,
            "email": self.email,
            "phone": self.phone,
            "niche": self.niche,
            "source": self.source,
            "stage": self.stage,
            "deal_value_usd": self.deal_value_usd,
            "probability_pct": self.probability_pct,
            "weighted_value_usd": self.weighted_value_usd,
            "interactions": self.interactions,
            "next_action": self.next_action,
            "next_action_date": self.next_action_date,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# Stage → default win probability
_STAGE_PROBABILITY: dict[str, float] = {
    "new": 5.0,
    "contacted": 15.0,
    "qualified": 30.0,
    "proposal": 50.0,
    "negotiation": 70.0,
    "closed_won": 100.0,
    "closed_lost": 0.0,
}


class CRMEngine:
    """
    Sales CRM with pipeline tracking and AI-generated next actions.
    State persisted in Redis (key: acquisition:crm:v1, TTL 90d).
    """

    def __init__(self) -> None:
        self._contacts: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    self._contacts = data.get("contacts", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_KEY, {"contacts": self._contacts[-1000:]}, ttl_seconds=_TTL)
        except Exception:
            pass

    async def add_contact(
        self,
        name: str,
        company: str,
        email: str = "",
        niche: str = "",
        source: str = "outreach",
        deal_value_usd: float = 500.0,
    ) -> CRMContact:
        """Add new contact to CRM pipeline."""
        await self._load()
        prob = _STAGE_PROBABILITY["new"]
        contact = CRMContact(
            name=name,
            company=company,
            email=email,
            niche=niche,
            source=source,
            stage="new",
            deal_value_usd=deal_value_usd,
            probability_pct=prob,
            weighted_value_usd=round(deal_value_usd * prob / 100, 2),
        )
        self._contacts.append(contact.to_dict())
        await self._save()
        return contact

    async def advance_stage(self, contact_id: str) -> dict | None:
        """Move contact to next pipeline stage, update probability."""
        await self._load()
        for contact in self._contacts:
            if contact.get("contact_id") == contact_id:
                current = contact.get("stage", "new")
                if current in _PIPELINE_STAGES:
                    idx = _PIPELINE_STAGES.index(current)
                    if idx < len(_PIPELINE_STAGES) - 1:
                        new_stage = _PIPELINE_STAGES[idx + 1]
                        contact["stage"] = new_stage
                        prob = _STAGE_PROBABILITY.get(new_stage, 10.0)
                        contact["probability_pct"] = prob
                        contact["weighted_value_usd"] = round(
                            contact.get("deal_value_usd", 0.0) * prob / 100, 2
                        )
                        contact["updated_at"] = time.time()
                        await self._save()
                return contact
        return None

    async def log_interaction(
        self,
        contact_id: str,
        interaction_type: str,
        note: str,
        outcome: str = "",
    ) -> bool:
        """Log a touchpoint (call, email, meeting, demo) for a contact."""
        await self._load()
        for contact in self._contacts:
            if contact.get("contact_id") == contact_id:
                interaction = {
                    "id": str(uuid.uuid4())[:8],
                    "type": interaction_type,
                    "note": note,
                    "outcome": outcome,
                    "timestamp": time.time(),
                }
                contact.setdefault("interactions", []).append(interaction)
                contact["updated_at"] = time.time()
                await self._save()
                return True
        return False

    async def suggest_next_action(self, contact_id: str) -> str:
        """AI suggests the best next sales action for a contact."""
        await self._load()
        contact = next((c for c in self._contacts if c.get("contact_id") == contact_id), None)
        if not contact:
            return "No contact found"

        ai = get_ai_client()
        try:
            interactions = contact.get("interactions", [])
            stage = contact.get("stage", "new")
            resp = await ai.complete(
                system="You are a sales coach. Suggest the single best next action to move this deal forward.",
                user=(
                    f"Contact: {contact.get('name')}, Company: {contact.get('company')}, "
                    f"Stage: {stage}, Interactions so far: {len(interactions)}. "
                    "What is the best next action? Be specific (e.g., 'Send case study + book demo')."
                ),
                model=AIModel.FAST,
                max_tokens=100,
            )
            if resp.success:
                action = resp.content.strip().split("\n")[0]
                for c in self._contacts:
                    if c.get("contact_id") == contact_id:
                        c["next_action"] = action
                        c["next_action_date"] = time.time() + 86400
                        break
                await self._save()
                return action
        except Exception:
            pass

        stage_actions = {
            "new": "Send personalized outreach email with one specific pain point addressed",
            "contacted": "Follow up with a case study relevant to their niche",
            "qualified": "Schedule a 20-minute discovery call",
            "proposal": "Send detailed proposal with ROI projections",
            "negotiation": "Offer a 30-day pilot at reduced rate to remove risk",
        }
        return stage_actions.get(contact.get("stage", "new"), "Follow up with value-add content")

    def contacts_by_stage(self, stage: str) -> list[dict]:
        return [c for c in self._contacts if c.get("stage") == stage]

    def pipeline_value(self) -> dict:
        total_weighted = sum(c.get("weighted_value_usd", 0.0) for c in self._contacts)
        total_potential = sum(c.get("deal_value_usd", 0.0) for c in self._contacts)
        won = sum(
            c.get("deal_value_usd", 0.0) for c in self._contacts if c.get("stage") == "closed_won"
        )
        return {
            "total_potential_usd": round(total_potential, 2),
            "weighted_pipeline_usd": round(total_weighted, 2),
            "closed_won_usd": round(won, 2),
        }

    def crm_dashboard(self) -> dict:
        by_stage: dict = {}
        by_source: dict = {}
        for c in self._contacts:
            s = c.get("stage", "new")
            by_stage[s] = by_stage.get(s, 0) + 1
            src = c.get("source", "unknown")
            by_source[src] = by_source.get(src, 0) + 1
        return {
            "total_contacts": len(self._contacts),
            "by_stage": by_stage,
            "by_source": by_source,
            **self.pipeline_value(),
        }

    def recent_contacts(self, limit: int = 10) -> list[dict]:
        return sorted(self._contacts, key=lambda x: x.get("updated_at", 0), reverse=True)[:limit]


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: CRMEngine | None = None


def get_crm_engine() -> CRMEngine:
    global _instance
    if _instance is None:
        _instance = CRMEngine()
    return _instance
