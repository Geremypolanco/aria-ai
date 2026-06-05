"""
  Settings centralizados para Aria AI.
  Todos los secrets se cargan desde variables de entorno o Fly.io secrets.
  """
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── SISTEMA ───────────────────────────────────────────
    ENVIRONMENT: str = "production"
    PORT: int = 8000
    OWNER_NAME: str = "Geremy Polanco"
    OWNER_EMAIL: Optional[str] = None
    CYCLE_INTERVAL_MINUTES: int = 60
    REQUIRE_APPROVAL_FOR_PAYMENTS: bool = True
    REQUIRE_APPROVAL_FOR_DEPLOYS: bool = False
    MAX_SPEND_WITHOUT_APPROVAL_USD: float = 0.0

    # ── NOTIFICACIONES (Obligatorias) ─────────────────────
    TELEGRAM_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # ── BASE DE DATOS (Obligatorias) ──────────────────────
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    UPSTASH_REDIS_REST_URL: str = ""
    UPSTASH_REDIS_REST_TOKEN: str = ""
    REDIS_URL: Optional[str] = None

    # ── INTELIGENCIA ARTIFICIAL ───────────────────────────
    HF_TOKEN: Optional[str] = None
    HF_API_KEY: Optional[str] = None
    HUGGING_FACE_TOKEN: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    MISTRAL_API_KEY: Optional[str] = None
    COHERE_API_KEY: Optional[str] = None
    TOGETHER_AI_API_KEY: Optional[str] = None
    DEEPGRAM_API_KEY: Optional[str] = None
    ASSEMBLYAI_API_KEY: Optional[str] = None
    DID_API_KEY: Optional[str] = None

    HF_MODEL_STRATEGY: str = "Qwen/Qwen2.5-72B-Instruct"
    HF_MODEL_CODE: str = "Qwen/Qwen2.5-Coder-32B-Instruct"
    HF_MODEL_FAST: str = "mistralai/Mistral-7B-Instruct-v0.3"
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    OPENAI_MODEL: str = "gpt-4o-mini"

    # ── DESPLIEGUE ────────────────────────────────────────
    GITHUB_TOKEN: Optional[str] = None
    SOCIAL_CONNECT_TOKEN: str = Field(default="aria", description="Token para el formulario web de conexion social")
    GITHUB_USERNAME: Optional[str] = None
    GITHUB_REPO: Optional[str] = "Geremypolanco/aria-ai"
    VERCEL_TOKEN: Optional[str] = None

    # ── PAGOS Y MONETIZACIÓN ──────────────────────────────
    STRIPE_SECRET_KEY: Optional[str] = None
    PAYPAL_CLIENT_ID: Optional[str] = None
    PAYPAL_CLIENT_SECRET: Optional[str] = None
    PAYPAL_SECRET: Optional[str] = None
    GUMROAD_TOKEN: Optional[str] = None
    LEMONSQUEEZY_API_KEY: Optional[str] = None
    LEMONSQUEEZY_STORE_ID: Optional[str] = None
    COINBASE_COMMERCE_API_KEY: Optional[str] = None
    WISE_API_KEY: Optional[str] = None

    # ── ECOMMERCE ─────────────────────────────────────────
    SHOPIFY_URL: Optional[str] = None
    SHOPIFY_AUTOMATION_TOKEN: Optional[str] = None
    SHOPIFY_API_KEY: Optional[str] = None
    SHOPIFY_ACCESS_TOKEN: Optional[str] = None
    PRINTFUL_API_KEY: Optional[str] = None
    PRINTIFY_API_KEY: Optional[str] = None
    ETSY_API_KEY: Optional[str] = None
    ETSY_SHOP_ID: Optional[str] = None

    # ── AFILIADOS ────────────────────────────────────────
    AMAZON_ASSOCIATE_TAG: Optional[str] = None
    AMAZON_PA_ACCESS_KEY: Optional[str] = None
    AMAZON_PA_SECRET_KEY: Optional[str] = None
    AMAZON_PA_PARTNER_TAG: Optional[str] = None
    CLICKBANK_AFFILIATE_ID: Optional[str] = None
    CLICKBANK_API_KEY: Optional[str] = None
    HOTMART_BASIC_TOKEN: Optional[str] = None
    HOTMART_CLIENT_ID: Optional[str] = None
    HOTMART_CLIENT_SECRET: Optional[str] = None

    # ── PUBLICACIÓN DE CONTENIDO ─────────────────────────
    MEDIUM_TOKEN: Optional[str] = None
    DEVTO_API_KEY: Optional[str] = None
    HASHNODE_TOKEN: Optional[str] = None
    HASHNODE_PUBLICATION_ID: Optional[str] = None

    # ── CONTENIDO Y MULTIMEDIA ────────────────────────────
    ELEVENLABS_API_KEY: Optional[str] = None
    PEXELS_API_KEY: Optional[str] = None
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None
    CANVA_CLIENT_ID: Optional[str] = None
    CANVA_CLIENT_SECRET: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None

    # ── REDES SOCIALES ───────────────────────────────────
    ARIA_BASE_URL: str = "https://aria-ai.fly.dev"
    FACEBOOK_APP_ID: Optional[str] = None
    FACEBOOK_APP_SECRET: Optional[str] = None
    TIKTOK_CLIENT_KEY: Optional[str] = None
    TIKTOK_CLIENT_SECRET: Optional[str] = None
    LINKEDIN_CLIENT_ID: Optional[str] = None
    LINKEDIN_CLIENT_SECRET: Optional[str] = None
    TWITTER_API_KEY: Optional[str] = None
    TWITTER_API_SECRET: Optional[str] = None
    TWITTER_ACCESS_TOKEN: Optional[str] = None
    TWITTER_ACCESS_TOKEN_SECRET: Optional[str] = None
    TWITTER_BEARER_TOKEN: Optional[str] = None
    REDDIT_CLIENT_ID: Optional[str] = None
    REDDIT_CLIENT_SECRET: Optional[str] = None
    REDDIT_USERNAME: Optional[str] = None
    REDDIT_PASSWORD: Optional[str] = None
    REDDIT_TARGET_SUBREDDIT: Optional[str] = None
    PINTEREST_ACCESS_TOKEN: Optional[str] = None
    PINTEREST_BOARD_ID: Optional[str] = None
    PINTEREST_DEFAULT_IMAGE_URL: Optional[str] = None
    DISCORD_WEBHOOK_URL: Optional[str] = None
    DISCORD_BOT_TOKEN: Optional[str] = None
    YOUTUBE_API_KEY: Optional[str] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_BUSINESS_TOKEN: Optional[str] = None
    PRODUCT_HUNT_TOKEN: Optional[str] = None

    # ── MARKETING ─────────────────────────────────────────
    MAILCHIMP_API_KEY: Optional[str] = None
    MAILCHIMP_DC: Optional[str] = "us1"
    BUFFER_TOKEN: Optional[str] = None
    AIRTABLE_API_KEY: Optional[str] = None
    AIRTABLE_TOKEN: Optional[str] = None
    NEWS_API_KEY: Optional[str] = None
    SERP_API_KEY: Optional[str] = None

    # ── EMAIL MARKETING ──────────────────────────────────
    RESEND_API_KEY: Optional[str] = None
    SENDGRID_API_KEY: Optional[str] = None
    MAILGUN_API_KEY: Optional[str] = None
    MAILGUN_DOMAIN: Optional[str] = None
    CONVERTKIT_API_KEY: Optional[str] = None
    CONVERTKIT_FORM_ID: Optional[str] = None
    KLAVIYO_API_KEY: Optional[str] = None
    BREVO_API_KEY: Optional[str] = None
    EMAIL_FROM: Optional[str] = None
    NEWSLETTER_LIST_EMAIL: Optional[str] = None

    # ── SEO E INTELIGENCIA ───────────────────────────────
    GOOGLE_SEARCH_CONSOLE_KEY: Optional[str] = None
    SCRAPER_API_KEY: Optional[str] = None
    DATA_FOR_SEO_LOGIN: Optional[str] = None
    DATA_FOR_SEO_PASSWORD: Optional[str] = None

    # ── ANALÍTICAS ───────────────────────────────────────
    GA4_MEASUREMENT_ID: Optional[str] = None
    GA4_API_SECRET: Optional[str] = None
    POSTHOG_API_KEY: Optional[str] = None
    SENTRY_DSN: Optional[str] = None

    # ── CRM ──────────────────────────────────────────────
    HUBSPOT_API_KEY: Optional[str] = None
    ZOHO_CRM_CLIENT_ID: Optional[str] = None
    ZOHO_CRM_CLIENT_SECRET: Optional[str] = None

    # ── INFRAESTRUCTURA ──────────────────────────────────
    CLOUDFLARE_API_TOKEN: Optional[str] = None
    CLOUDFLARE_ACCOUNT_ID: Optional[str] = None
    CLOUDFLARE_R2_ACCESS_KEY: Optional[str] = None
    CLOUDFLARE_R2_SECRET_KEY: Optional[str] = None

    # ── LOGÍSTICA ────────────────────────────────────────
    EASYPOST_API_KEY: Optional[str] = None
    SHIPPO_API_KEY: Optional[str] = None

    # ── COMUNICACIONES ────────────────────────────────────
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


def get_settings() -> Settings:
    return Settings()


settings = get_settings()
