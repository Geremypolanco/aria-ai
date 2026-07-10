"""
langfuse_client.py — Observabilidad y Rastreo de LLMs para ARIA AI.

Integra Langfuse para:
  - Rastreo detallado de cada llamada a LLM (traces)
  - Monitoreo de costos y uso de tokens
  - Evaluación de latencia y rendimiento de agentes
  - Depuración de flujos complejos de multi-paso

Referencia: https://langfuse.com/docs/sdk/python
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("aria.langfuse")

# ── Langfuse Import con fallback ─────────────────────────────────────────────
try:
    from langfuse import Langfuse

    LANGFUSE_AVAILABLE = True
    logger.info("[Langfuse] SDK cargado correctamente.")
except ImportError:
    LANGFUSE_AVAILABLE = False
    logger.warning("[Langfuse] langfuse no instalado.")


class AriaLangfuseClient:
    """
    Cliente de Observabilidad Langfuse para ARIA.
    Centraliza el monitoreo de todas las interacciones con modelos de lenguaje.
    """

    def __init__(
        self, public_key: str = "", secret_key: str = "", host: str = "https://cloud.langfuse.com"
    ) -> None:
        self.public_key = public_key
        self.secret_key = secret_key
        self.host = host
        self._client = None

        if LANGFUSE_AVAILABLE and public_key and secret_key:
            try:
                self._client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
                logger.info("[Langfuse] Inicializado en %s", host)
            except Exception as exc:
                logger.error("[Langfuse] Error inicializando: %s", exc)

    def trace_interaction(
        self,
        name: str,
        user_id: str,
        input_data: Any,
        output_data: Any,
        metadata: dict[str, Any] | None = None,
    ):
        """Registra un rastro de interacción completo."""
        if not self._client:
            logger.debug("[Langfuse] Rastreo simulado para: %s", name)
            return

        try:
            self._client.trace(
                name=name,
                user_id=user_id,
                input=input_data,
                output=output_data,
                metadata=metadata or {},
            )
            logger.info("[Langfuse] Traza registrada: %s", name)
        except Exception as exc:
            logger.error("[Langfuse] Error registrando traza: %s", exc)


# ── Singleton ────────────────────────────────────────────────────────────────
_langfuse_instance: AriaLangfuseClient | None = None


def get_langfuse_client() -> AriaLangfuseClient:
    """Retorna el singleton del cliente Langfuse."""
    global _langfuse_instance
    if _langfuse_instance is None:
        import os

        _langfuse_instance = AriaLangfuseClient(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
    return _langfuse_instance
