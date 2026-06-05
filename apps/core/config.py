import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Variables del Entorno Base
    ENVIRONMENT: str = "production"
    PORT: int = 8000

    # Infraestructura Núcleo (Obligatorias)
    TELEGRAM_TOKEN: str
    TELEGRAM_CHAT_ID: str
    SUPABASE_URL: str
    SUPABASE_KEY: str
    UPSTASH_REDIS_REST_URL: str
    UPSTASH_REDIS_REST_TOKEN: str

    # Modelos de Inteligencia Artificial
    HF_TOKEN: Optional[str] = "not_provided"
    GROQ_API_KEY: Optional[str] = "not_provided"
    OPENAI_API_KEY: Optional[str] = None

    # Configuración de modelos por proveedor
    HF_MODEL_STRATEGY: str = "Qwen/Qwen2.5-72B-Instruct"
    HF_MODEL_CODE: str = "Qwen/Qwen2.5-Coder-32B-Instruct"
    HF_MODEL_FAST: str = "mistralai/Mistral-7B-Instruct-v0.3"
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Herramientas de Terceros y APIs
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_USERNAME: Optional[str] = None
    VERCEL_TOKEN: Optional[str] = None
    STRIPE_SECRET_KEY: Optional[str] = None
    PAYPAL_CLIENT_ID: Optional[str] = None
    PAYPAL_SECRET: Optional[str] = None
    GUMROAD_TOKEN: Optional[str] = None
    PEXELS_API_KEY: Optional[str] = None
    ELEVENLABS_API_KEY: Optional[str] = None
    NEWS_API_KEY: Optional[str] = None
    SERP_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )

def get_settings() -> Settings:
    return Settings()

settings = get_settings()
