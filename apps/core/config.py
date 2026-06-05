"""
  Settings centralizados para Aria AI.
  Todos los secrets se cargan desde variables de entorno o Fly.io secrets.
  HuggingFace es el motor principal. Groq y OpenAI son respaldo.
  """
  from typing import Optional
  from pydantic import Field, field_validator
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
          """Compatibilidad: devuelve el token de Telegram disponible."""
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
          """Corrige automáticamente la URL del dashboard a la URL REST del proyecto."""
          if not v:
              return v
          # Si el usuario pegó la URL del dashboard, la convertimos a la API URL
          if "supabase.com/dashboard/project/" in v:
              project_ref = v.rstrip("/").split("/")[-1]
              return f"https://{project_ref}.supabase.co"
          return v

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

      # ── Modelos HF de respaldo ──────────────────────────
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

      # ── MULTIMEDIA ────────────────────────────────────────
      CLOUDINARY_CLOUD_NAME: Optional[str] = None
      CLOUDINARY_API_KEY: Optional[str] = None
      CLOUDINARY_API_SECRET: Optional[str] = None

      # ── DESARROLLO ────────────────────────────────────────
      GITHUB_TOKEN: Optional[str] = None
      GITHUB_USERNAME: str = "Geremypolanco"
      VERCEL_TOKEN: Optional[str] = None
      DID_API_KEY: Optional[str] = None
      CANVA_CLIENT_ID: Optional[str] = None
      CANVA_CLIENT_SECRET: Optional[str] = None

      # ── COMUNICACIÓN ──────────────────────────────────────
      TWILIO_ACCOUNT_SID: Optional[str] = None
      TWILIO_AUTH_TOKEN: Optional[str] = None

      model_config = SettingsConfigDict(
          env_file=".env",
          env_file_encoding="utf-8",
          extra="ignore",
          case_sensitive=True,
      )


  settings = Settings()
  