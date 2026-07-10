import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger("aria.trace")


class TraceEngine:
    """
    Motor de Trazabilidad (inspirado en Langfuse).

    Registra CADA acción de Aria para:
    - Debugging
    - Auditoría
    - Optimización
    - Aprendizaje
    """

    def __init__(self):
        self.traces = []
        self.metrics = {}

    async def trace_action(
        self,
        action_type: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        duration_ms: float,
        success: bool,
        roi: float = 0.0,
    ) -> dict[str, Any]:
        """Registra una acción de Aria."""

        trace = {
            "timestamp": datetime.now().isoformat(),
            "action_type": action_type,
            "input": input_data,
            "output": output_data,
            "duration_ms": duration_ms,
            "success": success,
            "roi": roi,
        }

        self.traces.append(trace)

        # Actualizar métricas
        if action_type not in self.metrics:
            self.metrics[action_type] = {
                "count": 0,
                "success_count": 0,
                "total_roi": 0,
                "avg_duration": 0,
            }

        self.metrics[action_type]["count"] += 1
        if success:
            self.metrics[action_type]["success_count"] += 1
        self.metrics[action_type]["total_roi"] += roi

        logger.info(
            f"[Trace] {action_type}: {'✓' if success else '✗'} (ROI: ${roi}, {duration_ms}ms)"
        )
        return trace

    async def get_action_metrics(self, action_type: str = None) -> dict[str, Any]:
        """Obtiene métricas de acciones."""
        if action_type:
            return self.metrics.get(action_type, {})

        return {
            "total_actions": len(self.traces),
            "total_roi": sum(t.get("roi", 0) for t in self.traces),
            "success_rate": (
                sum(1 for t in self.traces if t.get("success")) / max(1, len(self.traces))
            )
            * 100,
            "avg_duration_ms": (
                sum(t.get("duration_ms", 0) for t in self.traces) / max(1, len(self.traces))
            ),
            "metrics_by_action": self.metrics,
        }

    async def get_failure_analysis(self) -> list[dict[str, Any]]:
        """Analiza fallos para identificar patrones."""
        failures = [t for t in self.traces if not t.get("success")]

        failure_analysis = {}
        for failure in failures:
            action_type = failure.get("action_type")
            if action_type not in failure_analysis:
                failure_analysis[action_type] = []
            failure_analysis[action_type].append(failure)

        return [
            {
                "action_type": atype,
                "failure_count": len(failures),
                "failure_rate": (
                    len(failures) / max(1, self.metrics.get(atype, {}).get("count", 1))
                )
                * 100,
                "recent_failures": failures[-3:],
            }
            for atype, failures in failure_analysis.items()
        ]

    async def export_trace_log(self) -> str:
        """Exporta el log completo de trazas."""
        return json.dumps(
            {
                "total_traces": len(self.traces),
                "metrics": self.metrics,
                "recent_traces": self.traces[-20:],
            },
            indent=2,
        )
