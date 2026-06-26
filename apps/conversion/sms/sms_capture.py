"""
SMS Capture Engine — SMS opt-in capture with Klaviyo SMS integration stub.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_SMS_KEY = "conversion:sms:v1"
_SMS_TTL = 86400 * 90  # 90 days
_MAX_SUBSCRIBERS = 10000


@dataclass
class SMSSubscriber:
    subscriber_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    phone: str = ""
    name: str = ""
    opted_in: bool = True
    source: str = ""  # "popup", "checkout", "quiz", "campaign"
    tags: list = field(default_factory=list)
    klaviyo_synced: bool = False
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "subscriber_id": self.subscriber_id,
            "phone": self.phone,
            "name": self.name,
            "opted_in": self.opted_in,
            "source": self.source,
            "tags": self.tags,
            "klaviyo_synced": self.klaviyo_synced,
            "created_at": self.created_at,
        }


@dataclass
class SMSMessage:
    message_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    subscriber_id: str = ""
    message_type: str = ""  # "welcome", "promo", "cart_recovery", "reengagement", "flash_sale"
    body: str = ""  # MAX 160 chars for single SMS
    sent: bool = False
    sent_at: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "subscriber_id": self.subscriber_id,
            "message_type": self.message_type,
            "body": self.body,
            "sent": self.sent,
            "sent_at": self.sent_at,
            "created_at": self.created_at,
        }


class SMSCaptureEngine:
    """SMS opt-in capture with Klaviyo SMS integration."""

    def __init__(self) -> None:
        self._subscribers: list[dict] = []
        self._messages: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_SMS_KEY)
                if isinstance(data, dict):
                    self._subscribers = data.get("subscribers", [])
                    self._messages = data.get("messages", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(
                _SMS_KEY,
                {
                    "subscribers": self._subscribers[-_MAX_SUBSCRIBERS:],
                    "messages": self._messages[-5000:],
                },
                ttl_seconds=_SMS_TTL,
            )
        except Exception:
            pass

    async def capture(
        self,
        phone: str,
        source: str,
        name: str = "",
        tags: list = None,
    ) -> SMSSubscriber:
        """Capture an SMS opt-in subscriber."""
        if tags is None:
            tags = []
        await self._load()

        klaviyo_synced = False
        klaviyo_key = os.environ.get("KLAVIYO_PRIVATE_KEY", "")
        if klaviyo_key:
            sub_temp = SMSSubscriber(phone=phone, name=name, source=source, tags=list(tags))
            klaviyo_synced = await self._sync_to_klaviyo(sub_temp)

        subscriber = SMSSubscriber(
            phone=phone,
            name=name,
            opted_in=True,
            source=source,
            tags=list(tags),
            klaviyo_synced=klaviyo_synced,
        )

        self._subscribers.append(subscriber.to_dict())
        await self._save()
        return subscriber

    async def _sync_to_klaviyo(self, subscriber: SMSSubscriber) -> bool:
        """Sync subscriber to Klaviyo SMS list. Gracefully degrades if key not set."""
        klaviyo_key = os.environ.get("KLAVIYO_PRIVATE_KEY", "")
        if not klaviyo_key:
            return False
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://a.klaviyo.com/api/profiles/",
                    json={
                        "data": {
                            "type": "profile",
                            "attributes": {
                                "phone_number": subscriber.phone,
                                "first_name": subscriber.name,
                                "properties": {
                                    "source": subscriber.source,
                                    "tags": subscriber.tags,
                                },
                            },
                        }
                    },
                    headers={
                        "Authorization": f"Klaviyo-API-Key {klaviyo_key}",
                        "revision": "2023-12-15",
                        "Content-Type": "application/json",
                    },
                )
                return resp.status_code in (200, 201, 409)  # 409 = profile exists
        except Exception:
            return False

    async def generate_welcome_message(
        self, subscriber_id: str, brand_name: str, offer: str = "10% off"
    ) -> SMSMessage:
        """AI generates welcome SMS under 160 chars."""
        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are an SMS copywriter. Write a welcome SMS message under 160 characters. "
                "Be friendly, include the brand name and offer. No emojis. "
                "Return ONLY the SMS text, nothing else."
            ),
            user=f"Brand: {brand_name}\nOffer: {offer}\nWrite a welcome SMS under 160 characters.",
            model=AIModel.FAST,
            max_tokens=100,
        )

        if resp.success and resp.content:
            body = resp.content.strip()[:160]
        else:
            body = (
                f"Welcome to {brand_name}! Get {offer} on your first order. Reply STOP to opt out."[
                    :160
                ]
            )

        msg = SMSMessage(
            subscriber_id=subscriber_id,
            message_type="welcome",
            body=body,
        )
        self._messages.append(msg.to_dict())
        await self._save()
        return msg

    async def generate_cart_recovery_sms(
        self, subscriber_id: str, cart_value: float, product_name: str
    ) -> SMSMessage:
        """Generate cart recovery SMS with discount."""
        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are an SMS copywriter specializing in cart recovery. "
                "Write a cart recovery SMS under 160 characters. Include cart value and product. "
                "Create urgency. Return ONLY the SMS text."
            ),
            user=f"Cart value: ${cart_value:.2f}\nProduct: {product_name}\nWrite cart recovery SMS.",
            model=AIModel.FAST,
            max_tokens=100,
        )

        if resp.success and resp.content:
            body = resp.content.strip()[:160]
        else:
            body = f"You left {product_name} (${cart_value:.0f}) in your cart! Complete your order and save 10%. Limited time."[
                :160
            ]

        msg = SMSMessage(
            subscriber_id=subscriber_id,
            message_type="cart_recovery",
            body=body,
        )
        self._messages.append(msg.to_dict())
        await self._save()
        return msg

    async def generate_flash_sale_sms(self, subscriber_id: str, sale_details: dict) -> SMSMessage:
        """Generate flash sale announcement SMS."""
        sale_name = sale_details.get("name", "Flash Sale")
        discount = sale_details.get("discount", "30% off")
        expires = sale_details.get("expires", "24 hours")

        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are an SMS copywriter for flash sales. "
                "Write an urgent flash sale SMS under 160 characters. "
                "Create FOMO and urgency. Return ONLY the SMS text."
            ),
            user=f"Sale: {sale_name}\nDiscount: {discount}\nExpires: {expires}\nWrite flash sale SMS.",
            model=AIModel.FAST,
            max_tokens=100,
        )

        if resp.success and resp.content:
            body = resp.content.strip()[:160]
        else:
            body = f"FLASH SALE: {discount} on everything! Ends in {expires}. Shop now before it's gone!"[
                :160
            ]

        msg = SMSMessage(
            subscriber_id=subscriber_id,
            message_type="flash_sale",
            body=body,
        )
        self._messages.append(msg.to_dict())
        await self._save()
        return msg

    async def create_campaign_messages(
        self, segment_tag: str, campaign_type: str, offer: str
    ) -> list[SMSMessage]:
        """Create messages for all subscribers with the given tag."""
        await self._load()

        tagged_subs = [
            s
            for s in self._subscribers
            if segment_tag in s.get("tags", []) and s.get("opted_in", False)
        ]

        messages: list[SMSMessage] = []
        for sub in tagged_subs:
            sub_id = sub.get("subscriber_id", "unknown")

            if campaign_type == "flash_sale":
                msg = await self.generate_flash_sale_sms(sub_id, {"name": offer, "discount": offer})
            elif campaign_type == "cart_recovery":
                msg = await self.generate_cart_recovery_sms(sub_id, 0.0, offer)
            else:
                msg = await self.generate_welcome_message(sub_id, offer, offer)
                msg.message_type = campaign_type

            messages.append(msg)

        return messages

    def capture_stats(self) -> dict:
        """Return capture statistics."""
        total = len(self._subscribers)
        synced = sum(1 for s in self._subscribers if s.get("klaviyo_synced", False))
        opted_in = sum(1 for s in self._subscribers if s.get("opted_in", False))

        by_source: dict[str, int] = {}
        for s in self._subscribers:
            src = s.get("source", "unknown")
            by_source[src] = by_source.get(src, 0) + 1

        return {
            "total_subscribers": total,
            "klaviyo_synced": synced,
            "by_source": by_source,
            "opted_in_pct": round((opted_in / max(total, 1)) * 100, 1),
        }

    def recent_subscribers(self, limit: int = 10) -> list[dict]:
        """Return the most recent subscribers."""
        return sorted(
            self._subscribers,
            key=lambda x: x.get("created_at", 0),
            reverse=True,
        )[:limit]


# ── SINGLETON ─────────────────────────────────────────────
_instance: SMSCaptureEngine | None = None


def get_sms_capture_engine() -> SMSCaptureEngine:
    global _instance
    if _instance is None:
        _instance = SMSCaptureEngine()
    return _instance
