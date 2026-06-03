"""
Configuración centralizada de Aria AI.
Todas las variables de entorno tipadas y validadas al inicio.
"""
from pydantic_settings import BaseSettings
from pydantic import Field, validator
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    # ── IDENTIDAD ─────────────────────────────────────────
    APP_NAME: str = "Aria AI"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = Field(default="production")
    DEBUG: bool = Field(default=False)
    OWNER_NAME: str = Field(default="Señor Polanco")

    # ── IA — PRIMARIO ─────────────────────────────────────
    HF_TOKEN: str = Field(..., description="HuggingFace API Token")
    HF_MODEL_STRATEGY: str = "Qwen/Qwen2.5-72B-Instruct"
    HF_MODEL_CODE: str = "Qwen/Qwen2.5-Coder-32B-Instruct"
    HF_MODEL_FAST: str = "mistralai/Mistral-7B-Instruct-v0.3"

    # ── IA — SECUNDARIO ───────────────────────────────────
    GROQ_API_KEY: str = Field(..., description="Groq API Key")
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # ── IA — FALLBACK ─────────────────────────────────────
    OPENAI_API_KEY: Optional[str] = Field(default=None)
    OPENAI_MODEL: str = "gpt-4o-mini"

    # ── BASE DE DATOS ─────────────────────────────────────
    SUPABASE_URL: str = Field(...)
    SUPABASE_KEY: str = Field(...)

    # ── CACHE Y QUEUE ─────────────────────────────────────
    UPSTASH_REDIS_REST_URL: str = Field(...)
    UPSTASH_REDIS_REST_TOKEN: str = Field(...)

    # ── DESPLIEGUE ────────────────────────────────────────
    GITHUB_TOKEN: str = Field(...)
    GITHUB_USERNAME: str = Field(...)
    VERCEL_TOKEN: str = Field(...)

    # ── PAGOS ─────────────────────────────────────────────
    STRIPE_SECRET_KEY: str = Field(...)
    PAYPAL_CLIENT_ID: str = Field(...)
    PAYPAL_SECRET: str = Field(...)

    # ── PRODUCTOS DIGITALES ───────────────────────────────
    GUMROAD_TOKEN: str = Field(...)

    # ── ECOMMERCE ─────────────────────────────────────────
    SHOPIFY_STORE_URL: Optional[str] = Field(default=None)
    SHOPIFY_TOKEN: Optional[str] = Field(default=None)

    # ── CONTENIDO ─────────────────────────────────────────
    ELEVENLABS_API_KEY: Optional[str] = Field(default=None)
    DID_API_KEY: Optional[str] = Field(default=None)
    PEXELS_API_KEY: str = Field(...)
    CLOUDINARY_CLOUD_NAME: Optional[str] = Field(default=None)
    CLOUDINARY_API_KEY: Optional[str] = Field(default=None)
    CLOUDINARY_API_SECRET: Optional[str] = Field(default=None)

    # ── MARKETING ─────────────────────────────────────────
    MAILCHIMP_API_KEY: Optional[str] = Field(default=None)
    MAILCHIMP_DC: Optional[str] = Field(default=None)
    BUFFER_TOKEN: Optional[str] = Field(default=None)

    # ── INTELIGENCIA DE MERCADO ───────────────────────────
    NEWS_API_KEY: str = Field(...)
    SERP_API_KEY: str = Field(...)
    REDDIT_CLIENT_ID: Optional[str] = Field(default=None)
    REDDIT_SECRET: Optional[str] = Field(default=None)
    TWITTER_BEARER_TOKEN: Optional[str] = Field(default=None)

    # ── NOTIFICACIONES ────────────────────────────────────
    TELEGRAM_TOKEN: str = Field(...)
    TELEGRAM_CHAT_ID: str = Field(...)

    # ── EMAIL ─────────────────────────────────────────────
    RESEND_API_KEY: Optional[str] = Field(default=None)

    # ── SCHEDULER ────────────────────────────────────────
    CYCLE_INTERVAL_MINUTES: int = Field(default=60)
    MAX_CONCURRENT_TASKS: int = Field(default=8)
    REQUIRE_APPROVAL_FOR_PAYMENTS: bool = Field(default=True)
    REQUIRE_APPROVAL_FOR_DEPLOYS: bool = Field(default=False)
    MAX_SPEND_WITHOUT_APPROVAL_USD: float = Field(default=0.0)

    @validator("ENVIRONMENT")
    def validate_environment(cls, v):
        allowed = ["development", "staging", "production"]
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT debe ser uno de: {allowed}")
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

