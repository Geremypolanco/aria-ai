"""
apps/core/agents/__init__.py -- Registro de todos los agentes de ARIA AI v2.

Exporta todos los agentes nucleo y los nuevos agentes del Gobernador Economico.
"""
from apps.core.agents.base_agent import BaseAgent, AgentMetrics
from apps.core.agents.orchestrator import Orchestrator
from apps.core.agents.cfo_agent import CFOAgent
from apps.core.agents.content_agent import ContentAgent
from apps.core.agents.evolution_agent import EvolutionAgent
from apps.core.agents.compliance_agent import ComplianceAgent
from apps.core.agents.marketing_agent import MarketingAgent
from apps.core.agents.pm_agent import PMAgent
from apps.core.agents.support_agent import SupportAgent
from apps.core.agents.dev_agent import DevAgent

# Nuevos agentes del Gobernador Economico Multi-Sectorial (Fase 2)
from apps.core.agents.economic_governor_agent import EconomicGovernorAgent
from apps.core.agents.human_resources_agent import HumanResourcesAgent
from apps.core.agents.process_optimization_agent import ProcessOptimizationAgent

__all__ = [
    # Base
    "BaseAgent",
    "AgentMetrics",
    # Nucleo original
    "Orchestrator",
    "CFOAgent",
    "ContentAgent",
    "EvolutionAgent",
    "ComplianceAgent",
    "MarketingAgent",
    "PMAgent",
    "SupportAgent",
    "DevAgent",
    # Gobernador Economico Multi-Sectorial
    "EconomicGovernorAgent",
    "HumanResourcesAgent",
    "ProcessOptimizationAgent",
]
