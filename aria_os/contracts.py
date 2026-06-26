"""
contracts.py — Definición de Interfaces y Contratos de Aria OS.

Establece los esquemas de datos estrictos para la comunicación entre los 12 módulos.
Garantiza que el sistema sea modular, testeable y escalable.
"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class MarketSignal(BaseModel):
    """Señal detectada por la Perception Layer."""
    source: str
    content: str
    confidence: float = Field(ge=0, le=1)
    timestamp: datetime = Field(default_factory=datetime.now)

class StrategicIntention(BaseModel):
    """Intención generada por el Core OS."""
    strategy_type: str
    target_focus: str
    priority: int
    reasoning: str

class EconomicImpact(BaseModel):
    """Impacto económico registrado por el Economic Engine."""
    revenue: float
    cost: float
    currency: str = "USD"
    attributed_to: str  # ID del agente o campaña

class SwarmMission(BaseModel):
    """Misión para el Agent Swarm Layer."""
    mission_id: str
    goal: str
    agents: List[str]
    budget_limit: float
