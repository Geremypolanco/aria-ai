import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── SISTEMA ───────────────────────────────────────────
    ENVIRONMENT: str = "production"
    PORT: int = 8000
    OWNER_NAME: str = "Señor Polanco"
    CYCLE_INTERVAL_MINUTES: int = 60
    REQUIRE_APPROVAL_FOR_PAYMENTS: bool = True
    REQUIRE_APPROVAL_FOR_DEPLOYS: bool = False
    MAX_SPEND_WITHOUT_APPROVAL_USD: float = 0.0

    # ── NOTIFICACIONES (Obligatorias) ─────────────────────
    TELEGRAM_TOKEN: str
    TELEGRAM_CHAT_ID: str

    # ── BASE DE DATOS (Obligatorias) ──────────────────────
    SUPABASE_URL: str
    SUPABASE_KEY: str
    UPSTASH_REDIS_REST_URL: str
    UPSTASH_REDIS_REST_TOKEN: str

    # ── INTELIGENCIA ARTIFICIAL ───────────────────────────
    HF_TOKEN: Optional[str] = "not_provided"
    GROQ_API_KEY: Optional[str] = "not_provided"
    OPENAI_API_KEY: Optional[str] = None

    # Modelos por proveedor
    HF_MODEL_STRATEGY: str = "Qwen/Qwen2.5-72B-Instruct"
    HF_MODEL_CODE: str = "Qwen/Qwen2.5-Coder-32B-Instruct"
    HF_MODEL_FAST: str = "mistralai/Mistral-7B-Instruct-v0.3"
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    OPENAI_MODEL: str = "gpt-4o-mini"

    # ── DESPLIEGUE ────────────────────────────────────────
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_USERNAME: Optional[str] = None
    VERCEL_TOKEN: Optional[str] = None

    # ── PAGOS Y MONETIZACIÓN ──────────────────────────────
    STRIPE_SECRET_KEY: Optional[str] = None
    PAYPAL_CLIENT_ID: Optional[str] = None
    PAYPAL_SECRET: Optional[str] = None
    GUMROAD_TOKEN: Optional[str] = None

    # ── ECOMMERCE ─────────────────────────────────────────
    SHOPIFY_URL: Optional[str] = None
    SHOPIFY_AUTOMATION_TOKEN: Optional[str] = None
    SHOPIFY_API_KEY: Optional[str] = None

    # ── CONTENIDO Y MULTIMEDIA ────────────────────────────
    ELEVENLABS_API_KEY: Optional[str] = None
    PEXELS_API_KEY: Optional[str] = None
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None
    CANVA_CLIENT_ID: Optional[str] = None
    CANVA_CLIENT_SECRET: Optional[str] = None

    # ── MARKETING ─────────────────────────────────────────
    MAILCHIMP_API_KEY: Optional[str] = None
    MAILCHIMP_DC: Optional[str] = None
    BUFFER_TOKEN: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    AIRTABLE_TOKEN: Optional[str] = None

    # ── INTELIGENCIA DE MERCADO ───────────────────────────
    NEWS_API_KEY: Optional[str] = None
    SERP_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


def get_settings() -> Settings:
    return Settings()


settings = get_settings()
