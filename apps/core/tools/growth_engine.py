"""
growth_engine.py — Motor de Revenue & Growth para ARIA AI.

Integra GrowthBook y PostHog para:
  - A/B testing profesional de estrategias de marketing (GrowthBook)
  - Analítica de producto con funnels y conversiones (PostHog)
  - Experimentación continua para optimizar ingresos
  - Seguimiento de eventos de negocio en tiempo real
  - Análisis de cohortes y retención de clientes

ARIA necesita aprender qué funciona. No solo ejecutar.
Este módulo cierra el loop: ejecutar → medir → aprender → optimizar.

Referencia:
  - GrowthBook: https://github.com/growthbook/growthbook-python
  - PostHog: https://github.com/posthog/posthog-python
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("aria.growth_engine")

# ── GrowthBook Import con fallback ───────────────────────────────────────────
try:
    from growthbook import GrowthBook, Experiment, Result
    GROWTHBOOK_AVAILABLE = True
    logger.info("[GrowthBook] Librería cargada correctamente.")
except ImportError:
    GROWTHBOOK_AVAILABLE = False
    logger.warning(
        "[GrowthBook] growthbook no instalado. "
        "Usando A/B testing nativo. "
        "Instala con: pip install growthbook"
    )
    GrowthBook = None  # type: ignore[assignment,misc]
    Experiment = None  # type: ignore[assignment,misc]

# ── PostHog Import con fallback ──────────────────────────────────────────────
try:
    import posthog
    POSTHOG_AVAILABLE = True
    logger.info("[PostHog] Librería cargada correctamente.")
except ImportError:
    POSTHOG_AVAILABLE = False
    logger.warning(
        "[PostHog] posthog no instalado. "
        "Usando logging nativo. "
        "Instala con: pip install posthog"
    )
    posthog = None  # type: ignore[assignment]


# ── GrowthBook Engine ────────────────────────────────────────────────────────

class AriaGrowthBookEngine:
    """
    Motor de A/B Testing para ARIA AI con GrowthBook.

    Permite a ARIA experimentar con diferentes estrategias y aprender
    cuáles generan más ingresos y conversiones.

    Experimentos típicos de ARIA:
    - Precio de ebooks ($7 vs $17 vs $27)
    - Horario de publicación de contenido (mañana vs tarde vs noche)
    - Tipo de CTA en emails (urgencia vs beneficio vs social proof)
    - Canal de distribución (TikTok vs Instagram vs Twitter)
    - Longitud de email de ventas (corto vs largo)

    Uso:
        engine = AriaGrowthBookEngine()

        # Crear experimento de precio
        variant = engine.get_variant(
            experiment_id="ebook_price_test",
            user_id="campaign_001",
            variants=["$7", "$17", "$27"],
        )
        print(f"Precio a usar: {variant}")

        # Registrar conversión
        engine.track_conversion(
            experiment_id="ebook_price_test",
            user_id="campaign_001",
            value=17.0,
        )
    """

    def __init__(
        self,
        api_host: str = "http://localhost:3100",
        client_key: str = "",
    ) -> None:
        self._api_host = api_host
        self._client_key = client_key
        self._experiments: dict[str, dict] = {}
        self._results: list[dict] = []

    def get_variant(
        self,
        experiment_id: str,
        user_id: str,
        variants: list[Any],
        weights: list[float] | None = None,
    ) -> Any:
        """
        Obtiene la variante asignada para un usuario en un experimento.

        Usa hashing determinístico para asignación consistente.
        El mismo user_id siempre recibe la misma variante.

        Args:
            experiment_id: ID único del experimento
            user_id: ID del usuario o campaña
            variants: Lista de variantes posibles
            weights: Pesos de distribución (default: igual distribución)

        Returns:
            La variante asignada al usuario
        """
        if not variants:
            return None

        if GROWTHBOOK_AVAILABLE and GrowthBook is not None:
            try:
                gb = GrowthBook(
                    attributes={"id": user_id},
                    api_host=self._api_host,
                    client_key=self._client_key,
                )
                exp = Experiment(
                    key=experiment_id,
                    variations=variants,
                    weights=weights,
                )
                result = gb.run(exp)
                variant = result.value

                # Registrar asignación
                self._record_assignment(experiment_id, user_id, variant, result.in_experiment)
                return variant

            except Exception as exc:
                logger.warning("[GrowthBook] Error en experimento %s: %s", experiment_id, exc)

        # Fallback: hashing determinístico
        return self._hash_variant(experiment_id, user_id, variants, weights)

    def _hash_variant(
        self,
        experiment_id: str,
        user_id: str,
        variants: list[Any],
        weights: list[float] | None = None,
    ) -> Any:
        """Asignación determinística por hash cuando GrowthBook no está disponible."""
        hash_input = f"{experiment_id}_{user_id}"
        hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)

        if weights:
            # Distribución ponderada
            cumulative = 0.0
            normalized_hash = (hash_value % 10000) / 10000.0
            for variant, weight in zip(variants, weights):
                cumulative += weight
                if normalized_hash <= cumulative:
                    return variant
            return variants[-1]
        else:
            # Distribución uniforme
            return variants[hash_value % len(variants)]

    def _record_assignment(
        self,
        experiment_id: str,
        user_id: str,
        variant: Any,
        in_experiment: bool,
    ) -> None:
        """Registra la asignación de variante."""
        if experiment_id not in self._experiments:
            self._experiments[experiment_id] = {
                "id": experiment_id,
                "assignments": {},
                "conversions": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        self._experiments[experiment_id]["assignments"][user_id] = {
            "variant": variant,
            "in_experiment": in_experiment,
            "assigned_at": datetime.now(timezone.utc).isoformat(),
        }

    def track_conversion(
        self,
        experiment_id: str,
        user_id: str,
        value: float = 1.0,
        metric: str = "revenue",
    ) -> None:
        """
        Registra una conversión para un experimento.

        Args:
            experiment_id: ID del experimento
            user_id: ID del usuario
            value: Valor de la conversión (ej: $27.0 para una venta)
            metric: Métrica a trackear ('revenue', 'conversion', 'clicks')
        """
        conversion = {
            "experiment_id": experiment_id,
            "user_id": user_id,
            "value": value,
            "metric": metric,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._results.append(conversion)

        if experiment_id in self._experiments:
            self._experiments[experiment_id]["conversions"].append(conversion)

        logger.info(
            "[GrowthBook] Conversión registrada: exp=%s user=%s value=%.2f",
            experiment_id, user_id, value,
        )

    def get_experiment_results(self, experiment_id: str) -> dict[str, Any]:
        """
        Obtiene los resultados estadísticos de un experimento.

        Returns:
            Análisis de resultados por variante con métricas clave
        """
        if experiment_id not in self._experiments:
            return {"error": f"Experimento '{experiment_id}' no encontrado"}

        exp = self._experiments[experiment_id]
        assignments = exp.get("assignments", {})
        conversions = exp.get("conversions", [])

        # Agrupar por variante
        variant_stats: dict[str, dict] = {}
        for user_id, assignment in assignments.items():
            variant = str(assignment["variant"])
            if variant not in variant_stats:
                variant_stats[variant] = {"users": 0, "conversions": 0, "total_value": 0.0}
            variant_stats[variant]["users"] += 1

        for conv in conversions:
            user_id = conv["user_id"]
            if user_id in assignments:
                variant = str(assignments[user_id]["variant"])
                if variant in variant_stats:
                    variant_stats[variant]["conversions"] += 1
                    variant_stats[variant]["total_value"] += conv.get("value", 0.0)

        # Calcular métricas
        for variant, stats in variant_stats.items():
            users = stats["users"]
            stats["conversion_rate"] = stats["conversions"] / users if users > 0 else 0.0
            stats["avg_value"] = stats["total_value"] / max(stats["conversions"], 1)

        return {
            "experiment_id": experiment_id,
            "total_users": len(assignments),
            "total_conversions": len(conversions),
            "variants": variant_stats,
            "winner": max(variant_stats.items(), key=lambda x: x[1]["total_value"])[0]
            if variant_stats else None,
        }

    def get_all_experiments(self) -> list[dict[str, Any]]:
        """Lista todos los experimentos activos."""
        return [
            {
                "id": exp_id,
                "users": len(exp.get("assignments", {})),
                "conversions": len(exp.get("conversions", [])),
                "created_at": exp.get("created_at", ""),
            }
            for exp_id, exp in self._experiments.items()
        ]


# ── PostHog Analytics Engine ─────────────────────────────────────────────────

class AriaPostHogEngine:
    """
    Motor de Analítica de Producto para ARIA AI con PostHog.

    Permite a ARIA medir:
    - Funnels de conversión completos (contenido → lead → venta)
    - Eventos de negocio en tiempo real
    - Cohortes de clientes y retención
    - Feature flags para rollouts graduales
    - Session recordings para análisis de comportamiento

    Para un Revenue Engine es casi obligatorio.

    Uso:
        engine = AriaPostHogEngine()

        # Trackear evento de negocio
        engine.capture_event(
            distinct_id="campaign_001",
            event="sale_completed",
            properties={"amount": 27.0, "product": "Ebook Fitness", "channel": "tiktok"}
        )

        # Identificar usuario/campaña
        engine.identify(
            distinct_id="campaign_001",
            properties={"niche": "fitness", "total_revenue": 270.0}
        )
    """

    def __init__(
        self,
        api_key: str = "",
        host: str = "https://app.posthog.com",
    ) -> None:
        self._api_key = api_key
        self._host = host
        self._initialized = False
        self._event_buffer: list[dict] = []

        if POSTHOG_AVAILABLE and api_key and posthog is not None:
            try:
                posthog.project_api_key = api_key
                posthog.host = host
                posthog.debug = False
                self._initialized = True
                logger.info("[PostHog] Inicializado correctamente (host=%s)", host)
            except Exception as exc:
                logger.warning("[PostHog] Error inicializando: %s", exc)

    def capture_event(
        self,
        distinct_id: str,
        event: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """
        Captura un evento de negocio en PostHog.

        Args:
            distinct_id: ID único del usuario, campaña o agente
            event: Nombre del evento (ej: 'sale_completed', 'content_published')
            properties: Propiedades del evento (amount, channel, niche, etc.)
        """
        props = properties or {}
        props["timestamp"] = datetime.now(timezone.utc).isoformat()
        props["source"] = "aria_ai"

        event_data = {
            "distinct_id": distinct_id,
            "event": event,
            "properties": props,
            "timestamp": props["timestamp"],
        }

        if self._initialized and posthog is not None:
            try:
                posthog.capture(
                    distinct_id=distinct_id,
                    event=event,
                    properties=props,
                )
                logger.debug("[PostHog] Evento capturado: %s | %s", event, distinct_id)
            except Exception as exc:
                logger.warning("[PostHog] Error capturando evento: %s", exc)
                self._event_buffer.append(event_data)
        else:
            # Buffer local cuando PostHog no está disponible
            self._event_buffer.append(event_data)
            logger.debug("[PostHog] Evento en buffer: %s | %s", event, distinct_id)

    def identify(
        self,
        distinct_id: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """
        Identifica un usuario/campaña con sus propiedades.

        Args:
            distinct_id: ID único
            properties: Propiedades del perfil (niche, total_revenue, etc.)
        """
        if self._initialized and posthog is not None:
            try:
                posthog.identify(
                    distinct_id=distinct_id,
                    properties=properties or {},
                )
            except Exception as exc:
                logger.warning("[PostHog] Error en identify: %s", exc)

    def capture_funnel_step(
        self,
        funnel_id: str,
        step: str,
        distinct_id: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """
        Captura un paso en un funnel de conversión.

        Funnels típicos de ARIA:
        - content_funnel: content_created → lead_generated → email_sent → sale_completed
        - product_funnel: idea_generated → product_created → published → first_sale
        - campaign_funnel: campaign_started → content_published → engagement → conversion

        Args:
            funnel_id: ID del funnel (ej: 'content_to_sale')
            step: Paso actual (ej: 'lead_generated')
            distinct_id: ID del usuario/campaña
            properties: Datos adicionales del paso
        """
        props = properties or {}
        props["funnel_id"] = funnel_id
        props["funnel_step"] = step

        self.capture_event(
            distinct_id=distinct_id,
            event=f"funnel_{funnel_id}_{step}",
            properties=props,
        )

    def capture_revenue_event(
        self,
        amount_usd: float,
        channel: str,
        product: str,
        campaign_id: str = "",
        agent: str = "",
    ) -> None:
        """
        Captura un evento de ingresos para análisis de Revenue Attribution.

        Args:
            amount_usd: Monto en USD
            channel: Canal de origen (tiktok, email, organic, etc.)
            product: Producto vendido
            campaign_id: ID de la campaña que generó la venta
            agent: Agente de ARIA que ejecutó la acción
        """
        distinct_id = campaign_id or f"revenue_{channel}_{datetime.now().strftime('%Y%m%d')}"

        self.capture_event(
            distinct_id=distinct_id,
            event="revenue_generated",
            properties={
                "amount_usd": amount_usd,
                "channel": channel,
                "product": product,
                "campaign_id": campaign_id,
                "agent": agent,
                "currency": "USD",
            },
        )

    def capture_agent_action(
        self,
        agent_name: str,
        action: str,
        success: bool,
        duration_ms: int = 0,
        roi: float = 0.0,
    ) -> None:
        """
        Captura una acción de agente para análisis de performance.

        Args:
            agent_name: Nombre del agente (orchestrator, cfo, marketing, etc.)
            action: Acción ejecutada
            success: Si fue exitosa
            duration_ms: Duración en milisegundos
            roi: ROI generado
        """
        self.capture_event(
            distinct_id=f"agent_{agent_name}",
            event="agent_action",
            properties={
                "agent": agent_name,
                "action": action,
                "success": success,
                "duration_ms": duration_ms,
                "roi_usd": roi,
            },
        )

    def get_buffered_events(self) -> list[dict[str, Any]]:
        """Retorna los eventos en buffer (cuando PostHog no está disponible)."""
        return self._event_buffer.copy()

    def flush_buffer(self) -> int:
        """Vacía el buffer de eventos y retorna el número de eventos."""
        count = len(self._event_buffer)
        self._event_buffer.clear()
        return count

    def get_status(self) -> dict[str, Any]:
        """Estado del motor PostHog."""
        return {
            "posthog_available": POSTHOG_AVAILABLE,
            "initialized": self._initialized,
            "api_key_configured": bool(self._api_key),
            "buffered_events": len(self._event_buffer),
            "host": self._host,
        }


# ── Motor Unificado de Growth ────────────────────────────────────────────────

class AriaGrowthEngine:
    """
    Motor unificado de Revenue & Growth para ARIA AI.

    Combina GrowthBook (A/B testing) y PostHog (analítica) para
    cerrar el loop de aprendizaje continuo:

        Ejecutar → Medir → Aprender → Optimizar → Ejecutar

    Integra con:
    - ExecutionPipeline (medir resultados de cada ejecución)
    - MarketingAgent (optimizar campañas)
    - CFO Agent (atribuir ingresos)
    - EvolutionAgent (aprender y mejorar)
    """

    def __init__(
        self,
        posthog_api_key: str = "",
        posthog_host: str = "https://app.posthog.com",
        growthbook_api_host: str = "http://localhost:3100",
        growthbook_client_key: str = "",
    ) -> None:
        self.ab_testing = AriaGrowthBookEngine(
            api_host=growthbook_api_host,
            client_key=growthbook_client_key,
        )
        self.analytics = AriaPostHogEngine(
            api_key=posthog_api_key,
            host=posthog_host,
        )

    async def run_experiment(
        self,
        experiment_id: str,
        variants: list[Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Ejecuta un experimento completo: asigna variante y trackea en PostHog.

        Args:
            experiment_id: ID único del experimento
            variants: Variantes a probar
            context: Contexto adicional (niche, campaign_id, etc.)

        Returns:
            Dict con la variante asignada y metadata del experimento
        """
        ctx = context or {}
        user_id = ctx.get("campaign_id") or ctx.get("user_id") or str(uuid.uuid4())

        # Asignar variante con GrowthBook
        variant = self.ab_testing.get_variant(
            experiment_id=experiment_id,
            user_id=user_id,
            variants=variants,
        )

        # Trackear en PostHog
        self.analytics.capture_event(
            distinct_id=user_id,
            event="experiment_started",
            properties={
                "experiment_id": experiment_id,
                "variant": str(variant),
                **ctx,
            },
        )

        logger.info("[GrowthEngine] Experimento %s: user=%s variante=%s", experiment_id, user_id, variant)

        return {
            "experiment_id": experiment_id,
            "user_id": user_id,
            "variant": variant,
            "context": ctx,
        }

    async def record_outcome(
        self,
        experiment_id: str,
        user_id: str,
        success: bool,
        revenue_usd: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Registra el resultado de un experimento.

        Args:
            experiment_id: ID del experimento
            user_id: ID del usuario
            success: Si fue exitoso
            revenue_usd: Ingresos generados
            metadata: Datos adicionales
        """
        # Registrar conversión en GrowthBook
        if success or revenue_usd > 0:
            self.ab_testing.track_conversion(
                experiment_id=experiment_id,
                user_id=user_id,
                value=revenue_usd,
                metric="revenue",
            )

        # Trackear en PostHog
        self.analytics.capture_event(
            distinct_id=user_id,
            event="experiment_outcome",
            properties={
                "experiment_id": experiment_id,
                "success": success,
                "revenue_usd": revenue_usd,
                **(metadata or {}),
            },
        )

    def get_full_report(self) -> dict[str, Any]:
        """Reporte completo del estado de growth."""
        return {
            "experiments": self.ab_testing.get_all_experiments(),
            "analytics_status": self.analytics.get_status(),
            "growthbook_available": GROWTHBOOK_AVAILABLE,
            "posthog_available": POSTHOG_AVAILABLE,
        }


# ── Singleton ────────────────────────────────────────────────────────────────
_growth_engine_instance: AriaGrowthEngine | None = None


def get_growth_engine() -> AriaGrowthEngine:
    """Retorna el singleton del motor de Growth de ARIA."""
    global _growth_engine_instance
    if _growth_engine_instance is None:
        import os
        _growth_engine_instance = AriaGrowthEngine(
            posthog_api_key=os.getenv("POSTHOG_API_KEY", ""),
            posthog_host=os.getenv("POSTHOG_HOST", "https://app.posthog.com"),
            growthbook_api_host=os.getenv("GROWTHBOOK_API_HOST", "http://localhost:3100"),
            growthbook_client_key=os.getenv("GROWTHBOOK_CLIENT_KEY", ""),
        )
    return _growth_engine_instance
