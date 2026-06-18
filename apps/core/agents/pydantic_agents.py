"""
pydantic_agents.py — Agentes Robustos con PydanticAI para ARIA AI.

PydanticAI proporciona:
  - Tipado fuerte con Pydantic v2 para inputs/outputs de agentes
  - Validación automática de respuestas del LLM
  - Tool calling tipado y auditable
  - Workflows con historial completo de mensajes
  - Soporte multi-modelo (OpenAI, Anthropic, Groq, Gemini)

Integración con Aria:
  - Envuelve los agentes críticos (orchestrator, cfo, marketing) con PydanticAI
  - Valida los outputs del LLM antes de ejecutar acciones reales
  - Proporciona un sistema de tools tipado para el ExecutionPipeline
  - Audita cada llamada LLM con metadata completa

Referencia: https://ai.pydantic.dev/
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Union
from datetime import datetime

from pydantic import BaseModel, Field

logger = logging.getLogger("aria.pydantic_agents")

# ── PydanticAI Import con fallback ───────────────────────────────────────────
try:
    from pydantic_ai import Agent as PydanticAgent
    from pydantic_ai.models.openai import OpenAIModel
    from pydantic_ai import RunContext
    PYDANTIC_AI_AVAILABLE = True
    logger.info("[PydanticAI] Librería cargada correctamente.")
except ImportError:
    PYDANTIC_AI_AVAILABLE = False
    logger.warning(
        "[PydanticAI] pydantic-ai no instalado. "
        "Usando implementación tipada nativa. "
        "Instala con: pip install pydantic-ai"
    )
    PydanticAgent = None  # type: ignore[assignment,misc]
    OpenAIModel = None  # type: ignore[assignment,misc]
    RunContext = None  # type: ignore[assignment,misc]


# ── Modelos de Datos Tipados (Pydantic v2) ───────────────────────────────────

class AgentTask(BaseModel):
    """Input tipado para cualquier agente de ARIA."""
    mission: str = Field(..., description="Descripción clara de la tarea a ejecutar")
    agent_name: str = Field(default="orchestrator", description="Nombre del agente objetivo")
    context: dict[str, Any] = Field(default_factory=dict, description="Contexto adicional")
    priority: int = Field(default=2, ge=1, le=5, description="Prioridad (1=alta, 5=baja)")
    max_iterations: int = Field(default=3, ge=1, le=10, description="Máximo de iteraciones")
    notify_telegram: bool = Field(default=True, description="Notificar resultado por Telegram")


class AgentDecision(BaseModel):
    """Output tipado de una decisión de agente."""
    action: str = Field(..., description="Acción a ejecutar")
    agent: str = Field(..., description="Agente que ejecutará la acción")
    reasoning: str = Field(..., description="Razonamiento detrás de la decisión")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confianza en la decisión (0-1)")
    tools_required: list[str] = Field(default_factory=list, description="Herramientas necesarias")
    estimated_roi: float = Field(default=0.0, description="ROI estimado en USD")


class MarketAnalysis(BaseModel):
    """Output tipado de análisis de mercado."""
    niche: str = Field(..., description="Nicho analizado")
    opportunities: list[str] = Field(..., description="Oportunidades identificadas")
    competitors: list[str] = Field(default_factory=list, description="Competidores detectados")
    recommended_strategy: str = Field(..., description="Estrategia recomendada")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Confianza del análisis")
    estimated_market_size: Optional[str] = Field(None, description="Tamaño estimado del mercado")


class RevenueStrategy(BaseModel):
    """Output tipado de estrategia de ingresos."""
    primary_channel: str = Field(..., description="Canal principal de monetización")
    secondary_channels: list[str] = Field(default_factory=list, description="Canales secundarios")
    action_plan: list[str] = Field(..., description="Plan de acción paso a paso")
    timeline_days: int = Field(..., ge=1, description="Timeline en días")
    projected_revenue_usd: float = Field(..., ge=0.0, description="Ingresos proyectados en USD")
    risk_level: str = Field(..., description="Nivel de riesgo: low/medium/high")


class CodeTask(BaseModel):
    """Output tipado para tareas de desarrollo."""
    task_type: str = Field(..., description="Tipo: fix_bug/add_feature/refactor/create_pr")
    files_to_modify: list[str] = Field(default_factory=list, description="Archivos a modificar")
    description: str = Field(..., description="Descripción detallada de los cambios")
    test_required: bool = Field(default=True, description="¿Requiere tests?")
    pr_title: Optional[str] = Field(None, description="Título del PR si aplica")


class AgentAuditLog(BaseModel):
    """Log de auditoría tipado para cada ejecución de agente."""
    agent_name: str
    task: AgentTask
    decision: Optional[AgentDecision] = None
    output: Optional[dict[str, Any]] = None
    success: bool = False
    error: Optional[str] = None
    duration_ms: int = 0
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    llm_calls: int = 0
    tokens_used: int = 0


# ── Aria Typed Agent (wrapper sobre PydanticAI o nativo) ────────────────────

class AriaTypedAgent:
    """
    Agente tipado de ARIA AI con PydanticAI.

    Proporciona validación fuerte de inputs/outputs y auditoría completa.
    Si PydanticAI no está disponible, usa validación Pydantic nativa.

    Uso:
        agent = AriaTypedAgent(
            name="strategy",
            system_prompt="Eres el Strategy Engine de ARIA AI...",
            output_type=AgentDecision,
        )
        result = await agent.run(task)
    """

    def __init__(
        self,
        name: str,
        system_prompt: str,
        output_type: type[BaseModel] = AgentDecision,
        model: str = "gpt-4o-mini",
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.output_type = output_type
        self.model = model
        self._audit_log: list[AgentAuditLog] = []
        self._pydantic_agent: Any = None

        if PYDANTIC_AI_AVAILABLE and PydanticAgent is not None:
            try:
                self._pydantic_agent = PydanticAgent(
                    model=f"openai:{model}",
                    system_prompt=system_prompt,
                    result_type=output_type,
                )
                logger.info("[AriaTypedAgent] %s inicializado con PydanticAI", name)
            except Exception as exc:
                logger.warning("[AriaTypedAgent] Error inicializando PydanticAI para %s: %s", name, exc)
        else:
            logger.info("[AriaTypedAgent] %s usando validación Pydantic nativa", name)

    async def run(self, task: AgentTask) -> tuple[BaseModel | None, AgentAuditLog]:
        """
        Ejecuta el agente con validación tipada.

        Returns:
            Tuple de (output_tipado, audit_log)
        """
        import time
        start_ms = int(time.monotonic() * 1000)

        audit = AgentAuditLog(
            agent_name=self.name,
            task=task,
        )

        try:
            if self._pydantic_agent is not None:
                # Usar PydanticAI nativo
                result = await self._pydantic_agent.run(task.mission)
                output = result.data
                audit.llm_calls = 1
            else:
                # Fallback: usar ai_client de Aria con validación Pydantic
                output = await self._run_with_aria_client(task)

            audit.output = output.model_dump() if hasattr(output, "model_dump") else output
            audit.decision = output if isinstance(output, AgentDecision) else None
            audit.success = True

        except Exception as exc:
            logger.error("[AriaTypedAgent] %s error: %s", self.name, exc)
            audit.error = str(exc)
            audit.success = False
            output = None

        audit.duration_ms = int(time.monotonic() * 1000) - start_ms
        self._audit_log.append(audit)
        return output, audit

    async def _run_with_aria_client(self, task: AgentTask) -> BaseModel:
        """Fallback: usa el ai_client nativo de Aria con validación Pydantic."""
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            ai = get_ai_client()
            schema = self.output_type.model_json_schema()
            response = await ai.think(
                system=self.system_prompt,
                user=f"Tarea: {task.mission}\nContexto: {task.context}\n\nResponde con JSON válido según: {schema}",
                model=AIModel.STRATEGY,
                json_mode=True,
            )
            if response:
                return self.output_type.model_validate(response)
        except Exception as exc:
            logger.warning("[AriaTypedAgent] Fallback ai_client error: %s", exc)

        # Retornar output mínimo válido
        return self.output_type.model_validate(
            self._get_default_output(task)
        )

    def _get_default_output(self, task: AgentTask) -> dict[str, Any]:
        """Genera output por defecto según el tipo de salida."""
        if self.output_type == AgentDecision:
            return {
                "action": "analyze",
                "agent": self.name,
                "reasoning": f"Procesando: {task.mission}",
                "confidence": 0.5,
                "tools_required": [],
                "estimated_roi": 0.0,
            }
        elif self.output_type == MarketAnalysis:
            return {
                "niche": task.context.get("niche", "general"),
                "opportunities": ["Analizar mercado", "Identificar competidores"],
                "recommended_strategy": "Investigación inicial",
                "confidence_score": 0.5,
            }
        elif self.output_type == RevenueStrategy:
            return {
                "primary_channel": "digital_products",
                "action_plan": ["Analizar nicho", "Crear producto", "Publicar"],
                "timeline_days": 7,
                "projected_revenue_usd": 0.0,
                "risk_level": "medium",
            }
        return {}

    def get_audit_log(self) -> list[dict[str, Any]]:
        """Retorna el log de auditoría completo."""
        return [log.model_dump() for log in self._audit_log]

    def get_stats(self) -> dict[str, Any]:
        """Estadísticas de ejecución del agente."""
        if not self._audit_log:
            return {"total_runs": 0, "success_rate": 0.0, "avg_duration_ms": 0}
        total = len(self._audit_log)
        successful = sum(1 for log in self._audit_log if log.success)
        avg_duration = sum(log.duration_ms for log in self._audit_log) / total
        return {
            "total_runs": total,
            "success_rate": successful / total,
            "avg_duration_ms": int(avg_duration),
            "total_llm_calls": sum(log.llm_calls for log in self._audit_log),
        }


# ── Agentes Tipados Especializados de ARIA ───────────────────────────────────

class AriaStrategyAgent(AriaTypedAgent):
    """
    Strategy Engine tipado de ARIA AI.
    Toma decisiones de alto nivel con razonamiento auditable.
    """
    def __init__(self) -> None:
        super().__init__(
            name="strategy",
            system_prompt=(
                "Eres el Strategy Engine de ARIA AI, un sistema autónomo de ingresos digitales. "
                "Tu rol es tomar decisiones estratégicas de alto nivel con razonamiento claro y auditable. "
                "Analiza la situación, evalúa opciones y recomienda la acción óptima con confianza calibrada. "
                "Siempre considera el ROI, el riesgo y el tiempo de implementación."
            ),
            output_type=AgentDecision,
        )


class AriaMarketAnalystAgent(AriaTypedAgent):
    """
    Market Intelligence Agent tipado de ARIA AI.
    Analiza mercados y oportunidades con output validado.
    """
    def __init__(self) -> None:
        super().__init__(
            name="market_analyst",
            system_prompt=(
                "Eres el Market Intelligence Agent de ARIA AI. "
                "Analizas mercados, identificas oportunidades y evalúas competidores. "
                "Usa datos reales cuando estén disponibles. "
                "Proporciona análisis concretos con niveles de confianza calibrados."
            ),
            output_type=MarketAnalysis,
        )


class AriaRevenueAgent(AriaTypedAgent):
    """
    Revenue Strategy Agent tipado de ARIA AI.
    Diseña estrategias de monetización con proyecciones validadas.
    """
    def __init__(self) -> None:
        super().__init__(
            name="revenue_strategy",
            system_prompt=(
                "Eres el Revenue Strategy Agent de ARIA AI. "
                "Diseñas estrategias de monetización digital con proyecciones realistas. "
                "Considera: productos digitales, SaaS, afiliados, servicios. "
                "Sé conservador en proyecciones de ingresos. Prioriza canales probados."
            ),
            output_type=RevenueStrategy,
        )


class AriaCodeAgent(AriaTypedAgent):
    """
    Autonomous Code Agent tipado de ARIA AI.
    Planifica tareas de desarrollo con output estructurado.
    """
    def __init__(self) -> None:
        super().__init__(
            name="code_planner",
            system_prompt=(
                "Eres el Autonomous Code Agent de ARIA AI. "
                "Planificas y ejecutas tareas de desarrollo de software. "
                "Integras con Aider y SWE-agent para modificaciones reales de código. "
                "Siempre crea PRs con descripción clara y tests cuando sea posible."
            ),
            output_type=CodeTask,
        )


# ── Registry de Agentes Tipados ──────────────────────────────────────────────

class AriaAgentRegistry:
    """
    Registro centralizado de agentes tipados de ARIA AI.
    Integra con el ToolRegistry existente de Aria.
    """

    def __init__(self) -> None:
        self._agents: dict[str, AriaTypedAgent] = {}
        self._register_default_agents()

    def _register_default_agents(self) -> None:
        """Registra los agentes tipados por defecto."""
        self.register(AriaStrategyAgent())
        self.register(AriaMarketAnalystAgent())
        self.register(AriaRevenueAgent())
        self.register(AriaCodeAgent())
        logger.info("[AriaAgentRegistry] %d agentes tipados registrados", len(self._agents))

    def register(self, agent: AriaTypedAgent) -> None:
        """Registra un agente tipado."""
        self._agents[agent.name] = agent

    def get(self, name: str) -> AriaTypedAgent | None:
        """Obtiene un agente por nombre."""
        return self._agents.get(name)

    def list_agents(self) -> list[dict[str, str]]:
        """Lista todos los agentes registrados."""
        return [
            {
                "name": a.name,
                "output_type": a.output_type.__name__,
                "pydantic_ai": str(a._pydantic_agent is not None),
            }
            for a in self._agents.values()
        ]

    async def run_agent(self, name: str, task: AgentTask) -> tuple[BaseModel | None, AgentAuditLog]:
        """Ejecuta un agente por nombre."""
        agent = self.get(name)
        if not agent:
            raise ValueError(f"Agente '{name}' no encontrado. Disponibles: {list(self._agents.keys())}")
        return await agent.run(task)

    def get_all_stats(self) -> dict[str, Any]:
        """Estadísticas de todos los agentes."""
        return {name: agent.get_stats() for name, agent in self._agents.items()}


# ── Singleton ────────────────────────────────────────────────────────────────
_registry_instance: AriaAgentRegistry | None = None


def get_agent_registry() -> AriaAgentRegistry:
    """Retorna el singleton del registry de agentes tipados."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = AriaAgentRegistry()
    return _registry_instance
