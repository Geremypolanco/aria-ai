"""
ARIA Client Acquisition — autonomous client acquisition and lead management system.
Scores leads, generates outreach, and manages the sales pipeline.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_CLIENTS_KEY = "marketplace:clients:v1"
_CLIENTS_TTL = 86400 * 90  # 90 days


@dataclass
class Lead:
    lead_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    company: str = ""
    email: str = ""
    platform: str = ""  # "fiverr", "upwork", "linkedin", "email", "referral"
    niche: str = ""
    pain_points: list = field(default_factory=list)
    budget_estimate_usd: float = 0.0
    lead_score: float = 0.0  # 0-1
    status: str = "new"  # "new"|"contacted"|"qualified"|"proposal_sent"|"closed_won"|"closed_lost"
    source_url: str = ""
    notes: str = ""
    created_at: float = field(default_factory=time.time)
    last_contact_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "lead_id": self.lead_id,
            "name": self.name,
            "company": self.company,
            "email": self.email,
            "platform": self.platform,
            "niche": self.niche,
            "pain_points": self.pain_points,
            "budget_estimate_usd": round(self.budget_estimate_usd, 4),
            "lead_score": round(self.lead_score, 4),
            "status": self.status,
            "source_url": self.source_url,
            "notes": self.notes,
            "created_at": self.created_at,
            "last_contact_at": self.last_contact_at,
        }


@dataclass
class OutreachMessage:
    message_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    lead_id: str = ""
    platform: str = ""
    subject: str = ""
    body: str = ""
    follow_up_day: int = 0  # 0=initial, 3=first follow-up, 7=second follow-up
    sent: bool = False
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "lead_id": self.lead_id,
            "platform": self.platform,
            "subject": self.subject,
            "body": self.body,
            "follow_up_day": self.follow_up_day,
            "sent": self.sent,
            "created_at": self.created_at,
        }


class ClientAcquisition:
    """ARIA's autonomous client acquisition system."""

    def __init__(self) -> None:
        self._leads: list[dict] = []
        self._messages: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_CLIENTS_KEY)
                if data and isinstance(data, dict):
                    self._leads = data.get("leads", [])
                    self._messages = data.get("messages", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(
                _CLIENTS_KEY,
                {"leads": self._leads, "messages": self._messages},
                ttl_seconds=_CLIENTS_TTL,
            )
        except Exception:
            pass

    async def add_lead(
        self,
        name: str,
        company: str,
        email: str,
        platform: str,
        niche: str,
        pain_points: list = None,
        budget: float = 0.0,
    ) -> Lead:
        """Add a new lead to the system."""
        if pain_points is None:
            pain_points = []
        await self._load()
        lead = Lead(
            name=name,
            company=company,
            email=email,
            platform=platform,
            niche=niche,
            pain_points=list(pain_points),
            budget_estimate_usd=budget,
        )
        self._leads.append(lead.to_dict())
        await self._save()
        return lead

    async def score_lead(self, lead_id: str) -> Lead:
        """AI scores lead 0-1 based on pain_points, budget, platform."""
        await self._load()

        lead_data = next((l for l in self._leads if l.get("lead_id") == lead_id), None)
        if not lead_data:
            return Lead()

        pain_points = lead_data.get("pain_points", [])
        budget = lead_data.get("budget_estimate_usd", 0.0)
        platform = lead_data.get("platform", "")
        niche = lead_data.get("niche", "")

        score = 0.5  # default

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system="You are a sales qualification expert. Score leads 0.0-1.0.",
                user=(
                    f"Score this lead from 0.0 (poor) to 1.0 (excellent):\n"
                    f"Platform: {platform}\n"
                    f"Niche: {niche}\n"
                    f"Pain points: {', '.join(pain_points)}\n"
                    f"Budget: ${budget}\n\n"
                    f"Return ONLY a number between 0.0 and 1.0."
                ),
                model=AIModel.FAST,
                max_tokens=50,
            )

            if resp.success:
                content = resp.content.strip()
                # Extract first number from response
                import re

                match = re.search(r"0?\.\d+|1\.0|0|1", content)
                if match:
                    score = min(max(float(match.group()), 0.0), 1.0)
        except Exception:
            pass

        # Also apply heuristic boost
        if budget > 1000:
            score = min(score + 0.1, 1.0)
        if len(pain_points) >= 3:
            score = min(score + 0.1, 1.0)
        if platform in ("upwork", "linkedin"):
            score = min(score + 0.05, 1.0)

        # Update lead in storage
        for i, l in enumerate(self._leads):
            if l.get("lead_id") == lead_id:
                l["lead_score"] = round(score, 4)
                self._leads[i] = l
                break

        await self._save()

        lead = Lead(**{k: v for k, v in lead_data.items() if k in Lead.__dataclass_fields__})
        lead.lead_score = score
        return lead

    async def generate_outreach(self, lead_id: str, service_offered: str) -> OutreachMessage:
        """AI generates personalized outreach message for a lead."""
        await self._load()

        lead_data = next((l for l in self._leads if l.get("lead_id") == lead_id), None)
        if not lead_data:
            return OutreachMessage(lead_id=lead_id, follow_up_day=0)

        name = lead_data.get("name", "there")
        company = lead_data.get("company", "")
        pain_points = lead_data.get("pain_points", [])
        platform = lead_data.get("platform", "email")
        niche = lead_data.get("niche", "")

        subject = f"Help with {niche or 'your business'} — {service_offered}"
        body = (
            f"Hi {name},\n\n"
            f"I noticed you're working in {niche} and could use {service_offered}. "
            f"I help businesses solve {', '.join(pain_points[:2]) if pain_points else 'key challenges'}.\n\n"
            f"Would you be open to a quick call?\n\nBest regards"
        )

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    "You are an expert sales copywriter. Generate personalized, concise outreach messages "
                    "that focus on the prospect's pain points and your value proposition."
                ),
                user=(
                    f"Write a personalized outreach message for:\n"
                    f"Name: {name}\n"
                    f"Company: {company}\n"
                    f"Platform: {platform}\n"
                    f"Niche: {niche}\n"
                    f"Pain points: {', '.join(pain_points)}\n"
                    f"Service offered: {service_offered}\n\n"
                    f'Return JSON: {{"subject": "...", "body": "..."}}'
                ),
                model=AIModel.CREATIVE,
                max_tokens=400,
            )

            if resp.success:
                content = resp.content.strip()
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(content[start:end])
                    subject = data.get("subject", subject)
                    body = data.get("body", body)
        except Exception:
            pass

        message = OutreachMessage(
            lead_id=lead_id,
            platform=platform,
            subject=subject,
            body=body,
            follow_up_day=0,
        )
        self._messages.append(message.to_dict())
        await self._save()
        return message

    async def generate_follow_up_sequence(
        self, lead_id: str, service: str
    ) -> list[OutreachMessage]:
        """Generates 3-message follow-up sequence (day 0, 3, 7)."""
        await self._load()

        lead_data = next((l for l in self._leads if l.get("lead_id") == lead_id), None)
        name = lead_data.get("name", "there") if lead_data else "there"
        platform = lead_data.get("platform", "email") if lead_data else "email"
        niche = lead_data.get("niche", "") if lead_data else ""

        sequence_configs = [
            {"day": 0, "type": "initial"},
            {"day": 3, "type": "first_follow_up"},
            {"day": 7, "type": "second_follow_up"},
        ]

        messages = []
        for config in sequence_configs:
            day = config["day"]
            msg_type = config["type"]

            subject = f"Re: {service} for {niche or 'your business'}"
            if day == 0:
                subject = f"Quick question about {niche or 'your project'}"
                body = f"Hi {name},\n\nI specialize in {service} and think I can help with your {niche} work. Can we connect?\n\nBest"
            elif day == 3:
                body = f"Hi {name},\n\nJust following up on my previous message about {service}. Still interested in helping!\n\nBest"
            else:
                body = f"Hi {name},\n\nLast note — if {service} is something you need in the future, I'm here. No pressure!\n\nBest"

            try:
                ai = get_ai_client()
                resp = await ai.complete(
                    system="You are an expert sales copywriter creating follow-up sequences.",
                    user=(
                        f"Write a {msg_type} message (day {day} of sequence) for:\n"
                        f"Name: {name}, Service: {service}, Niche: {niche}, Platform: {platform}\n"
                        f'Return JSON: {{"subject": "...", "body": "..."}}'
                    ),
                    model=AIModel.FAST,
                    max_tokens=300,
                )

                if resp.success:
                    content = resp.content.strip()
                    start = content.find("{")
                    end = content.rfind("}") + 1
                    if start >= 0 and end > start:
                        data = json.loads(content[start:end])
                        subject = data.get("subject", subject)
                        body = data.get("body", body)
            except Exception:
                pass

            message = OutreachMessage(
                lead_id=lead_id,
                platform=platform,
                subject=subject,
                body=body,
                follow_up_day=day,
            )
            self._messages.append(message.to_dict())
            messages.append(message)

        await self._save()
        return messages

    async def qualify_lead(self, lead_id: str, discovery_notes: str) -> dict:
        """AI qualifies lead based on discovery notes."""
        await self._load()

        lead_data = next((l for l in self._leads if l.get("lead_id") == lead_id), None)
        budget = lead_data.get("budget_estimate_usd", 0.0) if lead_data else 0.0
        niche = lead_data.get("niche", "") if lead_data else ""

        result = {
            "qualified": False,
            "reason": "Insufficient budget or unclear requirements",
            "recommended_service": "consultation",
            "estimated_value_usd": 0.0,
        }
        ai_succeeded = False

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    "You are a sales qualification expert. Determine if a lead is qualified "
                    "based on discovery notes. Return structured JSON."
                ),
                user=(
                    f"Qualify this lead based on discovery:\n"
                    f"Niche: {niche}\n"
                    f"Budget: ${budget}\n"
                    f"Discovery notes: {discovery_notes}\n\n"
                    f'Return JSON: {{"qualified": bool, "reason": str, '
                    f'"recommended_service": str, "estimated_value_usd": float}}'
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
                    result["qualified"] = bool(data.get("qualified", False))
                    result["reason"] = str(data.get("reason", result["reason"]))
                    result["recommended_service"] = str(
                        data.get("recommended_service", "consultation")
                    )
                    result["estimated_value_usd"] = float(data.get("estimated_value_usd", 0.0))
                    ai_succeeded = True
        except Exception:
            pass

        # Heuristic fallback when AI fails or returns no valid data
        if not ai_succeeded and budget >= 500 and len(discovery_notes) > 20:
            result["qualified"] = True
            result["reason"] = "Budget and requirements meet threshold"
            result["estimated_value_usd"] = budget * 0.8

        return result

    def update_lead_status(self, lead_id: str, status: str) -> bool:
        """Update lead status."""
        valid_statuses = {
            "new",
            "contacted",
            "qualified",
            "proposal_sent",
            "closed_won",
            "closed_lost",
        }
        if status not in valid_statuses:
            return False

        for i, l in enumerate(self._leads):
            if l.get("lead_id") == lead_id:
                l["status"] = status
                l["last_contact_at"] = time.time()
                self._leads[i] = l
                return True
        return False

    def hot_leads(self, min_score: float = 0.7) -> list[dict]:
        """Return leads with score >= min_score."""
        return [l for l in self._leads if l.get("lead_score", 0.0) >= min_score]

    def pipeline_report(self) -> dict:
        """Pipeline summary report."""
        by_status: dict[str, int] = {}
        by_platform: dict[str, int] = {}
        pipeline_value = 0.0

        for lead in self._leads:
            status = lead.get("status", "new")
            platform = lead.get("platform", "unknown")
            score = lead.get("lead_score", 0.0)
            budget = lead.get("budget_estimate_usd", 0.0)

            by_status[status] = by_status.get(status, 0) + 1
            by_platform[platform] = by_platform.get(platform, 0) + 1
            pipeline_value += budget * score

        avg_score = sum(l.get("lead_score", 0.0) for l in self._leads) / max(len(self._leads), 1)

        return {
            "total_leads": len(self._leads),
            "by_status": by_status,
            "by_platform": by_platform,
            "pipeline_value_usd": round(pipeline_value, 4),
            "avg_lead_score": round(avg_score, 4),
        }

    def leads_by_platform(self) -> dict:
        """Count leads per platform."""
        result: dict[str, list[dict]] = {}
        for lead in self._leads:
            platform = lead.get("platform", "unknown")
            if platform not in result:
                result[platform] = []
            result[platform].append(lead)
        return result


_instance: ClientAcquisition | None = None


def get_client_acquisition() -> ClientAcquisition:
    global _instance
    if _instance is None:
        _instance = ClientAcquisition()
    return _instance
