"""
ARIA Agent System — Circuit Breaker.
Patrón de resiliencia: si un agente falla N veces seguidas, el circuito se abre
y la tarea se pausa para intervención humana.

Estados del circuito:
  CLOSED  → Funcionamiento normal
  OPEN    → Fallos detectados, rechazar operaciones
  HALF_OPEN → Probando si el servicio se recuperó
"""
from __future__ import annotations

import asyncio
import logging
import time
from enum import StrEnum
from typing import Any

logger = logging.getLogger("aria.resilience.circuit_breaker")


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Circuit Breaker por agente/tool.

    Configuración:
    - failure_threshold: Número de fallos consecutivos para abrir el circuito
    - recovery_timeout: Segundos a esperar antes de probar half-open
    - half_open_max_retries: Intentos en half-open antes de decidir
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: int = 30,
        half_open_max_retries: int = 2,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_retries = half_open_max_retries

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._half_open_attempts = 0
        self._total_failures = 0
        self._total_successes = 0
        self._last_error: str | None = None

    # ── Propiedades ──

    @property
    def state(self) -> CircuitState:
        """Estado actual del circuito."""
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_attempts = 0
                logger.info("CircuitBreaker[%s]: OPEN → HALF_OPEN", self.name)
        return self._state

    @property
    def is_available(self) -> bool:
        """¿El circuito permite ejecutar operaciones?"""
        return self.state != CircuitState.OPEN

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "last_error": self._last_error,
            "last_failure_seconds_ago": round(time.time() - self._last_failure_time, 1) if self._last_failure_time else None,
        }

    # ── Operaciones ──

    async def call(self, coro, *args, **kwargs) -> Any:
        """
        Ejecuta una operación protegida por el circuit breaker.

        Si el circuito está OPEN, lanza CircuitBreakerOpenError.
        Si la operación falla, incrementa contador de fallos.
        Si tiene éxito en HALF_OPEN, cierra el circuito.
        """
        current_state = self.state

        if current_state == CircuitState.OPEN:
            raise CircuitBreakerOpenError(
                f"CircuitBreaker[{self.name}]: circuito abierto tras "
                f"{self._failure_count} fallos. Reintentar en "
                f"{max(0, self.recovery_timeout - (time.time() - self._last_failure_time)):.0f}s"
            )

        try:
            result = await coro(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure(str(e)[:200])
            raise

    def _on_success(self) -> None:
        """Registra un éxito."""
        self._total_successes += 1

        if self._state == CircuitState.HALF_OPEN:
            self._half_open_attempts += 1
            self._success_count += 1
            if self._success_count >= self.half_open_max_retries:
                self._reset()
                logger.info(
                    "CircuitBreaker[%s]: HALF_OPEN → CLOSED (%d éxitos)",
                    self.name,
                    self._success_count,
                )
        else:
            # CLOSED: resetear contador de fallos periódicamente
            self._failure_count = max(0, self._failure_count - 1)

    def _on_failure(self, error: str) -> None:
        """Registra un fallo."""
        self._total_failures += 1
        self._failure_count += 1
        self._last_failure_time = time.time()
        self._last_error = error

        if self._state == CircuitState.HALF_OPEN:
            # Falló en half-open → volver a OPEN
            self._state = CircuitState.OPEN
            self._half_open_attempts = 0
            self._success_count = 0
            logger.warning(
                "CircuitBreaker[%s]: HALF_OPEN → OPEN (falló en recuperación)",
                self.name,
            )
        elif self._failure_count >= self.failure_threshold:
            # Umbral alcanzado → abrir circuito
            self._state = CircuitState.OPEN
            logger.error(
                "CircuitBreaker[%s]: CLOSED → OPEN (%d fallos consecutivos)",
                self.name,
                self._failure_count,
            )

    def _reset(self) -> None:
        """Resetea el circuito a estado cerrado."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_attempts = 0
        self._last_error = None

    def force_open(self, reason: str = "forced") -> None:
        """Fuerza la apertura del circuito (para mantenimiento)."""
        self._state = CircuitState.OPEN
        self._failure_count = self.failure_threshold
        self._last_failure_time = time.time()
        self._last_error = f"Forced open: {reason}"
        logger.warning("CircuitBreaker[%s]: forzado a OPEN: %s", self.name, reason)

    def force_close(self) -> None:
        """Fuerza el cierre del circuito."""
        self._reset()
        logger.info("CircuitBreaker[%s]: forzado a CLOSED", self.name)


class CircuitBreakerOpenError(Exception):
    """Error lanzado cuando el circuito está abierto."""
    pass


class CircuitBreakerRegistry:
    """
    Registro global de circuit breakers.
    Cada agente y herramienta tiene su propio breaker.
    """

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_or_create(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: int = 30,
    ) -> CircuitBreaker:
        """Obtiene o crea un circuit breaker."""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
        return self._breakers[name]

    def get(self, name: str) -> CircuitBreaker | None:
        """Obtiene un breaker existente."""
        return self._breakers.get(name)

    def all_stats(self) -> dict[str, dict[str, Any]]:
        """Estadísticas de todos los breakers."""
        return {name: breaker.stats for name, breaker in self._breakers.items()}

    def reset_all(self) -> None:
        """Resetea todos los breakers."""
        for breaker in self._breakers.values():
            breaker.force_close()

    @property
    def open_breakers(self) -> list[str]:
        """Lista de breakers en estado OPEN."""
        return [
            name for name, breaker in self._breakers.items()
            if breaker.state == CircuitState.OPEN
        ]


# Singleton global
circuit_breaker_registry = CircuitBreakerRegistry()