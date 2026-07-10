import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger("aria.attribution")


class RevenueAttributionEngine:
    """
    Motor de Atribución de Ingresos.
    Traza el origen exacto de cada dólar generado.

    Crea un grafo: Contenido → Lead → Venta → $$$
    """

    def __init__(self):
        self.revenue_graph = {}  # Grafo de relaciones económicas

    async def track_conversion_path(
        self, content_id: str, lead_id: str, sale_id: str, revenue: float
    ) -> dict[str, Any]:
        """
        Registra la ruta completa de una venta.

        Ejemplo:
        Video #12 → Lead #5 → Venta #2 → $300
        """
        path = {
            "content_id": content_id,
            "lead_id": lead_id,
            "sale_id": sale_id,
            "revenue": revenue,
            "timestamp": datetime.now().isoformat(),
        }

        # Guardar en grafo
        if content_id not in self.revenue_graph:
            self.revenue_graph[content_id] = {"leads": [], "revenue": 0}

        self.revenue_graph[content_id]["leads"].append(
            {"lead_id": lead_id, "sale_id": sale_id, "revenue": revenue}
        )
        self.revenue_graph[content_id]["revenue"] += revenue

        logger.info(f"[Attribution] {content_id} → ${revenue}")
        return path

    async def get_content_roi(self, content_id: str) -> dict[str, Any]:
        """Calcula el ROI de un contenido específico."""
        if content_id not in self.revenue_graph:
            return {"error": "Contenido no encontrado"}

        data = self.revenue_graph[content_id]
        return {
            "content_id": content_id,
            "total_revenue": data["revenue"],
            "leads_generated": len(data["leads"]),
            "conversion_rate": len(data["leads"]) / max(1, data.get("impressions", 1)),
            "avg_revenue_per_lead": data["revenue"] / max(1, len(data["leads"])),
        }

    async def get_top_performing_content(self, top_n: int = 5) -> list[dict[str, Any]]:
        """Retorna los N contenidos que más dinero generaron."""
        ranked = sorted(self.revenue_graph.items(), key=lambda x: x[1]["revenue"], reverse=True)

        return [
            {"content_id": cid, "revenue": data["revenue"], "leads": len(data["leads"])}
            for cid, data in ranked[:top_n]
        ]

    async def get_revenue_graph_json(self) -> dict[str, Any]:
        """Exporta el grafo completo de ingresos."""
        return {
            "total_revenue": sum(d["revenue"] for d in self.revenue_graph.values()),
            "total_content_pieces": len(self.revenue_graph),
            "graph": self.revenue_graph,
        }
