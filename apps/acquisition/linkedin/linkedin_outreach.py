"""
ARIA AI — LinkedIn Outreach
Phase 11: AI-powered LinkedIn prospecting and outreach automation.

Capabilities:
  - Prospect management and scoring
  - Personalized connection requests
  - Multi-step outreach sequences
  - Pipeline analytics
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

# ── Redis configuration ────────────────────────────────────────────────────────
_REDIS_KEY = "acquisition:linkedin:v1"
_TTL_90D = 60 * 60 * 24 * 90


# ══════════════════════════════════════════════════════════════════════════════
# Domain objects
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class LinkedInProspect:
    prospect_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    title: str = ""
    company: str = ""
    industry: str = ""
    connection_degree: int = 2
    pain_point_hypothesis: str = ""
    relevance_score: float = 0.0
    status: str = "identified"
    notes: str = ""
    profile_url: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "prospect_id": self.prospect_id,
            "name": self.name,
            "title": self.title,
            "company": self.company,
            "industry": self.industry,
            "connection_degree": self.connection_degree,
            "pain_point_hypothesis": self.pain_point_hypothesis,
            "relevance_score": self.relevance_score,
            "status": self.status,
            "notes": self.notes,
            "profile_url": self.profile_url,
            "created_at": self.created_at,
        }


@dataclass
class LinkedInMessage:
    message_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    prospect_id: str = ""
    message_type: str = ""
    subject: str = ""
    body: str = ""
    personalization_hooks: list = field(default_factory=list)
    sent: bool = False
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "prospect_id": self.prospect_id,
            "message_type": self.message_type,
            "subject": self.subject,
            "body": self.body,
            "personalization_hooks": self.personalization_hooks,
            "sent": self.sent,
            "created_at": self.created_at,
        }


# ══════════════════════════════════════════════════════════════════════════════
# LinkedIn Outreach
# ══════════════════════════════════════════════════════════════════════════════

class LinkedInOutreach:
    """
    AI-powered LinkedIn outreach system.
    State persisted in Redis (key: acquisition:linkedin:v1, TTL 90d).
    """

    def __init__(self):
        self._prospects: list[dict] = []
        self._messages: list[dict] = []

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _load(self) -> None:
        cache = get_cache()
        data = await cache.get(_REDIS_KEY)
        if isinstance(data, dict):
            self._prospects = data.get("prospects", [])
            self._messages = data.get("messages", [])

    async def _save(self) -> None:
        cache = get_cache()
        await cache.set(
            _REDIS_KEY,
            {"prospects": self._prospects, "messages": self._messages},
            ttl_seconds=_TTL_90D,
        )

    def _find_prospect(self, prospect_id: str) -> Optional[dict]:
        for p in self._prospects:
            if p.get("prospect_id") == prospect_id:
                return p
        return None

    # ── Public methods ─────────────────────────────────────────────────────────

    async def add_prospect(
        self,
        name: str,
        title: str,
        company: str,
        industry: str,
        profile_url: str = "",
    ) -> LinkedInProspect:
        """Add a new prospect to the pipeline."""
        await self._load()
        prospect = LinkedInProspect(
            name=name,
            title=title,
            company=company,
            industry=industry,
            profile_url=profile_url,
        )
        self._prospects.append(prospect.to_dict())
        await self._save()
        return prospect

    async def score_prospect(
        self, prospect_id: str, service_offered: str
    ) -> LinkedInProspect:
        """AI scores prospect relevance 0-1."""
        await self._load()
        prospect_dict = self._find_prospect(prospect_id)
        if not prospect_dict:
            return LinkedInProspect(prospect_id=prospect_id)

        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are a B2B sales qualifier. Score a prospect's relevance (0.0 to 1.0) "
                "based on their role, company, industry, and how well they match the service. "
                "Also identify their likely pain point. Be concise."
            ),
            user=(
                f"Prospect: {prospect_dict.get('name')}, {prospect_dict.get('title')} at {prospect_dict.get('company')}\n"
                f"Industry: {prospect_dict.get('industry')}\n"
                f"Service offered: {service_offered}\n\n"
                "Score relevance (0-1) and identify pain point."
            ),
            model=AIModel.FAST,
            max_tokens=200,
        )

        # Extract score from response
        score = 0.7  # default
        if resp.success:
            content = resp.content
            for token in content.split():
                try:
                    val = float(token.strip(".,()"))
                    if 0.0 <= val <= 1.0:
                        score = val
                        break
                except ValueError:
                    pass

        prospect_dict["relevance_score"] = round(score, 2)
        prospect_dict["pain_point_hypothesis"] = resp.content[:200] if resp.success else f"Needs {service_offered}"
        await self._save()

        return LinkedInProspect(**{k: prospect_dict[k] for k in LinkedInProspect.__dataclass_fields__ if k in prospect_dict})

    async def generate_connection_request(
        self, prospect_id: str, service: str
    ) -> LinkedInMessage:
        """AI generates personalized <300 char connection note."""
        await self._load()
        prospect_dict = self._find_prospect(prospect_id)
        name = prospect_dict.get("name", "there") if prospect_dict else "there"
        company = prospect_dict.get("company", "") if prospect_dict else ""
        title = prospect_dict.get("title", "") if prospect_dict else ""

        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are a LinkedIn connection expert. Write a personalized connection request "
                "note that is under 300 characters. Be genuine, specific, and value-focused. "
                "No generic pitches. Reference their role or company specifically."
            ),
            user=(
                f"Prospect: {name}, {title} at {company}\n"
                f"Service: {service}\n\n"
                "Write connection request (under 300 chars)."
            ),
            model=AIModel.CREATIVE,
            max_tokens=100,
        )
        body = resp.content.strip() if resp.success else f"Hi {name}, I help {title}s like you with {service}. Would love to connect!"
        # Enforce 300 char limit
        if len(body) > 299:
            body = body[:296] + "..."

        msg = LinkedInMessage(
            prospect_id=prospect_id,
            message_type="connection_request",
            subject="Connection Request",
            body=body,
            personalization_hooks=[name, company],
        )
        self._messages.append(msg.to_dict())
        await self._save()
        return msg

    async def generate_outreach_sequence(
        self, prospect_id: str, service: str
    ) -> list[LinkedInMessage]:
        """Generate 4-message sequence: connection, intro, follow-up-1, follow-up-2."""
        await self._load()
        prospect_dict = self._find_prospect(prospect_id)
        name = prospect_dict.get("name", "there") if prospect_dict else "there"
        company = prospect_dict.get("company", "") if prospect_dict else ""

        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are a B2B outreach copywriter. Write a 4-message LinkedIn sequence: "
                "1) Connection request (under 300 chars), "
                "2) Intro message (value-first, no pitch), "
                "3) Follow-up 1 (share relevant insight), "
                "4) Follow-up 2 (soft CTA). "
                "Each message on a new line starting with 'MSG1:', 'MSG2:', 'MSG3:', 'MSG4:'."
            ),
            user=(
                f"Prospect: {name} at {company}\n"
                f"Service: {service}\n\n"
                "Write the 4-message sequence."
            ),
            model=AIModel.STRATEGY,
            max_tokens=600,
        )
        content = resp.content if resp.success else ""

        message_types = ["connection_request", "intro", "follow_up_1", "follow_up_2"]
        subjects = ["Connection", "Thought you'd find this useful", "Following up", "Last touch"]

        # Try to parse MSG1-MSG4 format
        msg_bodies = {}
        if content:
            for i in range(1, 5):
                key = f"MSG{i}:"
                if key in content:
                    start = content.find(key) + len(key)
                    next_key = f"MSG{i+1}:"
                    end = content.find(next_key) if next_key in content else len(content)
                    msg_bodies[i] = content[start:end].strip()

        messages = []
        for i, (msg_type, subject) in enumerate(zip(message_types, subjects)):
            body = msg_bodies.get(i + 1, f"Message {i+1} for {name} about {service}")
            if msg_type == "connection_request" and len(body) > 299:
                body = body[:296] + "..."
            msg = LinkedInMessage(
                prospect_id=prospect_id,
                message_type=msg_type,
                subject=subject,
                body=body,
                personalization_hooks=[name, company],
            )
            self._messages.append(msg.to_dict())
            messages.append(msg)

        await self._save()
        return messages

    def update_prospect_status(self, prospect_id: str, status: str) -> bool:
        """Update prospect status in pipeline."""
        for p in self._prospects:
            if p.get("prospect_id") == prospect_id:
                p["status"] = status
                return True
        return False

    def hot_prospects(self, min_score: float = 0.7) -> list[dict]:
        """Return prospects with relevance score >= min_score."""
        return [p for p in self._prospects if p.get("relevance_score", 0.0) >= min_score]

    def outreach_analytics(self) -> dict:
        """Return outreach analytics."""
        by_status: dict[str, int] = {}
        scores = []
        for p in self._prospects:
            status = p.get("status", "identified")
            by_status[status] = by_status.get(status, 0) + 1
            scores.append(p.get("relevance_score", 0.0))

        total = len(self._prospects)
        connected = by_status.get("connected", 0) + by_status.get("messaged", 0) + by_status.get("replied", 0) + by_status.get("qualified", 0)
        replied = by_status.get("replied", 0) + by_status.get("qualified", 0)
        connection_sent = by_status.get("connection_sent", 0)

        avg_score = sum(scores) / len(scores) if scores else 0.0
        connection_rate = (connected / connection_sent * 100) if connection_sent > 0 else 0.0
        reply_rate = (replied / max(connected, 1) * 100)

        return {
            "total_prospects": total,
            "by_status": by_status,
            "avg_relevance_score": round(avg_score, 3),
            "connection_rate_pct": round(connection_rate, 1),
            "reply_rate_pct": round(reply_rate, 1),
        }


# ── Singleton ──────────────────────────────────────────────────────────────────
_instance: Optional[LinkedInOutreach] = None


def get_linkedin_outreach() -> LinkedInOutreach:
    global _instance
    if _instance is None:
        _instance = LinkedInOutreach()
    return _instance
