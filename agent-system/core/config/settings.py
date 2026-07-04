"""
ARIA Agent System — Configuración centralizada.
Todas las settings se cargan desde variables de entorno con validación Pydantic.
"""
from __future__ import annotations

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Base de Datos ──
    POSTGRES_USER: str = "aria"
    POSTGRES_PASSWORD: str = "aria_secret_change_me"
    POSTGRES_DB: str = "aria_agents"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: PostgresDsn | None = None

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_url(cls, v: str | None, info) -> str | None:
        if v:
            return v
        values = info.data
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=values.get("POSTGRES_USER", "aria"),
            password=values.get("POSTGRES_PASSWORD", "aria_secret_change_me"),
            host=values.get("POSTGRES_HOST", "localhost"),
            port=values.get("POSTGRES_PORT", 5432),
            path=values.get("POSTGRES_DB", "aria_agents"),
        )

    # ── Redis ──
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_URL: str | None = None

    @field_validator("REDIS_URL", mode="before")
    @classmethod
    def assemble_redis_url(cls, v: str | None, info) -> str:
        if v:
            return v
        values = info.data
        return f"redis://{values.get('REDIS_HOST', 'localhost')}:{values.get('REDIS_PORT', 6379)}/0"

    # ── Vault ──
    VAULT_ADDR: str = "http://localhost:8200"
    VAULT_DEV_ROOT_TOKEN_ID: str = "dev-root-token"
    VAULT_APPROLE_ROLE_ID: str = ""
    VAULT_APPROLE_SECRET_ID: str = ""

    @property
    def vault_token(self) -> str | None:
        """Devuelve el token de Vault: primero AppRole, luego dev token."""
        if self.VAULT_APPROLE_ROLE_ID and self.VAULT_APPROLE_SECRET_ID:
            return None  # Se autentica vía AppRole
        return self.VAULT_DEV_ROOT_TOKEN_ID or None

    # ── API ──
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_SECRET_KEY: str = "change-me-api-secret-2024"

    # ── Sandbox ──
    SANDBOX_IMAGE: str = "agent-sandbox:latest"
    SANDBOX_MEMORY_LIMIT: str = "512m"
    SANDBOX_CPU_LIMIT: float = 1.0
    SANDBOX_TIMEOUT_SECONDS: int = 120

    # ── Browser ──
    BROWSER_IMAGE: str = "agent-browser:latest"
    BROWSER_TIMEOUT_SECONDS: int = 60
    BROWSER_HEADLESS: bool = True

    # ── Logging ──
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"


settings = Settings()
