"""
ARIA AI — Email Nurture Engine
Phase 13: Automated email sequences that convert leads into customers
through value-first nurturing, segmentation, and behavioral triggers.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_KEY = "conversion:email_nurture:v1"
_TTL = 86400 * 60


@dataclass
class NurtureEmail:
    email_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    sequence_id: str = ""
    day_offset: int = 0           # days after sequence start
    subject: str = ""
    preview_text: str = ""        # ≤90 chars
    body: str = ""
    goal: str = ""               # "build_trust" | "educate" | "social_proof" | "offer" | "urgency"
    cta: str = ""
    cta_url_placeholder: str = "{{cta_url}}"
    expected_open_rate_pct: float = 0.0
    expected_click_rate_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "email_id": self.email_id,
            "sequence_id": self.sequence_id,
            "day_offset": self.day_offset,
            "subject": self.subject,
            "preview_text": self.preview_text,
            "body": self.body,
            "goal": self.goal,
            "cta": self.cta,
            "cta_url_placeholder": self.cta_url_placeholder,
            "expected_open_rate_pct": self.expected_open_rate_pct,
            "expected_click_rate_pct": self.expected_click_rate_pct,
        }


@dataclass
class NurtureSequence:
    sequence_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    niche: str = ""
    goal: str = ""               # "convert_to_customer" | "upsell" | "reactivate" | "onboard"
    target_audience: str = ""
    emails: list = field(default_factory=list)   # list of NurtureEmail.to_dict()
    total_emails: int = 0
    sequence_duration_days: int = 0
    expected_conversion_rate_pct: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "sequence_id": self.sequence_id,
            "name": self.name,
            "niche": self.niche,
            "goal": self.goal,
            "target_audience": self.target_audience,
            "emails": self.emails,
            "total_emails": self.total_emails,
            "sequence_duration_days": self.sequence_duration_days,
            "expected_conversion_rate_pct": self.expected_conversion_rate_pct,
            "created_at": self.created_at,
        }


# Day offsets and goals for a standard 7-email nurture sequence
_SEQUENCE_TEMPLATE = [
    (0,  "build_trust",   "Welcome + immediate value", 45.0, 8.0),
    (2,  "educate",       "Teach one powerful concept", 35.0, 6.0),
    (4,  "social_proof",  "Case study or testimonial",  32.0, 5.5),
    (6,  "educate",       "Address biggest objection",  30.0, 5.0),
    (8,  "offer",         "Introduce paid offer",       28.0, 7.0),
    (10, "urgency",       "Soft deadline reminder",     33.0, 9.0),
    (12, "urgency",       "Final call — last chance",   38.0, 11.0),
]


class EmailNurtureEngine:
    """
    Automated email nurture sequence engine.
    State persisted in Redis (key: conversion:email_nurture:v1, TTL 60d).
    """

    def __init__(self) -> None:
        self._sequences: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    self._sequences = data.get("sequences", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_KEY, {"sequences": self._sequences[-200:]}, ttl_seconds=_TTL)
        except Exception:
            pass

    async def create_sequence(
        self,
        niche: str,
        goal: str,
        target_audience: str,
        num_emails: int = 7,
        offer_name: str = "",
    ) -> NurtureSequence:
        """AI writes a full email nurture sequence."""
        await self._load()
        sequence = NurtureSequence(
            name=f"{niche.title()} {goal.replace('_', ' ').title()} Sequence",
            niche=niche,
            goal=goal,
            target_audience=target_audience,
        )

        ai = get_ai_client()
        emails = []
        template = _SEQUENCE_TEMPLATE[:num_emails]

        try:
            resp = await ai.complete(
                system=(
                    "You are an email marketing expert. Write a complete email nurture sequence. "
                    f"For each email provide: SUBJECT (curiosity/benefit), PREVIEW (≤90 chars), BODY (200-300 words), CTA (action phrase). "
                    "Separate emails with ---."
                ),
                user=(
                    f"Niche: {niche}\nGoal: {goal}\nAudience: {target_audience}\n"
                    f"Offer: {offer_name or niche + ' solution'}\n"
                    f"Write {num_emails} emails for a nurture sequence."
                ),
                model=AIModel.CREATIVE,
                max_tokens=1500,
            )
            if resp.success:
                email_blocks = resp.content.split("---")
                for i, (day, email_goal, purpose, open_rate, click_rate) in enumerate(template):
                    body_text = email_blocks[i].strip() if i < len(email_blocks) else ""
                    lines = [l.strip() for l in body_text.split("\n") if l.strip()]
                    subject = lines[0].replace("SUBJECT:", "").strip() if lines else f"Day {day}: {purpose}"
                    preview = lines[1].replace("PREVIEW:", "").strip()[:90] if len(lines) > 1 else f"{niche} insight for {target_audience}"
                    body = body_text if body_text else f"Here's your day {day} value from ARIA."
                    cta_line = [l for l in lines if "CTA:" in l or "cta:" in l.lower()]
                    cta = cta_line[0].replace("CTA:", "").strip() if cta_line else "Click here to learn more"

                    email = NurtureEmail(
                        sequence_id=sequence.sequence_id,
                        day_offset=day,
                        subject=subject,
                        preview_text=preview,
                        body=body,
                        goal=email_goal,
                        cta=cta,
                        expected_open_rate_pct=open_rate,
                        expected_click_rate_pct=click_rate,
                    )
                    emails.append(email)
        except Exception:
            pass

        if not emails:
            for day, email_goal, purpose, open_rate, click_rate in template:
                subjects = {
                    "build_trust": f"Welcome to your {niche} journey 👋",
                    "educate": f"The #{day} thing {target_audience} get wrong about {niche}",
                    "social_proof": f"How [Name] got results with {niche} in 30 days",
                    "offer": f"Ready to get serious about {niche}?",
                    "urgency": f"Last chance — your {offer_name or niche} offer expires soon",
                }
                email = NurtureEmail(
                    sequence_id=sequence.sequence_id,
                    day_offset=day,
                    subject=subjects.get(email_goal, f"Day {day}: {purpose}"),
                    preview_text=f"Quick {niche} tip inside — 2 minute read",
                    body=f"Here's your day {day} {niche} value. {purpose}. This will help you {goal.replace('_', ' ')}.",
                    goal=email_goal,
                    cta="Read the full guide →",
                    expected_open_rate_pct=open_rate,
                    expected_click_rate_pct=click_rate,
                )
                emails.append(email)

        sequence.emails = [e.to_dict() for e in emails]
        sequence.total_emails = len(emails)
        sequence.sequence_duration_days = max((e.day_offset for e in emails), default=0)
        sequence.expected_conversion_rate_pct = round(
            sum(e.expected_click_rate_pct for e in emails) / max(len(emails), 1) * 0.3, 2
        )

        self._sequences.append(sequence.to_dict())
        await self._save()
        return sequence

    async def personalize_email(self, email: NurtureEmail, subscriber_name: str, subscriber_data: dict) -> NurtureEmail:
        """AI personalizes a template email for a specific subscriber."""
        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system="You are an email personalization expert. Rewrite the email subject to feel personal and relevant.",
                user=(
                    f"Subscriber: {subscriber_name}, Data: {subscriber_data}\n"
                    f"Original subject: {email.subject}\n"
                    "Personalize the subject line only. Keep it ≤60 chars."
                ),
                model=AIModel.FAST,
                max_tokens=80,
            )
            if resp.success:
                personalized_subject = resp.content.strip().split("\n")[0][:60]
                email.subject = personalized_subject
        except Exception:
            pass

        email.body = email.body.replace("{{first_name}}", subscriber_name).replace("{{name}}", subscriber_name)
        return email

    async def create_reactivation_sequence(self, niche: str, inactive_days: int = 30) -> NurtureSequence:
        """3-email win-back sequence for inactive subscribers."""
        return await self.create_sequence(
            niche=niche,
            goal="reactivate",
            target_audience=f"inactive subscribers ({inactive_days}+ days)",
            num_emails=3,
            offer_name=f"{niche} win-back offer",
        )

    def sequence_analytics(self) -> dict:
        total = len(self._sequences)
        avg_emails = sum(s.get("total_emails", 0) for s in self._sequences) / max(total, 1)
        avg_cvr = sum(s.get("expected_conversion_rate_pct", 0.0) for s in self._sequences) / max(total, 1)
        by_goal: dict = {}
        for s in self._sequences:
            g = s.get("goal", "unknown")
            by_goal[g] = by_goal.get(g, 0) + 1
        return {
            "total_sequences": total,
            "avg_emails_per_sequence": round(avg_emails, 1),
            "avg_expected_cvr_pct": round(avg_cvr, 2),
            "by_goal": by_goal,
        }

    def recent_sequences(self, limit: int = 10) -> list[dict]:
        return sorted(self._sequences, key=lambda x: x.get("created_at", 0), reverse=True)[:limit]


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: Optional[EmailNurtureEngine] = None


def get_email_nurture_engine() -> EmailNurtureEngine:
    global _instance
    if _instance is None:
        _instance = EmailNurtureEngine()
    return _instance
