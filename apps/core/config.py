"""
Settings centralizados para Aria AI.
Todos los secrets se cargan desde variables de entorno o Fly.io secrets.
HuggingFace es el motor principal. Groq y OpenAI son respaldo.
"""
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── SISTEMA ───────────────────────────────────────────
    ENVIRONMENT: str = "production"
    PORT: int = 8000
    OWNER_NAME: str = "Señor Polanco"
    OWNER_EMAIL: Optional[str] = None
    CYCLE_INTERVAL_MINUTES: int = 30
    REQUIRE_APPROVAL_FOR_PAYMENTS: bool = True
    REQUIRE_APPROVAL_FOR_DEPLOYS: bool = False
    MAX_SPEND_WITHOUT_APPROVAL_USD: float = 0.0

    # ── NOTIFICACIONES ────────────────────────────────────
    TELEGRAM_TOKEN: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # ── BASE DE DATOS ─────────────────────────────────────
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    UPSTASH_REDIS_REST_URL: str = ""
    UPSTASH_REDIS_REST_TOKEN: str = ""
    REDIS_URL: Optional[str] = None

    # ═══════════════════════════════════════════════════════
    # MOTOR PRINCIPAL: HuggingFace (gratis, sin límites de modelo)
    # Respaldo 1: Groq (ultra rápido, 30K tokens/min gratis)
    # Respaldo 2: OpenAI (pago, último recurso)
    # ═══════════════════════════════════════════════════════
    HF_TOKEN: Optional[str] = None
    HF_API_KEY: Optional[str] = None
    HUGGING_FACE_TOKEN: Optional[str] = None

    # ── Modelos HF primarios (free serverless inference) ──
    HF_MODEL_STRATEGY: str = "Qwen/Qwen2.5-72B-Instruct"
    HF_MODEL_CODE: str = "Qwen/Qwen2.5-Coder-7B-Instruct"
    HF_MODEL_FAST: str = "microsoft/Phi-3-mini-4k-instruct"
    HF_MODEL_CREATIVE: str = "HuggingFaceH4/zephyr-7b-beta"

    # ── Modelos HF de respaldo (si el primario está ocupado) ──
    HF_MODEL_STRATEGY_FB: str = "mistralai/Mistral-7B-Instruct-v0.3"
    HF_MODEL_CODE_FB: str = "microsoft/Phi-3.5-mini-instruct"
    HF_MODEL_FAST_FB: str = "google/flan-t5-large"

    # ── Respaldo 1: Groq (si HF falla completamente) ──────
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_MODEL_FAST: str = "llama-3.1-8b-instant"
    GROQ_MODEL_CODE: str = "llama-3.3-70b-versatile"

    # ── Respaldo 2: OpenAI (último recurso) ───────────────
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    # ── IA Adicional ──────────────────────────────────────
    ANTHROPIC_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    MISTRAL_API_KEY: Optional[str] = None
    ELEVENLABS_API_KEY: Optional[str] = None
    DID_API_KEY: Optional[str] = None
    DEEPGRAM_API_KEY: Optional[str] = None
    ASSEMBLYAI_API_KEY: Optional[str] = None

    # ── DESPLIEGUE / INFRA ────────────────────────────────
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_USERNAME: Optional[str] = None
    GITHUB_REPO: Optional[str] = "Geremypolanco/aria-ai"
    VERCEL_TOKEN: Optional[str] = None
    FLY_API_TOKEN: Optional[str] = None
    FLY_APP_NAME: str = "aria-ai"
    CLOUDFLARE_API_TOKEN: Optional[str] = None
    CLOUDFLARE_ACCOUNT_ID: Optional[str] = None

    # ── SOCIAL TOKEN ──────────────────────────────────────
    SOCIAL_CONNECT_TOKEN: str = Field(default="aria")

    # ── PAGOS Y MONETIZACIÓN ──────────────────────────────
    STRIPE_SECRET_KEY: Optional[str] = None
    PAYPAL_CLIENT_ID: Optional[str] = None
    PAYPAL_CLIENT_SECRET: Optional[str] = None
    PAYPAL_SECRET: Optional[str] = None
    GUMROAD_TOKEN: Optional[str] = None
    LEMONSQUEEZY_API_KEY: Optional[str] = None
    LEMONSQUEEZY_STORE_ID: Optional[str] = None
    COINBASE_COMMERCE_API_KEY: Optional[str] = None

    # ── E-COMMERCE ────────────────────────────────────────
    SHOPIFY_URL: Optional[str] = None
    SHOPIFY_STORE_URL: Optional[str] = None
    SHOPIFY_API_KEY: Optional[str] = None
    SHOPIFY_AUTOMATION_TOKEN: Optional[str] = None

    # ── PUBLICACIÓN DE CONTENIDO ──────────────────────────
    MEDIUM_TOKEN: Optional[str] = None
    DEVTO_API_KEY: Optional[str] = None
    HASHNODE_TOKEN: Optional[str] = None
    HASHNODE_PUBLICATION_ID: Optional[str] = None

    # ── SOCIAL MEDIA / MARKETING ──────────────────────────
    BUFFER_TOKEN: Optional[str] = None
    BUFFER_ACCESS_TOKEN: Optional[str] = None
    MAILCHIMP_API_KEY: Optional[str] = None
    MAILCHIMP_DC: Optional[str] = None
    AIRTABLE_TOKEN: Optional[str] = None
    AIRTABLE_API_KEY: Optional[str] = None

    # ── BÚSQUEDA Y DATOS ──────────────────────────────────
    NEWS_API_KEY: Optional[str] = None
    SERP_API_KEY: Optional[str] = None
    PEXELS_API_KEY: Optional[str] = None
    CANVA_CLIENT_ID: Optional[str] = None
    CANVA_CLIENT_SECRET: Optional[str] = None

    # ── MEDIA / IMÁGENES ─────────────────────────────────
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None

    # ── COMUNICACIONES ────────────────────────────────────
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None

    # ── AFILIADOS ─────────────────────────────────────────
    AMAZON_ASSOCIATE_TAG: Optional[str] = None
    CLICKBANK_AFFILIATE_ID: Optional[str] = None
    HOTMART_AFFILIATE_ID: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def hf_key(self) -> Optional[str]:
        """Devuelve el token HF activo (múltiples nombres aceptados)."""
        return self.HF_TOKEN or self.HF_API_KEY or self.HUGGING_FACE_TOKEN

    @property
    def telegram_token(self) -> str:
        """Token de Telegram (acepta ambos nombres)."""
        return self.TELEGRAM_BOT_TOKEN or self.TELEGRAM_TOKEN or ""

    @property
    def shopify_admin_url(self) -> Optional[str]:
        """URL de la tienda Shopify."""
        return self.SHOPIFY_URL or self.SHOPIFY_STORE_URL


settings = Settings()
