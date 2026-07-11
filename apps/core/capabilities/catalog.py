"""
Capability catalog — the honest, current inventory of what ARIA can do.

This seeds the CapabilityRegistry with ARIA's REAL capabilities (assessed from how
the system actually behaves today) plus an explicit list of gaps (status=PLANNED).
Keeping this honest is the point: it prevents "ARIA can do everything" assumptions
and gives the planner a real map to work from.

Update this file as capabilities are added, verified, or change status. Health checks
are intentionally cheap (env-presence) so check_all() stays fast and free.
"""

from __future__ import annotations

import os

from apps.core.capabilities.registry import (
    Capability,
    CapabilityRegistry,
    CapabilityStatus,
    Quality,
)


def _env(*names: str) -> bool:
    return all(os.environ.get(n) for n in names)


async def _hc_stripe() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


async def _hc_telegram() -> bool:
    return _env("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID")


async def _hc_github() -> bool:
    return bool(os.environ.get("ARIA_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN"))


async def _hc_smtp() -> bool:
    return _env("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD")


async def _hc_social_creds() -> bool:
    return _env("ARIA_EMAIL", "ARIA_PASSWORD") or bool(os.environ.get("LINKEDIN_ACCESS_TOKEN"))


def seed_registry(reg: CapabilityRegistry) -> None:
    """Register ARIA's current capabilities and known gaps."""
    reg.register_many(
        [
            # ── Revenue-critical: payments & fulfillment ──────────────────────
            Capability(
                key="payments.stripe",
                category="payments",
                provider="stripe",
                description="Create real Stripe products/prices/payment links; accept card payments.",
                status=CapabilityStatus.ACTIVE,
                quality=Quality.HIGH,
                verified=True,  # live payment links created and validated
                requires=["STRIPE_SECRET_KEY"],
                standard="OpenAPI",
                health_check=_hc_stripe,
                notes="Live mode verified via the Stripe connector.",
            ),
            Capability(
                key="payments.paypal",
                category="payments",
                provider="paypal",
                description="PayPal Orders/Invoicing checkout.",
                status=CapabilityStatus.DEGRADED,
                quality=Quality.MEDIUM,
                requires=["PAYPAL_CLIENT_ID", "PAYPAL_SECRET"],
                standard="OAuth2",
                notes="Configured credentials are SANDBOX (live token 401) — needs live creds.",
            ),
            Capability(
                key="fulfillment.digital_delivery",
                category="fulfillment",
                provider="app:/access",
                description="Deliver purchased digital products automatically post-payment.",
                status=CapabilityStatus.ACTIVE,
                quality=Quality.HIGH,
                verified=True,
                notes="Stripe redirect → /access/{key} serves the real product. Anti-fraud.",
            ),
            # ── Distribution / publishing ─────────────────────────────────────
            Capability(
                key="publishing.linkedin",
                category="publishing",
                provider="broadcaster",
                description="Publish to LinkedIn (API-first, stealth-browser fallback).",
                status=CapabilityStatus.ACTIVE,
                quality=Quality.HIGH,
                verified=True,  # posts published this session
                requires=["LINKEDIN_ACCESS_TOKEN | ARIA_EMAIL+ARIA_PASSWORD"],
                health_check=_hc_social_creds,
            ),
            Capability(
                key="publishing.twitter",
                category="publishing",
                provider="broadcaster",
                description="Publish to Twitter/X (API-first, browser fallback).",
                status=CapabilityStatus.ACTIVE,
                quality=Quality.MEDIUM,
                requires=["TWITTER_API_KEY+SECRET+ACCESS | ARIA_EMAIL+ARIA_PASSWORD"],
            ),
            # ── Outreach / messaging ──────────────────────────────────────────
            Capability(
                key="messaging.telegram",
                category="messaging",
                provider="telegram_bot",
                description="Owner alerts and notifications via Telegram.",
                status=CapabilityStatus.ACTIVE,
                quality=Quality.HIGH,
                verified=True,
                requires=["TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"],
                health_check=_hc_telegram,
            ),
            Capability(
                key="outreach.email_smtp",
                category="outreach",
                provider="smtp",
                description="Send outreach / transactional email from the app.",
                status=CapabilityStatus.DOWN,
                quality=Quality.UNKNOWN,
                requires=["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"],
                health_check=_hc_smtp,
                notes="Not configured — app cannot send email until SMTP secrets are set.",
            ),
            # ── Content & intelligence ────────────────────────────────────────
            Capability(
                key="content.generation",
                category="content",
                provider="ai_client",
                description="LLM text generation (cascade: HF→Groq→Anthropic→Gemini→OpenAI).",
                status=CapabilityStatus.ACTIVE,
                quality=Quality.HIGH,
                verified=True,
            ),
            Capability(
                key="search.web",
                category="research",
                provider="web_tools",
                description="Web search for research and signals.",
                status=CapabilityStatus.ACTIVE,
                quality=Quality.MEDIUM,
                verified=True,
            ),
            # ── Infrastructure ────────────────────────────────────────────────
            Capability(
                key="repo.github",
                category="infrastructure",
                provider="github_client",
                description="Read/write repos, archive insights, deploy via CI.",
                status=CapabilityStatus.ACTIVE,
                quality=Quality.HIGH,
                verified=True,
                requires=["ARIA_GITHUB_TOKEN"],
                health_check=_hc_github,
            ),
            Capability(
                key="automation.browser",
                category="infrastructure",
                provider="human_browser",
                description="Stealth browser automation (logins, posting, DMs).",
                status=CapabilityStatus.ACTIVE,
                quality=Quality.MEDIUM,
                requires=["ARIA_EMAIL", "ARIA_PASSWORD"],
            ),
            Capability(
                key="crm.pipeline",
                category="crm",
                provider="redis",
                description="Lead/subscriber pipeline with follow-up.",
                status=CapabilityStatus.ACTIVE,
                quality=Quality.MEDIUM,
                verified=True,
                requires=["UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"],
            ),
            Capability(
                key="commerce.shopify",
                category="commerce",
                provider="shopify",
                description="Create/manage Shopify products & store.",
                status=CapabilityStatus.DEGRADED,
                quality=Quality.MEDIUM,
                requires=["SHOPIFY_URL", "SHOPIFY_ADMIN_TOKEN"],
                notes="Store is password-gated and lacks auto-delivery — use Stripe links to sell.",
            ),
            # ── Known GAPS (status=PLANNED) — what ARIA does NOT have yet ──────
            Capability(
                key="media.image_generation",
                category="media",
                provider="(none)",
                description="Generate product/marketing images.",
                status=CapabilityStatus.PLANNED,
                notes="No image-gen integration wired into the app yet.",
            ),
            Capability(
                key="media.video",
                category="media",
                provider="(none)",
                description="Generate/edit video for YouTube/TikTok.",
                status=CapabilityStatus.PLANNED,
            ),
            Capability(
                key="ads.paid_traffic",
                category="growth",
                provider="(none)",
                description="Run paid acquisition (Google/Meta) to the funnel.",
                status=CapabilityStatus.PLANNED,
                notes="Highest-leverage gap for scaling beyond organic reach.",
            ),
            Capability(
                key="crm.native",
                category="crm",
                provider="(none)",
                description="Native HubSpot/Salesforce sync (beyond the internal pipeline).",
                status=CapabilityStatus.PLANNED,
            ),
            Capability(
                key="finance.accounting",
                category="finance",
                provider="(none)",
                description="Bookkeeping / revenue reconciliation.",
                status=CapabilityStatus.PLANNED,
            ),
            Capability(
                key="prospecting.data",
                category="prospecting",
                provider="(none)",
                description="In-app real B2B prospect data with verified contacts.",
                status=CapabilityStatus.PLANNED,
                notes="Available to the operator via Explorium/Vibe, but not wired into the app (needs EXPLORIUM_API_KEY).",
            ),
        ]
    )
