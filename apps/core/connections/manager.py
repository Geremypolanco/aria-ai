"""
ConnectionManager — central management of OAuth connections for ARIA AI.

Equivalent to Claude's MCP system: each service is a connection that
exposes tools. Tokens are stored in Redis per chat_id.
"""

from __future__ import annotations

import logging

from apps.core.connections.registry import ConnectorFactory

logger = logging.getLogger("aria.connections")


class ConnectionManager:
    """
    Manages OAuth connections to external services.
    Each connection: {access_token, refresh_token, expires_at, scope, service_user}
    """

    K_CONN = "aria:conn:{chat_id}:{service}"  # Redis key per user and service
    TTL = 86400 * 90  # 90 days

    AVAILABLE: dict[str, str] = {
        # Productivity / communication
        "google": "Google (Gmail, Calendar, Drive)",
        "slack": "Slack (messages, channels)",
        "microsoft": "Microsoft (Outlook, Teams, OneDrive)",
        "zoom": "Zoom (meetings, recordings)",
        "discord": "Discord (webhooks)",
        "notion": "Notion (pages, databases)",
        "airtable": "Airtable (bases, records)",
        # Search / jobs
        "indeed": "Indeed (job search)",
        # CRM / sales
        "hubspot": "HubSpot (contacts, deals, pipelines)",
        "salesforce": "Salesforce (CRM enterprise)",
        # Storage
        "dropbox": "Dropbox (files, folders)",
        "box": "Box (enterprise storage)",
        # Finance
        "quickbooks": "QuickBooks (invoices, accounting)",
        # Scheduling
        "calendly": "Calendly (scheduling, meetings)",
        "calcom": "Cal.com (open-source scheduling)",
        # Design
        "figma": "Figma (UI/UX design, prototypes)",
        "canva": "Canva (graphic design)",
        # E-commerce
        "etsy": "Etsy (artisan shop)",
        "woocommerce": "WooCommerce (WordPress store)",
        "amazon": "Amazon (Product Advertising)",
        # Analytics
        "google_analytics": "Google Analytics 4",
        "mixpanel": "Mixpanel (product analytics)",
        "amplitude": "Amplitude (analytics)",
        "datadog": "DataDog (infrastructure, logs)",
        # Email marketing
        "klaviyo": "Klaviyo (email, SMS marketing)",
        "activecampaign": "ActiveCampaign (email automation)",
        "convertkit": "ConvertKit/Kit (newsletter)",
        "brevo": "Brevo / Sendinblue (transactional email)",
        "postmark": "Postmark (transactional email)",
        # DevOps
        "netlify": "Netlify (deploy, sites)",
        "cloudflare": "Cloudflare (DNS, CDN, analytics)",
        "firebase": "Firebase / Firestore",
        "aws_s3": "AWS S3 (storage)",
        # CMS
        "wordpress": "WordPress (posts, pages)",
        "webflow": "Webflow (sites, collections)",
        "contentful": "Contentful (headless CMS)",
        "sanity": "Sanity (structured content)",
        # Media
        "spotify": "Spotify (music, playlists)",
        "youtube": "YouTube (videos, channel)",
        "tiktok": "TikTok (videos, account)",
        "twitch": "Twitch (streams, channel)",
        # Project management
        "asana": "Asana (tasks, projects)",
        "trello": "Trello (boards, cards)",
        "linear": "Linear (issues, sprints)",
        "jira": "Jira (tickets, sprints)",
        "monday": "Monday.com (projects)",
    }

    # Services that don't require OAuth (use API key/webhook directly)
    # "quickbooks" removed: QuickBooksConnection implements real OAuth2
    # (get_auth_url/exchange_code), registered in ConnectorFactory.
    NO_OAUTH = {
        "indeed",
        "discord",
        "airtable",
        "trello",
        "calcom",
        "mixpanel",
        "amplitude",
        "datadog",
        "klaviyo",
        "activecampaign",
        "convertkit",
        "brevo",
        "postmark",
        "netlify",
        "cloudflare",
        "firebase",
        "aws_s3",
        "wordpress",
        "webflow",
        "contentful",
        "sanity",
        "woocommerce",
        "amazon",
        "notion",
    }

    def _cache(self):
        from apps.core.memory.redis_client import get_cache

        return get_cache()

    async def store(self, chat_id: str, service: str, tokens: dict) -> None:
        cache = self._cache()
        if cache:
            import json

            from apps.core.connectors import token_crypto

            key = self.K_CONN.format(chat_id=chat_id, service=service)
            blob = token_crypto.encrypt(json.dumps(tokens))
            await cache.set(key, blob, ttl_seconds=self.TTL)
            logger.info("[Connections] %s connected for chat %s", service, chat_id)

    async def get(self, chat_id: str, service: str) -> dict | None:
        cache = self._cache()
        if not cache:
            return None
        import json

        from apps.core.connectors import token_crypto

        key = self.K_CONN.format(chat_id=chat_id, service=service)
        raw = await cache.get(key)
        if not raw:
            return None
        # decrypt() transparently passes through any legacy plaintext record,
        # matching the same forward-compatible pattern oauth_hub.get_token uses.
        decoded = token_crypto.decrypt(raw) if isinstance(raw, str) else raw
        data = json.loads(decoded) if isinstance(decoded, str) else decoded
        return data if isinstance(data, dict) else None

    async def remove(self, chat_id: str, service: str) -> None:
        cache = self._cache()
        if cache:
            key = self.K_CONN.format(chat_id=chat_id, service=service)
            await cache.delete(key)
            logger.info("[Connections] %s disconnected for chat %s", service, chat_id)

    async def is_connected(self, chat_id: str, service: str) -> bool:
        if service in self.NO_OAUTH:
            # For API-key services, check the relevant env var exists
            return self._check_api_key_service(service)
        tokens = await self.get(chat_id, service)
        return bool(tokens and tokens.get("access_token"))

    def _check_api_key_service(self, service: str) -> bool:
        """Check if a non-OAuth service has its API key configured."""
        from apps.core.config import settings

        key_map = {
            "indeed": "SERP_API_KEY",
            "discord": "DISCORD_WEBHOOK_URL",
            "airtable": "AIRTABLE_TOKEN",
            "notion": "NOTION_TOKEN",
            "trello": "TRELLO_API_KEY",
            "calcom": "CALCOM_API_KEY",
            "mixpanel": "MIXPANEL_API_SECRET",
            "amplitude": "AMPLITUDE_API_KEY",
            "datadog": "DATADOG_API_KEY",
            "klaviyo": "KLAVIYO_API_KEY",
            "activecampaign": "ACTIVECAMPAIGN_API_KEY",
            "convertkit": "CONVERTKIT_API_SECRET",
            "brevo": "BREVO_API_KEY",
            "postmark": "POSTMARK_SERVER_TOKEN",
            "netlify": "NETLIFY_TOKEN",
            "cloudflare": "CLOUDFLARE_API_TOKEN",
            "firebase": "FIREBASE_PROJECT_ID",
            "aws_s3": "AWS_ACCESS_KEY_ID",
            "wordpress": "WORDPRESS_URL",
            "webflow": "WEBFLOW_API_TOKEN",
            "contentful": "CONTENTFUL_SPACE_ID",
            "sanity": "SANITY_PROJECT_ID",
            "woocommerce": "WOOCOMMERCE_URL",
            "amazon": "AMAZON_ASSOCIATE_TAG",
        }
        env_var = key_map.get(service)
        if not env_var:
            return False
        return bool(getattr(settings, env_var, None))

    async def list_connected(self, chat_id: str) -> list[str]:
        connected = []
        for service in self.AVAILABLE:
            if await self.is_connected(chat_id, service):
                connected.append(service)
        return connected

    def get_auth_url(self, service: str, chat_id: str) -> str | None:
        """Generates the OAuth authentication URL for the service.

        Dispatched entirely through ConnectorFactory — adding connector #23
        (or #300) never touches this method. See apps/core/connections/base.py
        and registry.py for the interface + Factory Manager.
        """
        connector = ConnectorFactory.create(service)
        return connector.get_auth_url(chat_id) if connector else None

    async def handle_callback(self, service: str, code: str, chat_id: str) -> bool:
        """Exchange authorization code for tokens and store them."""
        connector = ConnectorFactory.create(service)
        if not connector:
            logger.warning("[Connections] Unknown service: %s", service)
            return False
        try:
            tokens = await connector.exchange_code(code, chat_id)
            if tokens:
                await self.store(chat_id, service, tokens)
                return True
        except Exception as exc:
            logger.error("[Connections] Callback error %s: %s", service, exc)
        return False


_mgr: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    global _mgr
    if _mgr is None:
        _mgr = ConnectionManager()
    return _mgr
