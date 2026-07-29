"""
ARIA AI — Post-Sale Delivery Engine
Aria Revenue Engine, Phase 1: closes the one gap nothing else in the
acquisition/CRM/lead stack covers — once a deal is actually sold, something
has to send the buyer what they paid for, without a human manually
copy-pasting a link into an email every time.

Deliberately narrow, and deliberately NOT another content generator:
  - register_deliverable() is the only place new deliverable content enters
    the system, and it runs the same Layer 3 content-safety check used by
    send_email/post_to_social (apps/core/safety/guardrails.check_content_safety)
    once, at registration — because that's the one point a human is actually
    deciding what this SKU sends out. deliver() itself never generates or
    alters content; it only looks up what was already registered and sends
    it verbatim, so a real purchase is never left waiting on a chat turn.
  - deliver() refuses (records a "no_deliverable" outcome, never guesses or
    fabricates a delivery) when the sku wasn't registered — no silent no-op,
    no invented placeholder content sent to a paying customer.

Sends through PublishingTools.send_newsletter — the same real provider
stack (Resend → SendGrid → Mailgun) already used by aria_mind.py's
send_email tool — so a delivered product goes out over the same audited
path, not a second bespoke send mechanism.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache

logger = logging.getLogger("aria.acquisition.delivery")

_KEY = "acquisition:delivery:v1"
_TTL = 86400 * 365


@dataclass
class Deliverable:
    sku: str = ""
    name: str = ""
    price_usd: float = 0.0
    delivery_type: str = "link"  # "link" | "text"
    content: str = ""  # a URL (delivery_type=link) or the full message body (delivery_type=text)
    registered_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "sku": self.sku,
            "name": self.name,
            "price_usd": self.price_usd,
            "delivery_type": self.delivery_type,
            "content": self.content,
            "registered_at": self.registered_at,
        }


@dataclass
class DeliveryRecord:
    record_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    sku: str = ""
    buyer_email: str = ""
    buyer_name: str = ""
    order_ref: str = ""
    status: str = "pending"  # sent | failed | no_deliverable
    detail: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "sku": self.sku,
            "buyer_email": self.buyer_email,
            "buyer_name": self.buyer_name,
            "order_ref": self.order_ref,
            "status": self.status,
            "detail": self.detail,
            "created_at": self.created_at,
        }


class DeliveryEngine:
    """
    Registry of sellable deliverables + a log of what's actually been sent.
    State persisted in Redis (key: acquisition:delivery:v1, TTL 365d).
    """

    def __init__(self) -> None:
        self._deliverables: dict[str, dict] = {}
        self._records: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_KEY)
            if isinstance(data, dict):
                self._deliverables = data.get("deliverables", {})
                self._records = data.get("records", [])
        except Exception as exc:
            logger.warning("DeliveryEngine._load failed: %s", exc)
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(
                _KEY,
                {"deliverables": self._deliverables, "records": self._records[-500:]},
                ttl_seconds=_TTL,
            )
        except Exception as exc:
            logger.warning("DeliveryEngine._save failed: %s", exc)

    async def register_deliverable(
        self,
        sku: str,
        name: str,
        content: str,
        delivery_type: str = "link",
        price_usd: float = 0.0,
    ) -> dict:
        """Register what a SKU actually sends the buyer. Runs the shared
        content-safety firewall once here, since this is the only point a
        human decides what will later be sent fully automatically."""
        await self._load()
        if not sku or not name or not content:
            return {"success": False, "error": "sku, name, and content are all required"}
        if delivery_type not in ("link", "text"):
            return {"success": False, "error": "delivery_type must be 'link' or 'text'"}

        from apps.core.config import settings as _guardrail_settings
        from apps.core.safety import guardrails

        if getattr(_guardrail_settings, "GUARDRAILS_ENABLED", True):
            safety = guardrails.check_content_safety(f"{name}\n{content}")
            if not safety.safe:
                return {
                    "success": False,
                    "error": f"Blocked pattern: {'; '.join(safety.findings)}",
                }

        deliverable = Deliverable(
            sku=sku,
            name=name,
            price_usd=price_usd,
            delivery_type=delivery_type,
            content=content,
        )
        self._deliverables[sku] = deliverable.to_dict()
        await self._save()
        return {"success": True, "deliverable": deliverable.to_dict()}

    async def deliver(
        self,
        sku: str,
        buyer_email: str,
        buyer_name: str = "",
        order_ref: str = "",
    ) -> DeliveryRecord:
        """Send whatever was registered for `sku` to `buyer_email`, and log
        the outcome. Never invents content for a sku that wasn't registered.

        Idempotent per (sku, order_ref): a repeat call for an order that was
        already confirmed sent returns that same stored record instead of
        sending again — an ambiguous or automated retry (e.g. aria_mind.py's
        generic failure-retry loop) must never risk a second real email for
        one purchase. A prior "failed"/"no_deliverable" outcome never sent
        anything, so it doesn't block a fresh attempt."""
        await self._load()

        if order_ref:
            for existing in self._records:
                if (
                    existing.get("sku") == sku
                    and existing.get("order_ref") == order_ref
                    and existing.get("status") == "sent"
                ):
                    return DeliveryRecord(**existing)

        record = DeliveryRecord(
            sku=sku, buyer_email=buyer_email, buyer_name=buyer_name, order_ref=order_ref
        )

        if not buyer_email:
            record.status = "failed"
            record.detail = "No buyer_email provided"
            self._records.append(record.to_dict())
            await self._save()
            return record

        deliverable = self._deliverables.get(sku)
        if not deliverable:
            record.status = "no_deliverable"
            record.detail = f"No deliverable registered for sku '{sku}'"
            self._records.append(record.to_dict())
            await self._save()
            logger.warning("DeliveryEngine.deliver: %s", record.detail)
            return record

        greeting = f"Hi {buyer_name},\n\n" if buyer_name else "Hi,\n\n"
        if deliverable["delivery_type"] == "link":
            body = f"{greeting}Thanks for your purchase — here's your {deliverable['name']}:\n\n{deliverable['content']}"
        else:
            body = f"{greeting}Thanks for your purchase — here's your {deliverable['name']}:\n\n{deliverable['content']}"
        subject = f"Your {deliverable['name']} is ready"

        from apps.core.tools.publishing_tools import PublishingTools

        try:
            result = await PublishingTools().send_newsletter(subject, body, to_override=buyer_email)
        except Exception as exc:
            result = {"success": False, "error": str(exc)}

        if result.get("success"):
            record.status = "sent"
            record.detail = f"via {result.get('provider', 'email')}"
        else:
            record.status = "failed"
            record.detail = result.get("error", "unknown error")

        self._records.append(record.to_dict())
        await self._save()
        return record

    def get_deliverable(self, sku: str) -> dict | None:
        return self._deliverables.get(sku)

    def list_deliverables(self) -> list[dict]:
        return list(self._deliverables.values())

    def recent_deliveries(self, limit: int = 10) -> list[dict]:
        return sorted(self._records, key=lambda r: r.get("created_at", 0), reverse=True)[:limit]

    def delivery_stats(self) -> dict:
        total = len(self._records)
        sent = sum(1 for r in self._records if r.get("status") == "sent")
        failed = sum(1 for r in self._records if r.get("status") == "failed")
        no_deliverable = sum(1 for r in self._records if r.get("status") == "no_deliverable")
        return {
            "total_deliverables_registered": len(self._deliverables),
            "total_delivery_attempts": total,
            "sent": sent,
            "failed": failed,
            "no_deliverable": no_deliverable,
            "success_rate_pct": round(sent / total * 100, 1) if total else 0.0,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: DeliveryEngine | None = None


def get_delivery_engine() -> DeliveryEngine:
    global _instance
    if _instance is None:
        _instance = DeliveryEngine()
    return _instance
