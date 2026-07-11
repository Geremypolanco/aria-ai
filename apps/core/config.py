"""
Settings centralizados para Aria AI.
Todos los secrets se cargan desde variables de entorno o Fly.io secrets.
HuggingFace es el motor principal. Groq y OpenAI son respaldo.
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── SISTEMA ───────────────────────────────────────────
    ENVIRONMENT: str = "production"
    PORT: int = 8000
    OWNER_NAME: str = "Señor Polanco"
    OWNER_EMAIL: str | None = None
    CYCLE_INTERVAL_MINUTES: int = 60
    REQUIRE_APPROVAL_FOR_PAYMENTS: bool = True
    REQUIRE_APPROVAL_FOR_DEPLOYS: bool = False
    MAX_SPEND_WITHOUT_APPROVAL_USD: float = 0.0

    # ── NOTIFICACIONES ────────────────────────────────────
    TELEGRAM_TOKEN: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    @property
    def telegram_token(self) -> str:
        """Devuelve el token de Telegram disponible."""
        return self.TELEGRAM_TOKEN or self.TELEGRAM_BOT_TOKEN

    # ── BASE DE DATOS ─────────────────────────────────────
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    UPSTASH_REDIS_REST_URL: str = ""
    UPSTASH_REDIS_REST_TOKEN: str = ""
    REDIS_URL: str | None = None

    @field_validator("SUPABASE_URL", mode="before")
    @classmethod
    def fix_supabase_url(cls, v: str) -> str:
        """Corrige URL del dashboard a URL REST del proyecto."""
        if not v:
            return v
        if "supabase.com/dashboard/project/" in v:
            project_ref = v.rstrip("/").split("/")[-1]
            return f"https://{project_ref}.supabase.co"
        return v

    # ── HuggingFace (motor principal) ─────────────────────
    HF_TOKEN: str | None = None
    HF_API_KEY: str | None = None
    HUGGING_FACE_TOKEN: str | None = None

    @property
    def hf_key(self) -> str | None:
        """Compatibilidad con ai_client.py: devuelve el HF token."""
        return self.HF_TOKEN or self.HF_API_KEY or self.HUGGING_FACE_TOKEN

    # ── Modelos HF primarios ───────────────────────────────
    HF_MODEL_STRATEGY: str = "Qwen/Qwen2.5-72B-Instruct"
    HF_MODEL_CODE: str = "Qwen/Qwen2.5-Coder-7B-Instruct"
    HF_MODEL_FAST: str = "microsoft/Phi-3-mini-4k-instruct"
    HF_MODEL_CREATIVE: str = "HuggingFaceH4/zephyr-7b-beta"

    # ── Modelos HF de respaldo ────────────────────────────
    HF_MODEL_STRATEGY_FB: str = "mistralai/Mistral-7B-Instruct-v0.3"
    HF_MODEL_CODE_FB: str = "microsoft/Phi-3.5-mini-instruct"
    HF_MODEL_FAST_FB: str = "google/flan-t5-large"

    # ── Respaldo 1: Groq ──────────────────────────────────
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_MODEL_FAST: str = "llama-3.1-8b-instant"
    GROQ_MODEL_CODE: str = "llama-3.3-70b-versatile"

    # ── Respaldo 2: OpenAI ────────────────────────────────
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    # ── IA Adicional ──────────────────────────────────────
    ANTHROPIC_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None
    COHERE_API_KEY: str | None = None

    # ── CONTENIDO / SEO ───────────────────────────────────
    NEWS_API_KEY: str | None = None
    SERP_API_KEY: str | None = None
    # Alternative web-search providers (free tiers, work from servers). Set either
    # to keep research working when SerpAPI is out of quota.
    TAVILY_API_KEY: str | None = None
    BRAVE_API_KEY: str | None = None
    PEXELS_API_KEY: str | None = None
    ELEVENLABS_API_KEY: str | None = None

    # ── COMERCIO ──────────────────────────────────────────
    GUMROAD_TOKEN: str | None = None
    STRIPE_SECRET_KEY: str | None = None
    PAYPAL_CLIENT_ID: str | None = None
    PAYPAL_SECRET: str | None = None
    SHOPIFY_URL: str | None = None
    SHOPIFY_API_KEY: str | None = None
    SHOPIFY_ADMIN_TOKEN: str | None = None
    SHOPIFY_AUTOMATION_TOKEN: str | None = None

    # ── REDES SOCIALES ────────────────────────────────────
    BUFFER_TOKEN: str | None = None
    AIRTABLE_TOKEN: str | None = None
    MAILCHIMP_API_KEY: str | None = None
    MAILCHIMP_DC: str | None = None
    MAILCHIMP_FROM_NAME: str | None = "ARIA AI"
    MAILCHIMP_REPLY_TO: str | None = None
    CONTACT_EMAIL: str | None = None

    # Twitter / X
    TWITTER_API_KEY: str | None = None
    TWITTER_API_SECRET: str | None = None
    TWITTER_ACCESS_TOKEN: str | None = None
    TWITTER_ACCESS_TOKEN_SECRET: str | None = None
    TWITTER_BEARER_TOKEN: str | None = None

    # Reddit
    REDDIT_CLIENT_ID: str | None = None
    REDDIT_CLIENT_SECRET: str | None = None
    REDDIT_USERNAME: str | None = None
    REDDIT_PASSWORD: str | None = None
    REDDIT_TARGET_SUBREDDIT: str | None = None

    # Pinterest
    PINTEREST_ACCESS_TOKEN: str | None = None
    PINTEREST_BOARD_ID: str | None = None
    PINTEREST_DEFAULT_IMAGE_URL: str | None = None

    # Discord
    DISCORD_WEBHOOK_URL: str | None = None

    # Screenshot API
    SCREENSHOT_API_KEY: str | None = None

    # ── PUBLICACIÓN DE CONTENIDO ──────────────────────────
    MEDIUM_TOKEN: str | None = None
    DEVTO_API_KEY: str | None = None
    HASHNODE_TOKEN: str | None = None
    HASHNODE_PUBLICATION_ID: str | None = None
    PRODUCT_HUNT_TOKEN: str | None = None

    # ── EMAIL / NEWSLETTER ────────────────────────────────
    RESEND_API_KEY: str | None = None
    SENDGRID_API_KEY: str | None = None
    MAILGUN_API_KEY: str | None = None
    MAILGUN_DOMAIN: str | None = None
    EMAIL_FROM: str | None = None
    NEWSLETTER_LIST_EMAIL: str | None = None

    # ── AFILIADOS ─────────────────────────────────────────
    AMAZON_ASSOCIATE_TAG: str | None = None
    CLICKBANK_AFFILIATE_ID: str | None = None

    # ── MULTIMEDIA ────────────────────────────────────────
    CLOUDINARY_CLOUD_NAME: str | None = None
    CLOUDINARY_API_KEY: str | None = None
    CLOUDINARY_API_SECRET: str | None = None

    # ── DESARROLLO ────────────────────────────────────────
    GITHUB_TOKEN: str | None = None
    GITHUB_USERNAME: str = "Geremypolanco"
    VERCEL_TOKEN: str | None = None
    NOTION_TOKEN: str | None = None
    FACEBOOK_MARKETING_TOKEN: str | None = None
    FACEBOOK_AD_ACCOUNT_ID: str | None = None
    DID_API_KEY: str | None = None
    CANVA_CLIENT_ID: str | None = None
    CANVA_CLIENT_SECRET: str | None = None
    ARIA_BASE_URL: str = "https://aria-ai.fly.dev"
    ZAPIER_WEBHOOK_URL: str | None = None
    # Full Zapier MCP endpoint URL (embeds its own key) copied from mcp.zapier.com.
    # Lets ARIA publish to every account the owner connected in Zapier with one credential.
    ZAPIER_MCP_URL: str | None = None
    SOCIAL_CONNECT_TOKEN: str = "aria"

    # ── COMUNICACIÓN ──────────────────────────────────────
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None

    # ── API PÚBLICA ───────────────────────────────────────
    ARIA_API_KEY: str | None = None
    # Owner-only password gating the /admin control panel (server-side).
    ADMIN_PASSWORD: str | None = None
    # Dedicated HMAC key for signing user session cookies + OAuth state.
    # Set this in production; if unset, auth.py derives an ephemeral per-process
    # key (sessions won't survive a restart / multiple instances) — never a
    # public constant.
    SESSION_SECRET: str | None = None
    # Secret for signing outbound integration webhooks.
    WEBHOOK_SECRET: str | None = None
    # Fly.io API token — enables the live instance counter in the admin console.
    FLY_API_TOKEN: str | None = None

    # ── CREDENCIALES DE ARIA (para login stealth en plataformas) ──────────
    ARIA_EMAIL: str | None = None
    ARIA_PASSWORD: str | None = None

    # ── CONEXIONES OAuth (equivalente a MCP de Claude) ────────────────────
    # Google OAuth (DIFERENTE de GOOGLE_API_KEY — para acceso a Gmail/Calendar/Drive)
    # Obtén en: console.cloud.google.com → APIs & Services → Credentials → OAuth 2.0
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    GITHUB_CLIENT_ID: str | None = None
    GITHUB_CLIENT_SECRET: str | None = None
    META_APP_ID: str | None = None
    META_APP_SECRET: str | None = None

    # Slack OAuth (para enviar/leer mensajes en workspaces)
    # Obtén en: api.slack.com/apps → Create App → OAuth & Permissions
    SLACK_CLIENT_ID: str | None = None
    SLACK_CLIENT_SECRET: str | None = None
    SLACK_WEBHOOK_URL: str | None = None  # Modo simple: solo webhook URL

    # ── Microsoft / Zoom ──────────────────────────────────
    MICROSOFT_CLIENT_ID: str | None = None
    MICROSOFT_CLIENT_SECRET: str | None = None
    ZOOM_CLIENT_ID: str | None = None
    ZOOM_CLIENT_SECRET: str | None = None

    # ── CRM ───────────────────────────────────────────────
    HUBSPOT_CLIENT_ID: str | None = None
    HUBSPOT_CLIENT_SECRET: str | None = None
    HUBSPOT_PRIVATE_APP_TOKEN: str | None = None
    SALESFORCE_CLIENT_ID: str | None = None
    SALESFORCE_CLIENT_SECRET: str | None = None

    # ── Almacenamiento ────────────────────────────────────
    DROPBOX_APP_KEY: str | None = None
    DROPBOX_APP_SECRET: str | None = None
    BOX_CLIENT_ID: str | None = None
    BOX_CLIENT_SECRET: str | None = None

    # ── Scheduling ────────────────────────────────────────
    CALENDLY_CLIENT_ID: str | None = None
    CALENDLY_CLIENT_SECRET: str | None = None
    CALCOM_API_KEY: str | None = None

    # ── Diseño ────────────────────────────────────────────
    FIGMA_CLIENT_ID: str | None = None
    FIGMA_CLIENT_SECRET: str | None = None
    FIGMA_API_TOKEN: str | None = None

    # ── E-commerce ────────────────────────────────────────
    ETSY_CLIENT_ID: str | None = None
    ETSY_CLIENT_SECRET: str | None = None
    WOOCOMMERCE_URL: str | None = None
    WOOCOMMERCE_CONSUMER_KEY: str | None = None
    WOOCOMMERCE_CONSUMER_SECRET: str | None = None
    AMAZON_ACCESS_KEY: str | None = None
    AMAZON_SECRET_KEY: str | None = None

    # ── Analytics ─────────────────────────────────────────
    MIXPANEL_API_SECRET: str | None = None
    MIXPANEL_PROJECT_TOKEN: str | None = None
    AMPLITUDE_API_KEY: str | None = None
    AMPLITUDE_SECRET_KEY: str | None = None
    DATADOG_API_KEY: str | None = None
    DATADOG_APP_KEY: str | None = None

    # ── Email Marketing ───────────────────────────────────
    KLAVIYO_API_KEY: str | None = None
    ACTIVECAMPAIGN_URL: str | None = None
    ACTIVECAMPAIGN_API_KEY: str | None = None
    CONVERTKIT_API_SECRET: str | None = None
    BREVO_API_KEY: str | None = None
    POSTMARK_SERVER_TOKEN: str | None = None

    # ── DevOps ────────────────────────────────────────────
    NETLIFY_TOKEN: str | None = None
    CLOUDFLARE_API_TOKEN: str | None = None
    CLOUDFLARE_ACCOUNT_ID: str | None = None
    FIREBASE_PROJECT_ID: str | None = None
    FIREBASE_SERVICE_ACCOUNT_TOKEN: str | None = None
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    AWS_REGION: str = "us-east-1"

    # ── CMS ───────────────────────────────────────────────
    WORDPRESS_URL: str | None = None
    WORDPRESS_USERNAME: str | None = None
    WORDPRESS_APP_PASSWORD: str | None = None
    WEBFLOW_API_TOKEN: str | None = None
    CONTENTFUL_SPACE_ID: str | None = None
    CONTENTFUL_DELIVERY_TOKEN: str | None = None
    CONTENTFUL_MANAGEMENT_TOKEN: str | None = None
    SANITY_PROJECT_ID: str | None = None
    SANITY_DATASET: str = "production"
    SANITY_API_TOKEN: str | None = None

    # ── Media ─────────────────────────────────────────────
    SPOTIFY_CLIENT_ID: str | None = None
    SPOTIFY_CLIENT_SECRET: str | None = None
    TIKTOK_CLIENT_KEY: str | None = None
    TIKTOK_CLIENT_SECRET: str | None = None
    TWITCH_CLIENT_ID: str | None = None
    TWITCH_CLIENT_SECRET: str | None = None

    # ── Gestión de Proyectos ──────────────────────────────
    ASANA_ACCESS_TOKEN: str | None = None
    TRELLO_API_KEY: str | None = None
    TRELLO_TOKEN: str | None = None
    LINEAR_API_KEY: str | None = None
    JIRA_URL: str | None = None
    JIRA_EMAIL: str | None = None
    JIRA_API_TOKEN: str | None = None
    MONDAY_API_KEY: str | None = None

    # ── Finanzas ──────────────────────────────────────────
    QUICKBOOKS_CLIENT_ID: str | None = None
    QUICKBOOKS_CLIENT_SECRET: str | None = None
    ALPHA_VANTAGE_API_KEY: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )


settings = Settings()
