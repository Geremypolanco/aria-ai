"""
ConnectionManager — gestión central de conexiones OAuth para ARIA AI.

Equivalente al sistema MCP de Claude: cada servicio es una conexión que
expone herramientas. Los tokens se guardan en Redis por chat_id.
"""

from __future__ import annotations

import logging

from apps.core.connections.registry import ConnectorFactory

logger = logging.getLogger("aria.connections")


class ConnectionManager:
    """
    Gestiona conexiones OAuth a servicios externos.
    Cada conexión: {access_token, refresh_token, expires_at, scope, service_user}
    """

    K_CONN = "aria:conn:{chat_id}:{service}"  # Redis key por usuario y servicio
    TTL = 86400 * 90  # 90 días

    AVAILABLE: dict[str, str] = {
        # Productividad / comunicación
        "google": "Google (Gmail, Calendar, Drive)",
        "slack": "Slack (mensajes, canales)",
        "microsoft": "Microsoft (Outlook, Teams, OneDrive)",
        "zoom": "Zoom (meetings, grabaciones)",
        "discord": "Discord (webhooks)",
        "notion": "Notion (páginas, bases de datos)",
        "airtable": "Airtable (bases, registros)",
        # Búsqueda / empleo
        "indeed": "Indeed (búsqueda de empleo)",
        # CRM / ventas
        "hubspot": "HubSpot (contactos, deals, pipelines)",
        "salesforce": "Salesforce (CRM enterprise)",
        # Almacenamiento
        "dropbox": "Dropbox (archivos, carpetas)",
        "box": "Box (almacenamiento empresarial)",
        # Finanzas
        "quickbooks": "QuickBooks (facturas, contabilidad)",
        # Agenda / scheduling
        "calendly": "Calendly (agenda, reuniones)",
        "calcom": "Cal.com (scheduling open-source)",
        # Diseño
        "figma": "Figma (diseño UI/UX, prototipos)",
        "canva": "Canva (diseño gráfico)",
        # E-commerce
        "etsy": "Etsy (tienda artesanal)",
        "woocommerce": "WooCommerce (tienda WordPress)",
        "amazon": "Amazon (Product Advertising)",
        # Analytics
        "google_analytics": "Google Analytics 4",
        "mixpanel": "Mixpanel (product analytics)",
        "amplitude": "Amplitude (analytics)",
        "datadog": "DataDog (infraestructura, logs)",
        # Email marketing
        "klaviyo": "Klaviyo (email, SMS marketing)",
        "activecampaign": "ActiveCampaign (email automation)",
        "convertkit": "ConvertKit/Kit (newsletter)",
        "brevo": "Brevo / Sendinblue (email transaccional)",
        "postmark": "Postmark (email transaccional)",
        # DevOps
        "netlify": "Netlify (deploy, sites)",
        "cloudflare": "Cloudflare (DNS, CDN, analytics)",
        "firebase": "Firebase / Firestore",
        "aws_s3": "AWS S3 (almacenamiento)",
        # CMS
        "wordpress": "WordPress (posts, páginas)",
        "webflow": "Webflow (sites, collections)",
        "contentful": "Contentful (headless CMS)",
        "sanity": "Sanity (structured content)",
        # Media
        "spotify": "Spotify (música, playlists)",
        "youtube": "YouTube (videos, canal)",
        "tiktok": "TikTok (videos, cuenta)",
        "twitch": "Twitch (streams, canal)",
        # Gestión de proyectos
        "asana": "Asana (tareas, proyectos)",
        "trello": "Trello (tableros, tarjetas)",
        "linear": "Linear (issues, sprints)",
        "jira": "Jira (tickets, sprints)",
        "monday": "Monday.com (proyectos)",
    }

    # Servicios que no requieren OAuth (usan API key/webhook directamente)
    NO_OAUTH = {
        "indeed",
        "discord",
        "airtable",
        "quickbooks",
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
            key = self.K_CONN.format(chat_id=chat_id, service=service)
            await cache.set(key, tokens, ttl_seconds=self.TTL)
            logger.info("[Connections] %s conectado para chat %s", service, chat_id)

    async def get(self, chat_id: str, service: str) -> dict | None:
        cache = self._cache()
        if not cache:
            return None
        key = self.K_CONN.format(chat_id=chat_id, service=service)
        data = await cache.get(key)
        return data if isinstance(data, dict) else None

    async def remove(self, chat_id: str, service: str) -> None:
        cache = self._cache()
        if cache:
            key = self.K_CONN.format(chat_id=chat_id, service=service)
            await cache.delete(key)
            logger.info("[Connections] %s desconectado para chat %s", service, chat_id)

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
            "quickbooks": "QUICKBOOKS_CLIENT_ID",
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
        """Genera URL de autenticación OAuth para el servicio.

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
            logger.warning("[Connections] Servicio desconocido: %s", service)
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
