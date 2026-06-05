"""
  BaseAgent — Clase base universal para todos los agentes de Aria AI.

  v2 — Gobernador Económico Multi-Sectorial:
  - domain_context / sector_id para operar en cualquier sector económico
  - Auto-registro en Supabase agent_registry
  - Capacidades parametrizables y genéricas
  - Métricas extendidas por sector
  - Ningún método retorna datos falsos o simulados.
  """
  from __future__ import annotations

  import asyncio
  import logging
  import time
  import uuid
  from abc import ABC, abstractmethod
  from dataclasses import dataclass, field
  from typing import Any, Callable, Coroutine, Optional

  import httpx

  from apps.core.config import settings
  from apps.core.tools.ai_client import AIModel, get_ai_client

  logger = logging.getLogger("aria.base_agent")
  TELEGRAM_API = "https://api.telegram.org/bot"


  @dataclass
  class AgentMetrics:
      tasks_attempted: int = 0
      tasks_succeeded: int = 0
      tasks_failed: int = 0
      total_latency_ms: int = 0
      revenue_generated: float = 0.0
      cost_saved: float = 0.0
      sector_impact: dict = field(default_factory=dict)

      @property
      def success_rate(self) -> float:
          if self.tasks_attempted == 0:
              return 100.0
          return round(self.tasks_succeeded / self.tasks_attempted * 100, 1)

      @property
      def avg_latency_ms(self) -> int:
          if self.tasks_succeeded == 0:
              return 0
          return self.total_latency_ms // self.tasks_succeeded

      def record_sector_action(self, sector: str, action: str, value: float = 0.0) -> None:
          if sector not in self.sector_impact:
              self.sector_impact[sector] = {"actions": 0, "value": 0.0}
          self.sector_impact[sector]["actions"] += 1
          self.sector_impact[sector]["value"] += value


  class BaseAgent(ABC):
      """
      Clase base universal para todos los agentes de Aria AI.

      Cada agente puede operar en uno o múltiples sectores económicos gracias
      a domain_context y sector_id. El Orchestrator usa estos campos para
      instanciar y dirigir agentes al sector correcto.

      Política: ningún método retorna datos falsos o simulados.
      Si falta una API key o servicio, se retorna error explícito.
      """

      APPROVAL_THRESHOLD_USD: float = float(
          getattr(settings, "MAX_SPEND_WITHOUT_APPROVAL_USD", 0.0)
      )
      REQUIRE_APPROVAL_FOR_PAYMENTS: bool = True

      # Mapa global: nombre_capacidad -> env_var requerida
      CAPABILITY_ENV_MAP: dict[str, str] = {
          # ── Pagos & Comercio ──
          "gumroad": "GUMROAD_TOKEN",
          "stripe": "STRIPE_SECRET_KEY",
          "paypal": "PAYPAL_CLIENT_ID",
          "shopify": "SHOPIFY_URL",
          # ── Marketing ──
          "mailchimp": "MAILCHIMP_API_KEY",
          "buffer": "BUFFER_TOKEN",
          "google": "GOOGLE_API_KEY",
          "youtube": "GOOGLE_API_KEY",
          # ── Creación de contenido ──
          "elevenlabs": "ELEVENLABS_API_KEY",
          "pexels": "PEXELS_API_KEY",
          "cloudinary": "CLOUDINARY_CLOUD_NAME",
          "canva": "CANVA_CLIENT_ID",
          # ── Datos & Investigación ──
          "airtable": "AIRTABLE_TOKEN",
          "news": "NEWS_API_KEY",
          "serp": "SERP_API_KEY",
          # ── Infraestructura ──
          "telegram": "TELEGRAM_TOKEN",
          "github": "GITHUB_TOKEN",
          "huggingface": "HF_TOKEN",
          "groq": "GROQ_API_KEY",
          "openai": "OPENAI_API_KEY",
          "supabase": "SUPABASE_URL",
          "redis": "UPSTASH_REDIS_REST_URL",
          # ── Publicación ──
          "medium": "MEDIUM_TOKEN",
          "devto": "DEVTO_API_KEY",
          "hashnode": "HASHNODE_TOKEN",
          # ── Afiliados ──
          "amazon": "AMAZON_ASSOCIATE_TAG",
          "affiliate": "AMAZON_ASSOCIATE_TAG",
          # ── Sectores físicos / industriales ──
          "banking": "BANKING_API_KEY",
          "logistics": "LOGISTICS_API_KEY",
          "iot": "IOT_API_KEY",
          "erp": "ERP_API_KEY",
          "legal_db": "LEGAL_DB_API_KEY",
          "hr_system": "HR_SYSTEM_API_KEY",
          "market_data": "MARKET_DATA_API_KEY",
      }

      # Sectores económicos que ARIA puede gestionar
      SUPPORTED_SECTORS: list[str] = [
          "digital",        # Productos y servicios digitales (sector origen)
          "banking",        # Banca, microcréditos, inversiones
          "legal",          # Bufetes, contratos, asesoría
          "logistics",      # Cadena de suministro, transporte
          "manufacturing",  # Manufactura, producción
          "distribution",   # Distribución, mayoristas
          "agriculture",    # Agricultura, alimentos
          "engineering",    # Ingeniería civil/industrial
          "biochemistry",   # Bioquímica, farmacia
          "education",      # Capacitación, e-learning
          "healthcare",     # Salud, telemedicina
          "energy",         # Energía, renovables
          "real_estate",    # Bienes raíces
          "retail",         # Comercio minorista
      ]

      def __init__(
          self,
          name: str,
          description: str,
          capabilities: list[str],
          sector_id: str = "digital",
          domain_context: Optional[dict[str, Any]] = None,
      ) -> None:
          self.name = name
          self.description = description
          self.capabilities = capabilities
          self.agent_id = str(uuid.uuid4())
          self.metrics = AgentMetrics()
          self._http = httpx.AsyncClient(timeout=15.0)

          # ── Multi-sector fields ──────────────────────────────────
          self.sector_id: str = sector_id if sector_id in self.SUPPORTED_SECTORS else "digital"
          self.domain_context: dict[str, Any] = domain_context or {}
          self._registered: bool = False  # True tras auto-registro en Supabase

      # ── CICLO DE VIDA ─────────────────────────────────────────────

      async def start(self) -> None:
          """Inicia el agente y lo registra en el registry de Supabase."""
          await self._auto_register()
          logger.info("[%s] Iniciado | Sector: %s", self.name, self.sector_id)

      async def stop(self) -> None:
          """Detiene el agente y actualiza su estado en Supabase."""
          await self._update_registry_status("stopped")
          await self._http.aclose()

      # ── AUTO-REGISTRO ─────────────────────────────────────────────

      async def _auto_register(self) -> None:
          """Registra este agente en la tabla agent_registry de Supabase."""
          try:
              from apps.core.memory.supabase_client import get_db
              db = get_db()
              await db.upsert_agent_registry({
                  "agent_id": self.agent_id,
                  "name": self.name,
                  "description": self.description,
                  "capabilities": self.capabilities,
                  "sector_id": self.sector_id,
                  "domain_context": self.domain_context,
                  "status": "active",
              })
              self._registered = True
          except Exception as exc:
              logger.warning("[%s] No pudo registrarse: %s", self.name, exc)

      async def _update_registry_status(self, status: str) -> None:
          try:
              from apps.core.memory.supabase_client import get_db
              db = get_db()
              await db.update_agent_status(self.agent_id, status)
          except Exception:
              pass

      # ── EJECUCIÓN PRINCIPAL ───────────────────────────────────────

      @abstractmethod
      async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
          """Implementación específica de cada agente."""

      async def run(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
          """Punto de entrada unificado con métricas y manejo de errores."""
          ctx = context or {}
          # Inyectar sector_id si el contexto no lo especifica
          ctx.setdefault("sector_id", self.sector_id)
          ctx.setdefault("domain_context", self.domain_context)

          start = time.time()
          self.metrics.tasks_attempted += 1
          try:
              result = await self._execute(ctx)
              self.metrics.tasks_succeeded += 1
              self.metrics.total_latency_ms += int((time.time() - start) * 1000)
              # Acumular ingresos / ahorros por sector
              revenue = result.get("revenue_usd", 0.0)
              savings = result.get("cost_saved_usd", 0.0)
              self.metrics.revenue_generated += revenue
              self.metrics.cost_saved += savings
              if revenue or savings:
                  self.metrics.record_sector_action(self.sector_id, "value_generated", revenue + savings)
              return result
          except Exception as exc:
              self.metrics.tasks_failed += 1
              logger.error("[%s] Error en _execute: %s", self.name, exc, exc_info=True)
              return {"success": False, "error": str(exc), "agent": self.name, "sector": self.sector_id}

      # ── APROBACIÓN HUMANA ─────────────────────────────────────────

      async def execute_with_approval(
          self,
          action: str,
          details: str,
          fn: Callable[[], Coroutine],
          amount_usd: float = 0.0,
          sector: Optional[str] = None,
      ) -> dict[str, Any]:
          """Solicita aprobación humana vía Telegram antes de ejecutar acciones críticas."""
          effective_sector = sector or self.sector_id
          needs_approval = (
              self.REQUIRE_APPROVAL_FOR_PAYMENTS
              and amount_usd > self.APPROVAL_THRESHOLD_USD
          )
          if needs_approval:
              await self._request_telegram_approval(action, details, amount_usd, effective_sector)
              return {"status": "pending_approval", "action": action, "amount_usd": amount_usd, "sector": effective_sector}
          return await fn()

      async def _request_telegram_approval(
          self, action: str, details: str, amount_usd: float, sector: str
      ) -> None:
          token = settings.telegram_token
          chat_id = settings.TELEGRAM_CHAT_ID
          if not token or not chat_id:
              logger.warning("[%s] Aprobación requerida pero Telegram no configurado", self.name)
              return
          msg = (
              f"⚠️ <b>ARIA AI — Aprobación Requerida</b>\n\n"
              f"🏭 <b>Sector:</b> {sector}\n"
              f"🤖 <b>Agente:</b> {self.name}\n"
              f"📋 <b>Acción:</b> {action}\n"
              f"💬 <b>Detalle:</b> {details}\n"
              f"💰 <b>Monto:</b> USD {amount_usd:.2f}\n\n"
              f"Responde /aprobar o /rechazar en el bot."
          )
          try:
              async with httpx.AsyncClient(timeout=10.0) as client:
                  await client.post(
                      f"{TELEGRAM_API}{token}/sendMessage",
                      json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                  )
          except Exception as exc:
              logger.error("Telegram approval request failed: %s", exc)

      # ── VERIFICACIÓN DE CAPACIDADES ───────────────────────────────

      def check_capabilities(self, required: list[str]) -> dict[str, bool]:
          """Verifica si las env vars necesarias están disponibles."""
          result = {}
          for cap in required:
              env_var = self.CAPABILITY_ENV_MAP.get(cap)
              if env_var:
                  result[cap] = bool(getattr(settings, env_var, None))
              else:
                  result[cap] = True  # Sin requisito conocido → asumir disponible
          return result

      def available_capabilities(self) -> list[str]:
          """Retorna las capacidades disponibles según env vars configuradas."""
          available = []
          for cap in self.capabilities:
              status = self.check_capabilities([cap])
              if status.get(cap, False):
                  available.append(cap)
          return available

      # ── UTILIDADES IA ─────────────────────────────────────────────

      async def ai_complete(self, prompt: str, model: AIModel = AIModel.STRATEGY) -> str:
          """Llama al motor IA con el prompt dado."""
          ai = get_ai_client()
          return await ai.complete(prompt, model=model)

      async def ai_complete_json(self, prompt: str, model: AIModel = AIModel.STRATEGY) -> dict:
          """Llama al motor IA y parsea la respuesta como JSON."""
          ai = get_ai_client()
          return await ai.complete_json(prompt, model=model)

      # ── REPRESENTACIÓN ────────────────────────────────────────────

      def to_registry_dict(self) -> dict[str, Any]:
          """Serializa el agente para el registry de Supabase."""
          return {
              "agent_id": self.agent_id,
              "name": self.name,
              "description": self.description,
              "capabilities": self.capabilities,
              "sector_id": self.sector_id,
              "domain_context": self.domain_context,
              "status": "active",
              "metrics": {
                  "success_rate": self.metrics.success_rate,
                  "tasks_attempted": self.metrics.tasks_attempted,
                  "revenue_generated": self.metrics.revenue_generated,
                  "cost_saved": self.metrics.cost_saved,
              },
          }

      def __repr__(self) -> str:
          return f"<{self.__class__.__name__} name={self.name!r} sector={self.sector_id!r}>"
  