"""
Settings centralizados para Aria AI.
Todos los secrets se cargan desde variables de entorno o Fly.io secrets.
HuggingFace es el motor principal. Groq y OpenAI son respaldo.
"""
from typing import Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── SISTEMA ───────────────────────────────────────────
    ENVIRONMENT: str = "production"
    PORT: int = 8000
    OWNER_NAME: str = "Señor Polanco"
    OWNER_EMAIL: Optional[str] = None
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
    REDIS_URL: Optional[str] = None

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
    HF_TOKEN: Optional[str] = None
    HF_API_KEY: Optional[str] = None
    HUGGING_FACE_TOKEN: Optional[str] = None

    @property
    def hf_key(self) -> Optional[str]:
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
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_MODEL_FAST: str = "llama-3.1-8b-instant"
    GROQ_MODEL_CODE: str = "llama-3.3-70b-versatile"

    # ── Respaldo 2: OpenAI ────────────────────────────────
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    # ── IA Adicional ──────────────────────────────────────
    ANTHROPIC_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    COHERE_API_KEY: Optional[str] = None

    # ── CONTENIDO / SEO ───────────────────────────────────
    NEWS_API_KEY: Optional[str] = None
    SERP_API_KEY: Optional[str] = None
    PEXELS_API_KEY: Optional[str] = None
    ELEVENLABS_API_KEY: Optional[str] = None

    # ── COMERCIO ──────────────────────────────────────────
    GUMROAD_TOKEN: Optional[str] = None
    STRIPE_SECRET_KEY: Optional[str] = None
    PAYPAL_CLIENT_ID: Optional[str] = None
    PAYPAL_SECRET: Optional[str] = None
    SHOPIFY_URL: Optional[str] = None
    SHOPIFY_API_KEY: Optional[str] = None
    SHOPIFY_ADMIN_TOKEN: Optional[str] = None
    SHOPIFY_AUTOMATION_TOKEN: Optional[str] = None

    # ── REDES SOCIALES ────────────────────────────────────
    BUFFER_TOKEN: Optional[str] = None
    AIRTABLE_TOKEN: Optional[str] = None
    MAILCHIMP_API_KEY: Optional[str] = None
    MAILCHIMP_DC: Optional[str] = None
    MAILCHIMP_FROM_NAME: Optional[str] = "ARIA AI"
    MAILCHIMP_REPLY_TO: Optional[str] = None
    CONTACT_EMAIL: Optional[str] = None

    # Twitter / X
    TWITTER_API_KEY: Optional[str] = None
    TWITTER_API_SECRET: Optional[str] = None
    TWITTER_ACCESS_TOKEN: Optional[str] = None
    TWITTER_ACCESS_TOKEN_SECRET: Optional[str] = None
    TWITTER_BEARER_TOKEN: Optional[str] = None

    # Reddit
    REDDIT_CLIENT_ID: Optional[str] = None
    REDDIT_CLIENT_SECRET: Optional[str] = None
    REDDIT_USERNAME: Optional[str] = None
    REDDIT_PASSWORD: Optional[str] = None
    REDDIT_TARGET_SUBREDDIT: Optional[str] = None

    # Pinterest
    PINTEREST_ACCESS_TOKEN: Optional[str] = None
    PINTEREST_BOARD_ID: Optional[str] = None
    PINTEREST_DEFAULT_IMAGE_URL: Optional[str] = None

    # Discord
    DISCORD_WEBHOOK_URL: Optional[str] = None

    # Screenshot API
    SCREENSHOT_API_KEY: Optional[str] = None

    # ── PUBLICACIÓN DE CONTENIDO ──────────────────────────
    MEDIUM_TOKEN: Optional[str] = None
    DEVTO_API_KEY: Optional[str] = None
    HASHNODE_TOKEN: Optional[str] = None
    HASHNODE_PUBLICATION_ID: Optional[str] = None
    PRODUCT_HUNT_TOKEN: Optional[str] = None

    # ── EMAIL / NEWSLETTER ────────────────────────────────
    RESEND_API_KEY: Optional[str] = None
    SENDGRID_API_KEY: Optional[str] = None
    MAILGUN_API_KEY: Optional[str] = None
    MAILGUN_DOMAIN: Optional[str] = None
    EMAIL_FROM: Optional[str] = None
    NEWSLETTER_LIST_EMAIL: Optional[str] = None

    # ── AFILIADOS ─────────────────────────────────────────
    AMAZON_ASSOCIATE_TAG: Optional[str] = None
    CLICKBANK_AFFILIATE_ID: Optional[str] = None

    # ── MULTIMEDIA ────────────────────────────────────────
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None

    # ── DESARROLLO ────────────────────────────────────────
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_USERNAME: str = "Geremypolanco"
    VERCEL_TOKEN: Optional[str] = None
    NOTION_TOKEN: Optional[str] = None
    FACEBOOK_MARKETING_TOKEN: Optional[str] = None
    FACEBOOK_AD_ACCOUNT_ID: Optional[str] = None
    DID_API_KEY: Optional[str] = None
    CANVA_CLIENT_ID: Optional[str] = None
    CANVA_CLIENT_SECRET: Optional[str] = None
    ARIA_BASE_URL: str = "https://aria-ai.fly.dev"
    ZAPIER_WEBHOOK_URL: Optional[str] = None
    SOCIAL_CONNECT_TOKEN: str = "aria"

    # ── COMUNICACIÓN ──────────────────────────────────────
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None

    # ── API PÚBLICA ───────────────────────────────────────
    ARIA_API_KEY: Optional[str] = None

    # ── CREDENCIALES DE ARIA (para login stealth en plataformas) ──────────
    ARIA_EMAIL: Optional[str] = None
    ARIA_PASSWORD: Optional[str] = None

    # ── CONEXIONES OAuth (equivalente a MCP de Claude) ────────────────────
    # Google OAuth (DIFERENTE de GOOGLE_API_KEY — para acceso a Gmail/Calendar/Drive)
    # Obtén en: console.cloud.google.com → APIs & Services → Credentials → OAuth 2.0
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None

    # Slack OAuth (para enviar/leer mensajes en workspaces)
    # Obtén en: api.slack.com/apps → Create App → OAuth & Permissions
    SLACK_CLIENT_ID: Optional[str] = None
    SLACK_CLIENT_SECRET: Optional[str] = None
    SLACK_WEBHOOK_URL: Optional[str] = None  # Modo simple: solo webhook URL

    # ── Microsoft / Zoom ──────────────────────────────────
    MICROSOFT_CLIENT_ID: Optional[str] = None
    MICROSOFT_CLIENT_SECRET: Optional[str] = None
    ZOOM_CLIENT_ID: Optional[str] = None
    ZOOM_CLIENT_SECRET: Optional[str] = None

    # ── CRM ───────────────────────────────────────────────
    HUBSPOT_CLIENT_ID: Optional[str] = None
    HUBSPOT_CLIENT_SECRET: Optional[str] = None
    HUBSPOT_PRIVATE_APP_TOKEN: Optional[str] = None
    SALESFORCE_CLIENT_ID: Optional[str] = None
    SALESFORCE_CLIENT_SECRET: Optional[str] = None

    # ── Almacenamiento ────────────────────────────────────
    DROPBOX_APP_KEY: Optional[str] = None
    DROPBOX_APP_SECRET: Optional[str] = None
    BOX_CLIENT_ID: Optional[str] = None
    BOX_CLIENT_SECRET: Optional[str] = None

    # ── Scheduling ────────────────────────────────────────
    CALENDLY_CLIENT_ID: Optional[str] = None
    CALENDLY_CLIENT_SECRET: Optional[str] = None
    CALCOM_API_KEY: Optional[str] = None

    # ── Diseño ────────────────────────────────────────────
    FIGMA_CLIENT_ID: Optional[str] = None
    FIGMA_CLIENT_SECRET: Optional[str] = None
    FIGMA_API_TOKEN: Optional[str] = None

    # ── E-commerce ────────────────────────────────────────
    ETSY_CLIENT_ID: Optional[str] = None
    ETSY_CLIENT_SECRET: Optional[str] = None
    WOOCOMMERCE_URL: Optional[str] = None
    WOOCOMMERCE_CONSUMER_KEY: Optional[str] = None
    WOOCOMMERCE_CONSUMER_SECRET: Optional[str] = None
    AMAZON_ACCESS_KEY: Optional[str] = None
    AMAZON_SECRET_KEY: Optional[str] = None

    # ── Analytics ─────────────────────────────────────────
    MIXPANEL_API_SECRET: Optional[str] = None
    MIXPANEL_PROJECT_TOKEN: Optional[str] = None
    AMPLITUDE_API_KEY: Optional[str] = None
    AMPLITUDE_SECRET_KEY: Optional[str] = None
    DATADOG_API_KEY: Optional[str] = None
    DATADOG_APP_KEY: Optional[str] = None

    # ── Email Marketing ───────────────────────────────────
    KLAVIYO_API_KEY: Optional[str] = None
    ACTIVECAMPAIGN_URL: Optional[str] = None
    ACTIVECAMPAIGN_API_KEY: Optional[str] = None
    CONVERTKIT_API_SECRET: Optional[str] = None
    BREVO_API_KEY: Optional[str] = None
    POSTMARK_SERVER_TOKEN: Optional[str] = None

    # ── DevOps ────────────────────────────────────────────
    NETLIFY_TOKEN: Optional[str] = None
    CLOUDFLARE_API_TOKEN: Optional[str] = None
    CLOUDFLARE_ACCOUNT_ID: Optional[str] = None
    FIREBASE_PROJECT_ID: Optional[str] = None
    FIREBASE_SERVICE_ACCOUNT_TOKEN: Optional[str] = None
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"

    # ── CMS ───────────────────────────────────────────────
    WORDPRESS_URL: Optional[str] = None
    WORDPRESS_USERNAME: Optional[str] = None
    WORDPRESS_APP_PASSWORD: Optional[str] = None
    WEBFLOW_API_TOKEN: Optional[str] = None
    CONTENTFUL_SPACE_ID: Optional[str] = None
    CONTENTFUL_DELIVERY_TOKEN: Optional[str] = None
    CONTENTFUL_MANAGEMENT_TOKEN: Optional[str] = None
    SANITY_PROJECT_ID: Optional[str] = None
    SANITY_DATASET: str = "production"
    SANITY_API_TOKEN: Optional[str] = None

    # ── Media ─────────────────────────────────────────────
    SPOTIFY_CLIENT_ID: Optional[str] = None
    SPOTIFY_CLIENT_SECRET: Optional[str] = None
    TIKTOK_CLIENT_KEY: Optional[str] = None
    TIKTOK_CLIENT_SECRET: Optional[str] = None
    TWITCH_CLIENT_ID: Optional[str] = None
    TWITCH_CLIENT_SECRET: Optional[str] = None

    # ── Gestión de Proyectos ──────────────────────────────
    ASANA_ACCESS_TOKEN: Optional[str] = None
    TRELLO_API_KEY: Optional[str] = None
    TRELLO_TOKEN: Optional[str] = None
    LINEAR_API_KEY: Optional[str] = None
    JIRA_URL: Optional[str] = None
    JIRA_EMAIL: Optional[str] = None
    JIRA_API_TOKEN: Optional[str] = None
    MONDAY_API_KEY: Optional[str] = None

    # ── Finanzas ──────────────────────────────────────────
    QUICKBOOKS_CLIENT_ID: Optional[str] = None
    QUICKBOOKS_CLIENT_SECRET: Optional[str] = None
    ALPHA_VANTAGE_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )


settings = Settings()
