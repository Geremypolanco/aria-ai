"""
Settings centralizados para Aria AI — v2 Gobernador Económico.
"""
from typing import Optional, Any
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

    # ── SECTORES HABILITADOS ──────────────────────────────
    ENABLED_SECTORS: str = "digital"

    @property
    def enabled_sectors_list(self) -> list[str]:
        return [s.strip() for s in self.ENABLED_SECTORS.split(",") if s.strip()]

    # ── NOTIFICACIONES ────────────────────────────────────
    TELEGRAM_TOKEN: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    @property
    def telegram_token(self) -> str:
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
        return self.HF_TOKEN or self.HF_API_KEY or self.HUGGING_FACE_TOKEN

    HF_MODEL_STRATEGY: str = "Qwen/Qwen2.5-72B-Instruct"
    HF_MODEL_CODE: str = "Qwen/Qwen2.5-Coder-7B-Instruct"
    HF_MODEL_FAST: str = "microsoft/Phi-3-mini-4k-instruct"
    HF_MODEL_CREATIVE: str = "HuggingFaceH4/zephyr-7b-beta"
    HF_MODEL_STRATEGY_FB: str = "mistralai/Mistral-7B-Instruct-v0.3"
    HF_MODEL_CODE_FB: str = "microsoft/Phi-3.5-mini-instruct"
    HF_MODEL_FAST_FB: str = "google/flan-t5-large"

    # ── Groq (respaldo 1) ─────────────────────────────────
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # ── OpenAI (respaldo 2) ───────────────────────────────
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    # ── Anthropic ─────────────────────────────────────────
    ANTHROPIC_API_KEY: Optional[str] = None

    # ── CHLOE API (IA de economía circular) ───────────────
    CHLOE_API: Optional[str] = None
    CHLOE_API_URL: str = "https://api.chloe.ai/v1"

    # ── Cloudinary (gestión de media assets) ─────────────
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None
    CLOUDINARY_URL: Optional[str] = None

    @property
    def cloudinary_configured(self) -> bool:
        return bool(self.CLOUDINARY_CLOUD_NAME and self.CLOUDINARY_API_KEY and self.CLOUDINARY_API_SECRET)

    # ── GitHub ────────────────────────────────────────────
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_REPO: str = "Geremypolanco/aria-ai"

    # ── Pagos ─────────────────────────────────────────────
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_PUBLISHABLE_KEY: Optional[str] = None
    GUMROAD_TOKEN: Optional[str] = None

    # ── Email marketing ───────────────────────────────────
    MAILCHIMP_API_KEY: Optional[str] = None
    MAILCHIMP_SERVER_PREFIX: str = "us1"
    MAILCHIMP_LIST_ID: Optional[str] = None
    RESEND_API_KEY: Optional[str] = None
    SENDGRID_API_KEY: Optional[str] = None

    # ── Redes sociales ────────────────────────────────────
    BUFFER_TOKEN: Optional[str] = None
    TWITTER_BEARER_TOKEN: Optional[str] = None
    TWITTER_API_KEY: Optional[str] = None
    TWITTER_API_SECRET: Optional[str] = None
    TWITTER_ACCESS_TOKEN: Optional[str] = None
    TWITTER_ACCESS_SECRET: Optional[str] = None
    LINKEDIN_CLIENT_ID: Optional[str] = None
    LINKEDIN_CLIENT_SECRET: Optional[str] = None
    LINKEDIN_ACCESS_TOKEN: Optional[str] = None

    # ── Google ────────────────────────────────────────────
    GOOGLE_API_KEY: Optional[str] = None
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REFRESH_TOKEN: Optional[str] = None

    # ── Canva ─────────────────────────────────────────────
    CANVA_API_KEY: Optional[str] = None

    # ── Airtable ──────────────────────────────────────────
    AIRTABLE_API_KEY: Optional[str] = None
    AIRTABLE_BASE_ID: Optional[str] = None

    # ── ElevenLabs ────────────────────────────────────────
    ELEVENLABS_API_KEY: Optional[str] = None

    # ── Shopify ───────────────────────────────────────────
    SHOPIFY_URL: Optional[str] = None
    SHOPIFY_API_KEY: Optional[str] = None
    SHOPIFY_PASSWORD: Optional[str] = None

    # ── Fly.io ────────────────────────────────────────────
    FLY_API_TOKEN: Optional[str] = None

    # ── AWS S3 ────────────────────────────────────────────
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_S3_BUCKET: Optional[str] = None
    AWS_REGION: str = "us-east-1"

    # ── ECONOMÍA CIRCULAR ─────────────────────────────────
    # Tasas de distribución del capital (deben sumar <= 1.0)
    CIRCULAR_ECONOMY_REINVEST_RATE: float = 0.40
    CIRCULAR_ECONOMY_RESERVE_RATE: float = 0.30
    CIRCULAR_ECONOMY_COMMUNITY_RATE: float = 0.15
    # Varianza máxima aceptable en precios (5%)
    PRICE_STABILITY_TARGET_VARIANCE: float = 0.05

    # ── SECTORES ──────────────────────────────────────────
    SECTOR_CONFIGS: dict = {}

    def get_sector_credentials(self, sector: str) -> dict[str, Any]:
        base = self.SECTOR_CONFIGS.get(sector, {})
        if sector == "banking":
            return {**base, "stripe": self.STRIPE_SECRET_KEY}
        if sector == "digital":
            return {**base, "github": self.GITHUB_TOKEN, "cloudinary": self.CLOUDINARY_API_KEY}
        return base

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )


settings = Settings()
