import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger("aria.attribution")


class RevenueAttributionEngine:
    """
    Revenue Attribution Engine.
    Traces the exact origin of every dollar generated.

    Builds a graph: Content → Lead → Sale → $$$
    """

    def __init__(self):
        self.revenue_graph = {}  # Graph of economic relationships

    async def track_conversion_path(
        self, content_id: str, lead_id: str, sale_id: str, revenue: float
    ) -> dict[str, Any]:
        """
        Records the complete path of a sale.

        Example:
        Video #12 → Lead #5 → Sale #2 → $300
        """
        path = {
            "content_id": content_id,
            "lead_id": lead_id,
            "sale_id": sale_id,
            "revenue": revenue,
            "timestamp": datetime.now().isoformat(),
        }

        # Save to graph
        if content_id not in self.revenue_graph:
            self.revenue_graph[content_id] = {"leads": [], "revenue": 0}

        self.revenue_graph[content_id]["leads"].append(
            {"lead_id": lead_id, "sale_id": sale_id, "revenue": revenue}
        )
        self.revenue_graph[content_id]["revenue"] += revenue

        logger.info(f"[Attribution] {content_id} → ${revenue}")
        return path

    async def get_content_roi(self, content_id: str) -> dict[str, Any]:
        """Calculates the ROI of a specific piece of content."""
        if content_id not in self.revenue_graph:
            return {"error": "Content not found"}

        data = self.revenue_graph[content_id]
        return {
            "content_id": content_id,
            "total_revenue": data["revenue"],
            "leads_generated": len(data["leads"]),
            "conversion_rate": len(data["leads"]) / max(1, data.get("impressions", 1)),
            "avg_revenue_per_lead": data["revenue"] / max(1, len(data["leads"])),
        }

    async def get_top_performing_content(self, top_n: int = 5) -> list[dict[str, Any]]:
        """Returns the top N content pieces that generated the most revenue."""
        ranked = sorted(self.revenue_graph.items(), key=lambda x: x[1]["revenue"], reverse=True)

        return [
            {"content_id": cid, "revenue": data["revenue"], "leads": len(data["leads"])}
            for cid, data in ranked[:top_n]
        ]

    async def get_revenue_graph_json(self) -> dict[str, Any]:
        """Exports the complete revenue graph."""
        return {
            "total_revenue": sum(d["revenue"] for d in self.revenue_graph.values()),
            "total_content_pieces": len(self.revenue_graph),
            "graph": self.revenue_graph,
        }
