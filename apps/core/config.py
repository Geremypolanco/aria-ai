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
    
    # Herramientas de Terceros y APIs (Convertidas a Opcionales)
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_USERNAME: Optional[str] = None
    VERCEL_TOKEN: Optional[str] = None
    STRIPE_SECRET_KEY: Optional[str] = None
    PAYPAL_CLIENT_ID: Optional[str] = None
    PAYPAL_SECRET: Optional[str] = None
    GUMROAD_TOKEN: Optional[str] = None
    PEXELS_API_KEY: Optional[str] = None
    NEWS_API_KEY: Optional[str] = None
    SERP_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env", 
        extra="ignore"
    )

def get_settings() -> Settings:
    return Settings()

settings = get_settings()
