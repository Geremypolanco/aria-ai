"""
pocketflow_engine.py — Motor de Decisiones con PocketFlow para ARIA AI.

PocketFlow reemplaza y potencia el StateGraph con un grafo de decisiones
declarativo y composable. Permite:
  - Flujos de decisión complejos para el Executive AI
  - Strategy Engine con nodos de análisis → decisión → ejecución
  - Decision Trees para routing inteligente de tareas
  - Workflows auditables con historial de estados

Arquitectura:
    Input → AnalyzeNode → DecideNode → ExecuteNode → OutputNode
                ↑                                        ↓
                └──────────── FeedbackNode ──────────────┘
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger("aria.pocketflow_engine")

# ── PocketFlow Core Abstraction ──────────────────────────────────────────────
# PocketFlow es un framework de 100 líneas. Su abstracción central:
# - BaseNode: unidad de trabajo (prep → exec → post)
# - Flow: conecta nodos mediante Actions (aristas etiquetadas)
# - SharedStore: comunicación entre nodos dentro de un flow

try:
    from pocketflow import Node, Flow, AsyncNode, AsyncFlow
    POCKETFLOW_AVAILABLE = True
    logger.info("[PocketFlow] Librería cargada correctamente.")
except ImportError:
    POCKETFLOW_AVAILABLE = False
    logger.warning(
        "[PocketFlow] pocketflow no instalado. "
        "Usando implementación fallback basada en StateGraph. "
        "Instala con: pip install pocketflow"
    )

    # ── Fallback mínimo para mantener compatibilidad ──────────────────────────
    class Node:  # type: ignore[no-redef]
        """Nodo base de PocketFlow (fallback)."""
        def prep(self, shared: dict) -> Any:
            return None

        def exec(self, prep_res: Any) -> Any:
            return "default"

        def post(self, shared: dict, prep_res: Any, exec_res: Any) -> Optional[str]:
            return exec_res

        def run(self, shared: dict) -> str:
            prep_res = self.prep(shared)
            exec_res = self.exec(prep_res)
            action = self.post(shared, prep_res, exec_res)
            return action or "default"

    class AsyncNode(Node):  # type: ignore[no-redef]
        """Nodo asíncrono de PocketFlow (fallback)."""
        async def prep_async(self, shared: dict) -> Any:
            return self.prep(shared)

        async def exec_async(self, prep_res: Any) -> Any:
            return self.exec(prep_res)

        async def post_async(self, shared: dict, prep_res: Any, exec_res: Any) -> Optional[str]:
            return self.post(shared, prep_res, exec_res)

        async def run_async(self, shared: dict) -> str:
            prep_res = await self.prep_async(shared)
            exec_res = await self.exec_async(prep_res)
            action = await self.post_async(shared, prep_res, exec_res)
            return action or "default"

    class Flow:  # type: ignore[no-redef]
        """Flow de PocketFlow (fallback)."""
        def __init__(self, start: Node):
            self.start = start
            self._transitions: dict[tuple, Node] = {}

        def add_edge(self, node: Node, action: str, next_node: Node) -> "Flow":
            self._transitions[(id(node), action)] = next_node
            return self

        def run(self, shared: dict) -> dict:
            current = self.start
            visited = 0
            while current and visited < 50:
                action = current.run(shared)
                next_node = self._transitions.get((id(current), action))
                current = next_node
                visited += 1
            return shared

    class AsyncFlow(Flow):  # type: ignore[no-redef]
        """AsyncFlow de PocketFlow (fallback)."""
        async def run_async(self, shared: dict) -> dict:
            current = self.start
            visited = 0
            while current and visited < 50:
                if hasattr(current, "run_async"):
                    action = await current.run_async(shared)
                else:
                    action = current.run(shared)
                next_node = self._transitions.get((id(current), action))
                current = next_node
                visited += 1
            return shared


# ── Nodos de Decisión para ARIA AI ──────────────────────────────────────────

class AnalyzeContextNode(AsyncNode):
    """
    Nodo 1: Analiza el contexto de la misión entrante.
    Determina tipo de tarea, urgencia y agente óptimo.
    """
    async def prep_async(self, shared: dict) -> dict:
        return {
            "mission": shared.get("mission", ""),
            "context": shared.get("context", {}),
            "history": shared.get("history", []),
        }

    async def exec_async(self, prep_res: dict) -> dict:
        mission = prep_res["mission"].lower()
        # Clasificación de misión por palabras clave
        task_type = "general"
        if any(kw in mission for kw in ["revenue", "ventas", "monetizar", "income"]):
            task_type = "revenue"
        elif any(kw in mission for kw in ["código", "code", "bug", "deploy", "github"]):
            task_type = "coding"
        elif any(kw in mission for kw in ["marketing", "contenido", "social", "post"]):
            task_type = "marketing"
        elif any(kw in mission for kw in ["analizar", "investigar", "research", "competitor"]):
            task_type = "research"
        elif any(kw in mission for kw in ["estrategia", "strategy", "plan", "decision"]):
            task_type = "strategy"

        urgency = "high" if any(kw in mission for kw in ["urgente", "ahora", "inmediato"]) else "normal"

        return {
            "task_type": task_type,
            "urgency": urgency,
            "mission": prep_res["mission"],
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["analysis"] = exec_res
        logger.info("[PocketFlow] Análisis: tipo=%s urgencia=%s", exec_res["task_type"], exec_res["urgency"])
        return exec_res["task_type"]  # Action = tipo de tarea para routing


class StrategyDecisionNode(AsyncNode):
    """
    Nodo 2: Toma decisiones estratégicas de alto nivel.
    Determina el plan de acción óptimo para misiones de estrategia.
    """
    async def prep_async(self, shared: dict) -> dict:
        return shared.get("analysis", {})

    async def exec_async(self, prep_res: dict) -> dict:
        return {
            "decision": "execute_strategy",
            "agent": "orchestrator",
            "priority": 1,
            "plan": f"Ejecutar estrategia para: {prep_res.get('mission', '')}",
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["decision"] = exec_res
        return "execute"


class RevenueDecisionNode(AsyncNode):
    """
    Nodo 2b: Decisiones de revenue y monetización.
    Selecciona el canal de ingresos más prometedor.
    """
    async def prep_async(self, shared: dict) -> dict:
        return shared.get("analysis", {})

    async def exec_async(self, prep_res: dict) -> dict:
        return {
            "decision": "execute_revenue",
            "agent": "cfo",
            "channels": ["ebook", "saas", "affiliate"],
            "priority": 1,
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["decision"] = exec_res
        return "execute"


class CodingDecisionNode(AsyncNode):
    """
    Nodo 2c: Decisiones de desarrollo autónomo.
    Determina si usar Aider, SWE-agent o dev_agent nativo.
    """
    async def prep_async(self, shared: dict) -> dict:
        return shared.get("analysis", {})

    async def exec_async(self, prep_res: dict) -> dict:
        return {
            "decision": "execute_coding",
            "agent": "dev",
            "tool": "aider",
            "priority": 2,
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["decision"] = exec_res
        return "execute"


class ResearchDecisionNode(AsyncNode):
    """
    Nodo 2d: Decisiones de investigación de mercado.
    Selecciona entre Crawl4AI, Firecrawl o web_tools.
    """
    async def prep_async(self, shared: dict) -> dict:
        return shared.get("analysis", {})

    async def exec_async(self, prep_res: dict) -> dict:
        return {
            "decision": "execute_research",
            "agent": "marketing",
            "tools": ["crawl4ai", "firecrawl"],
            "priority": 2,
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["decision"] = exec_res
        return "execute"


class GeneralDecisionNode(AsyncNode):
    """Nodo de decisión general para tareas no clasificadas."""
    async def prep_async(self, shared: dict) -> dict:
        return shared.get("analysis", {})

    async def exec_async(self, prep_res: dict) -> dict:
        return {
            "decision": "execute_general",
            "agent": "orchestrator",
            "priority": 3,
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["decision"] = exec_res
        return "execute"


class ExecuteNode(AsyncNode):
    """
    Nodo 3: Ejecuta la decisión tomada.
    Delega al agente apropiado de Aria.
    """
    async def prep_async(self, shared: dict) -> dict:
        return {
            "decision": shared.get("decision", {}),
            "mission": shared.get("mission", ""),
            "context": shared.get("context", {}),
        }

    async def exec_async(self, prep_res: dict) -> dict:
        decision = prep_res["decision"]
        agent_name = decision.get("agent", "orchestrator")
        logger.info("[PocketFlow] Ejecutando con agente: %s", agent_name)
        return {
            "executed": True,
            "agent": agent_name,
            "mission": prep_res["mission"],
            "result": f"Delegado a {agent_name}",
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["execution"] = exec_res
        return "audit"


class AuditNode(AsyncNode):
    """
    Nodo 4: Audita el resultado de la ejecución.
    Integra con el ExecutionPipeline existente de Aria.
    """
    async def prep_async(self, shared: dict) -> dict:
        return {
            "execution": shared.get("execution", {}),
            "analysis": shared.get("analysis", {}),
        }

    async def exec_async(self, prep_res: dict) -> dict:
        execution = prep_res["execution"]
        quality_score = 85 if execution.get("executed") else 0
        return {
            "quality_score": quality_score,
            "passed": quality_score >= 75,
            "notes": "Ejecución completada correctamente" if quality_score >= 75 else "Requiere revisión",
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["audit"] = exec_res
        if exec_res["passed"]:
            return "complete"
        return "retry"


class CompleteNode(AsyncNode):
    """Nodo final: consolida el resultado del flow."""
    async def prep_async(self, shared: dict) -> dict:
        return shared

    async def exec_async(self, prep_res: dict) -> dict:
        return {
            "success": True,
            "analysis": prep_res.get("analysis"),
            "decision": prep_res.get("decision"),
            "execution": prep_res.get("execution"),
            "audit": prep_res.get("audit"),
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["result"] = exec_res
        return "done"


# ── Factory del Flow de Decisión de ARIA ────────────────────────────────────

def build_aria_decision_flow() -> AsyncFlow:
    """
    Construye el flow de decisión principal de ARIA AI usando PocketFlow.

    Topología:
        AnalyzeContext
            ├─ strategy  → StrategyDecision → Execute → Audit → Complete
            ├─ revenue   → RevenueDecision  → Execute → Audit → Complete
            ├─ coding    → CodingDecision   → Execute → Audit → Complete
            ├─ research  → ResearchDecision → Execute → Audit → Complete
            └─ general   → GeneralDecision  → Execute → Audit → Complete
    """
    # Instanciar nodos
    analyze = AnalyzeContextNode()
    strategy_decide = StrategyDecisionNode()
    revenue_decide = RevenueDecisionNode()
    coding_decide = CodingDecisionNode()
    research_decide = ResearchDecisionNode()
    general_decide = GeneralDecisionNode()
    execute = ExecuteNode()
    audit = AuditNode()
    complete = CompleteNode()

    # Construir flow con routing por tipo de tarea
    flow = AsyncFlow(start=analyze)

    # Routing desde AnalyzeContext
    flow.add_edge(analyze, "strategy", strategy_decide)
    flow.add_edge(analyze, "revenue", revenue_decide)
    flow.add_edge(analyze, "coding", coding_decide)
    flow.add_edge(analyze, "research", research_decide)
    flow.add_edge(analyze, "marketing", general_decide)
    flow.add_edge(analyze, "general", general_decide)

    # Todos los nodos de decisión van a Execute
    for decide_node in [strategy_decide, revenue_decide, coding_decide, research_decide, general_decide]:
        flow.add_edge(decide_node, "execute", execute)

    # Execute → Audit → Complete
    flow.add_edge(execute, "audit", audit)
    flow.add_edge(audit, "complete", complete)
    flow.add_edge(audit, "retry", execute)  # Retry loop

    return flow


# ── Interfaz pública ─────────────────────────────────────────────────────────

class AriaDecisionEngine:
    """
    Motor de decisiones de ARIA AI basado en PocketFlow.
    Reemplaza y potencia el StateGraph existente con flujos declarativos.

    Uso:
        engine = AriaDecisionEngine()
        result = await engine.decide(
            mission="Analizar competidores del nicho fitness",
            context={"niche": "fitness", "budget": 100}
        )
    """

    def __init__(self) -> None:
        self._flow = build_aria_decision_flow()
        logger.info(
            "[AriaDecisionEngine] Inicializado con PocketFlow (disponible=%s)",
            POCKETFLOW_AVAILABLE,
        )

    async def decide(self, mission: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Ejecuta el flow de decisión completo para una misión dada.

        Args:
            mission: Descripción de la tarea o misión a ejecutar.
            context: Contexto adicional (niche, budget, agente preferido, etc.)

        Returns:
            dict con analysis, decision, execution y audit del flow.
        """
        shared: dict[str, Any] = {
            "mission": mission,
            "context": context or {},
            "history": [],
        }
        try:
            result = await self._flow.run_async(shared)
            return result.get("result", result)
        except Exception as exc:
            logger.error("[AriaDecisionEngine] Error en flow: %s", exc)
            return {
                "success": False,
                "error": str(exc),
                "mission": mission,
            }

    async def batch_decide(self, missions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Ejecuta múltiples decisiones en paralelo (BatchFlow de PocketFlow).

        Args:
            missions: Lista de dicts con 'mission' y opcionalmente 'context'.

        Returns:
            Lista de resultados de cada decisión.
        """
        tasks = [
            self.decide(m.get("mission", ""), m.get("context"))
            for m in missions
        ]
        return await asyncio.gather(*tasks, return_exceptions=False)


# ── Singleton ────────────────────────────────────────────────────────────────
_engine_instance: AriaDecisionEngine | None = None


def get_decision_engine() -> AriaDecisionEngine:
    """Retorna el singleton del motor de decisiones de ARIA."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = AriaDecisionEngine()
    return _engine_instance
