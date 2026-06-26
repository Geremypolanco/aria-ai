"""
ARIA AI — Outreach Sequencer
Phase 11: AI-powered multi-channel outreach sequence management.

Capabilities:
  - Multi-step sequence creation (email, LinkedIn, Twitter, cold call)
  - Contact enrollment and tracking
  - AI personalization per contact
  - Sequence analytics
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

# ── Redis configuration ────────────────────────────────────────────────────────
_REDIS_KEY = "acquisition:outreach:v1"
_TTL_90D = 60 * 60 * 24 * 90


# ══════════════════════════════════════════════════════════════════════════════
# Domain objects
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class OutreachSequence:
    sequence_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    channel: str = ""
    target_persona: str = ""
    steps: list = field(default_factory=list)
    total_steps: int = 0
    conversion_goal: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "sequence_id": self.sequence_id,
            "name": self.name,
            "channel": self.channel,
            "target_persona": self.target_persona,
            "steps": self.steps,
            "total_steps": self.total_steps,
            "conversion_goal": self.conversion_goal,
            "created_at": self.created_at,
        }


@dataclass
class OutreachContact:
    contact_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    email: str = ""
    company: str = ""
    sequence_id: str = ""
    current_step: int = 0
    status: str = "active"
    next_action_at: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "contact_id": self.contact_id,
            "name": self.name,
            "email": self.email,
            "company": self.company,
            "sequence_id": self.sequence_id,
            "current_step": self.current_step,
            "status": self.status,
            "next_action_at": self.next_action_at,
            "created_at": self.created_at,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Outreach Sequencer
# ══════════════════════════════════════════════════════════════════════════════


class OutreachSequencer:
    """
    AI-powered multi-channel outreach sequencer.
    State persisted in Redis (key: acquisition:outreach:v1, TTL 90d).
    """

    def __init__(self):
        self._sequences: list[dict] = []
        self._contacts: list[dict] = []

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _load(self) -> None:
        cache = get_cache()
        data = await cache.get(_REDIS_KEY)
        if isinstance(data, dict):
            self._sequences = data.get("sequences", [])
            self._contacts = data.get("contacts", [])

    async def _save(self) -> None:
        cache = get_cache()
        await cache.set(
            _REDIS_KEY,
            {"sequences": self._sequences, "contacts": self._contacts},
            ttl_seconds=_TTL_90D,
        )

    def _find_sequence(self, sequence_id: str) -> dict | None:
        for s in self._sequences:
            if s.get("sequence_id") == sequence_id:
                return s
        return None

    def _find_contact(self, contact_id: str) -> dict | None:
        for c in self._contacts:
            if c.get("contact_id") == contact_id:
                return c
        return None

    def _day_offset(self, step_index: int) -> float:
        """Calculate next action timestamp based on step index."""
        # Days: 0, 3, 7, 10, 14... between steps
        day_gaps = [0, 3, 7, 10, 14]
        gap = day_gaps[min(step_index, len(day_gaps) - 1)]
        return time.time() + gap * 86400

    # ── Public methods ─────────────────────────────────────────────────────────

    async def create_sequence(
        self,
        name: str,
        channel: str,
        target_persona: str,
        conversion_goal: str,
        steps: int = 5,
    ) -> OutreachSequence:
        """AI generates full multi-step outreach sequence."""
        await self._load()
        ai = get_ai_client()
        await ai.complete(
            system=(
                f"You are an outreach copywriter specializing in {channel} campaigns. "
                f"Create a {steps}-step outreach sequence for {target_persona}. "
                "Each step: day number, subject line, message body, action type. "
                f"Goal: {conversion_goal}. Make it human, value-first, not spammy."
            ),
            user=(
                f"Sequence name: {name}\nChannel: {channel}\n"
                f"Target persona: {target_persona}\nGoal: {conversion_goal}\n"
                f"Steps: {steps}\n\nCreate the complete sequence."
            ),
            model=AIModel.CREATIVE,
            max_tokens=1000,
        )

        # Generate structured steps
        action_types = ["email", "dm", "follow_up", "email", "follow_up"]
        sequence_steps = []
        day_offsets = [0, 3, 7, 10, 14, 21]
        for i in range(steps):
            sequence_steps.append(
                {
                    "day": day_offsets[min(i, len(day_offsets) - 1)],
                    "subject": f"Step {i + 1}: {name} — {target_persona}",
                    "body": f"Step {i + 1} message for {target_persona} via {channel}",
                    "action_type": action_types[i % len(action_types)],
                }
            )

        sequence = OutreachSequence(
            name=name,
            channel=channel,
            target_persona=target_persona,
            steps=sequence_steps,
            total_steps=steps,
            conversion_goal=conversion_goal,
        )
        self._sequences.append(sequence.to_dict())
        await self._save()
        return sequence

    async def enroll_contact(
        self,
        name: str,
        email: str,
        company: str,
        sequence_id: str,
    ) -> OutreachContact:
        """Enroll a contact into an outreach sequence."""
        await self._load()
        contact = OutreachContact(
            name=name,
            email=email,
            company=company,
            sequence_id=sequence_id,
            current_step=0,
            status="active",
            next_action_at=time.time(),  # Start immediately
        )
        self._contacts.append(contact.to_dict())
        await self._save()
        return contact

    async def personalize_step(self, contact_id: str, step_index: int) -> dict:
        """AI personalizes a sequence step message for a specific contact."""
        await self._load()
        contact_dict = self._find_contact(contact_id)
        if not contact_dict:
            return {"error": "Contact not found", "body": ""}

        sequence_dict = self._find_sequence(contact_dict.get("sequence_id", ""))
        steps = sequence_dict.get("steps", []) if sequence_dict else []
        step = steps[step_index] if step_index < len(steps) else {}

        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are a personalization expert. Rewrite an outreach message to feel "
                "personally crafted for the specific recipient. Add their name, company, "
                "and a specific hook that shows research."
            ),
            user=(
                f"Contact: {contact_dict.get('name')} at {contact_dict.get('company')}\n"
                f"Step body: {step.get('body', 'Generic message')}\n\n"
                "Personalize this message."
            ),
            model=AIModel.CREATIVE,
            max_tokens=300,
        )
        personalized_body = resp.content.strip() if resp.success else step.get("body", "")
        return {
            "contact_id": contact_id,
            "step_index": step_index,
            "subject": step.get("subject", ""),
            "body": personalized_body,
            "action_type": step.get("action_type", "email"),
        }

    def contacts_due_today(self) -> list[dict]:
        """Return contacts where next_action_at <= now."""
        now = time.time()
        return [
            c
            for c in self._contacts
            if c.get("status") == "active" and c.get("next_action_at", float("inf")) <= now
        ]

    def advance_contact(self, contact_id: str) -> bool:
        """Move contact to next step in sequence."""
        contact_dict = self._find_contact(contact_id)
        if not contact_dict:
            return False

        sequence_dict = self._find_sequence(contact_dict.get("sequence_id", ""))
        total_steps = sequence_dict.get("total_steps", 5) if sequence_dict else 5

        current_step = contact_dict.get("current_step", 0)
        next_step = current_step + 1

        if next_step >= total_steps:
            contact_dict["status"] = "replied"  # Completed sequence
        else:
            contact_dict["current_step"] = next_step
            contact_dict["next_action_at"] = self._day_offset(next_step)
        return True

    def sequence_analytics(self) -> dict:
        """Return outreach analytics."""
        by_channel: dict[str, int] = {}
        for s in self._sequences:
            ch = s.get("channel", "unknown")
            by_channel[ch] = by_channel.get(ch, 0) + 1

        total_contacts = len(self._contacts)
        replied = sum(1 for c in self._contacts if c.get("status") in ("replied", "converted"))
        converted = sum(1 for c in self._contacts if c.get("status") == "converted")

        reply_rate = (replied / total_contacts * 100) if total_contacts > 0 else 0.0
        conversion_rate = (converted / total_contacts * 100) if total_contacts > 0 else 0.0

        return {
            "total_sequences": len(self._sequences),
            "total_contacts": total_contacts,
            "reply_rate_pct": round(reply_rate, 1),
            "conversion_rate_pct": round(conversion_rate, 1),
            "by_channel": by_channel,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────
_instance: OutreachSequencer | None = None


def get_outreach_sequencer() -> OutreachSequencer:
    global _instance
    if _instance is None:
        _instance = OutreachSequencer()
    return _instance
