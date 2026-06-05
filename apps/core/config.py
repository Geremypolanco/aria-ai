"""
  Settings centralizados para Aria AI — v2 Gobernador Económico.

  Novedades:
  - Configuración por sector/dominio (SECTOR_CONFIGS)
  - Credenciales dinámicas por sector (get_sector_credentials)
  - Variables para sectores físicos: banca, legal, logística, IoT, ERP, RRHH
  - Motor IA: HuggingFace primario → Groq → OpenAI
  - Todos los secretos se cargan desde variables de entorno o Fly.io secrets.
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
      GROQ_MODEL_FAST: str = "llama-3.1-8b-instant"
      GROQ_MODEL_CODE: str = "llama-3.3-70b-versatile"

      # ── OpenAI (respaldo 2) ───────────────────────────────
      OPENAI_API_KEY: Optional[str] = None
      OPENAI_MODEL: str = "gpt-4o-mini"

      # ── GitHub & CI/CD ────────────────────────────────────
      GITHUB_TOKEN: Optional[str] = None
      GITHUB_REPO: str = "Geremypolanco/aria-ai"
      FLY_API_TOKEN: Optional[str] = None
      FLY_APP_NAME: str = "aria-ai"

      # ── Publicación ───────────────────────────────────────
      MEDIUM_TOKEN: Optional[str] = None
      DEVTO_API_KEY: Optional[str] = None
      HASHNODE_TOKEN: Optional[str] = None

      # ── Comercio digital ──────────────────────────────────
      GUMROAD_TOKEN: Optional[str] = None
      STRIPE_SECRET_KEY: Optional[str] = None
      PAYPAL_CLIENT_ID: Optional[str] = None
      SHOPIFY_URL: Optional[str] = None
      SHOPIFY_TOKEN: Optional[str] = None

      # ── Marketing ─────────────────────────────────────────
      MAILCHIMP_API_KEY: Optional[str] = None
      MAILCHIMP_SERVER: Optional[str] = None
      BUFFER_TOKEN: Optional[str] = None
      GOOGLE_API_KEY: Optional[str] = None
      SERP_API_KEY: Optional[str] = None
      NEWS_API_KEY: Optional[str] = None

      # ── Contenido & Medios ────────────────────────────────
      ELEVENLABS_API_KEY: Optional[str] = None
      PEXELS_API_KEY: Optional[str] = None
      CLOUDINARY_CLOUD_NAME: Optional[str] = None
      CLOUDINARY_API_KEY: Optional[str] = None
      CLOUDINARY_API_SECRET: Optional[str] = None
      CANVA_CLIENT_ID: Optional[str] = None

      # ── Datos & Productividad ─────────────────────────────
      AIRTABLE_TOKEN: Optional[str] = None
      AMAZON_ASSOCIATE_TAG: Optional[str] = None
      IMPACT_ACCOUNT_SID: Optional[str] = None

      # ── SECTORES FÍSICOS — credenciales por sector ────────
      BANKING_API_KEY: Optional[str] = None
      BANKING_API_URL: Optional[str] = None
      OPEN_BANKING_CLIENT_ID: Optional[str] = None
      OPEN_BANKING_SECRET: Optional[str] = None
      LEGAL_DB_API_KEY: Optional[str] = None
      LEGAL_DB_API_URL: Optional[str] = None
      LOGISTICS_API_KEY: Optional[str] = None
      LOGISTICS_API_URL: Optional[str] = None
      FREIGHT_API_KEY: Optional[str] = None
      IOT_API_KEY: Optional[str] = None
      IOT_BROKER_URL: Optional[str] = None
      ERP_API_KEY: Optional[str] = None
      ERP_API_URL: Optional[str] = None
      HR_SYSTEM_API_KEY: Optional[str] = None
      HR_SYSTEM_API_URL: Optional[str] = None
      PAYROLL_API_KEY: Optional[str] = None
      MARKET_DATA_API_KEY: Optional[str] = None
      MARKET_DATA_API_URL: Optional[str] = None
      AGRO_API_KEY: Optional[str] = None
      WEATHER_API_KEY: Optional[str] = None

      def get_sector_credentials(self, sector: str) -> dict[str, Any]:
          """Retorna credenciales relevantes para un sector económico dado."""
          sector_cred_map: dict[str, list[str]] = {
              "digital":       ["GUMROAD_TOKEN", "STRIPE_SECRET_KEY", "SHOPIFY_URL", "SHOPIFY_TOKEN"],
              "banking":       ["BANKING_API_KEY", "BANKING_API_URL", "OPEN_BANKING_CLIENT_ID"],
              "legal":         ["LEGAL_DB_API_KEY", "LEGAL_DB_API_URL"],
              "logistics":     ["LOGISTICS_API_KEY", "LOGISTICS_API_URL", "FREIGHT_API_KEY"],
              "manufacturing": ["ERP_API_KEY", "ERP_API_URL", "IOT_API_KEY", "IOT_BROKER_URL"],
              "distribution":  ["LOGISTICS_API_KEY", "ERP_API_KEY"],
              "agriculture":   ["AGRO_API_KEY", "WEATHER_API_KEY"],
              "engineering":   ["ERP_API_KEY", "IOT_API_KEY"],
              "biochemistry":  ["ERP_API_KEY", "MARKET_DATA_API_KEY"],
              "education":     ["MAILCHIMP_API_KEY", "GUMROAD_TOKEN"],
              "healthcare":    ["ERP_API_KEY", "LEGAL_DB_API_KEY"],
              "energy":        ["IOT_API_KEY", "IOT_BROKER_URL", "MARKET_DATA_API_KEY"],
              "real_estate":   ["MARKET_DATA_API_KEY", "LEGAL_DB_API_KEY"],
              "retail":        ["SHOPIFY_URL", "SHOPIFY_TOKEN", "STRIPE_SECRET_KEY"],
          }
          keys = sector_cred_map.get(sector, [])
          return {key: getattr(self, key) for key in keys if getattr(self, key, None)}

      # ── GOBERNADOR ECONÓMICO ──────────────────────────────
      CIRCULAR_ECONOMY_REINVEST_RATE: float = 0.4
      CIRCULAR_ECONOMY_RESERVE_RATE: float = 0.2
      CIRCULAR_ECONOMY_COMMUNITY_RATE: float = 0.1
      PRICE_STABILITY_TARGET_VARIANCE: float = 0.05
      CAPITAL_ALLOCATION_INTERVAL_HOURS: int = 24

      model_config = SettingsConfigDict(
          env_file=".env",
          env_file_encoding="utf-8",
          extra="ignore",
      )


  settings = Settings()
  