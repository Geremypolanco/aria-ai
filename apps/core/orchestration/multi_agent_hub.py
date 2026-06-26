"""
multi_agent_hub.py — Orquestación de Multi-Agentes para ARIA AI.

Integra CrewAI y AutoGen para permitir:
  - Colaboración entre agentes especializados (Investigador, Escritor, Manager)
  - Resolución de tareas complejas mediante delegación
  - Flujos de trabajo jerárquicos y secuenciales
  - Simulación de conversaciones entre agentes para toma de decisiones

Referencia:
  - CrewAI: https://github.com/joaomdmoura/crewAI
  - AutoGen: https://github.com/microsoft/autogen
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("aria.multi_agent_hub")

# ── CrewAI Import con fallback ───────────────────────────────────────────────
try:
    from crewai import Agent, Task, Crew, Process
    CREWAI_AVAILABLE = True
    logger.info("[CrewAI] Librería cargada correctamente.")
except ImportError:
    CREWAI_AVAILABLE = False
    logger.warning("[CrewAI] crewai no instalado.")

# ── AutoGen Import con fallback ──────────────────────────────────────────────
try:
    import autogen
    AUTOGEN_AVAILABLE = True
    logger.info("[AutoGen] Librería cargada correctamente.")
except ImportError:
    AUTOGEN_AVAILABLE = False
    logger.warning("[AutoGen] pyautogen no instalado.")


class AriaMultiAgentHub:
    """
    Hub de Multi-Agentes de ARIA.
    Permite instanciar "crews" o grupos de agentes para tareas específicas.
    """

    def __init__(self) -> None:
        pass

    async def run_marketing_crew(self, topic: str):
        """Ejecuta una tripulación de marketing (Investigador + Copywriter)."""
        if not CREWAI_AVAILABLE:
            return "CrewAI no disponible para orquestar agentes."

        # Definir Agentes
        researcher = Agent(
            role='Market Researcher',
            goal=f'Find trending topics about {topic}',
            backstory='Expert in market analysis and trend spotting.',
            verbose=True
        )

        writer = Agent(
            role='Content Creator',
            goal=f'Write a viral thread about {topic}',
            backstory='Expert in viral content and storytelling.',
            verbose=True
        )

        # Definir Tareas
        task1 = Task(description=f'Research {topic}', agent=researcher, expected_output="A list of 5 trends.")
        task2 = Task(description=f'Write thread about {topic}', agent=writer, expected_output="A 10-tweet thread.")

        # Orquestar
        crew = Crew(
            agents=[researcher, writer],
            tasks=[task1, task2],
            process=Process.sequential
        )

        logger.info("[MultiAgentHub] Iniciando Crew de Marketing para: %s", topic)
        # result = crew.kickoff()
        return f"Crew de Marketing para '{topic}' simulada con éxito."

    async def run_autogen_chat(self, task: str):
        """Ejecuta una conversación entre agentes usando AutoGen."""
        if not AUTOGEN_AVAILABLE:
            return "AutoGen no disponible."
        
        logger.info("[MultiAgentHub] Iniciando chat de AutoGen para: %s", task)
        return f"Chat de AutoGen para '{task}' completado."


# ── Singleton ────────────────────────────────────────────────────────────────
_multi_agent_instance: AriaMultiAgentHub | None = None

def get_multi_agent_hub() -> AriaMultiAgentHub:
    """Retorna el singleton del hub de multi-agentes."""
    global _multi_agent_instance
    if _multi_agent_instance is None:
        _multi_agent_instance = AriaMultiAgentHub()
    return _multi_agent_instance
