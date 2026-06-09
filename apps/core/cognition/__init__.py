"""
cognition/ — Arquitectura cognitiva de ARIA AI.

AriaMind es el motor central. WorldState, ReflectionEngine y EpisodicMemory
son módulos de soporte que AriaMind consulta.
"""
from apps.core.cognition.aria_mind import get_aria_mind, AriaMind, MindResponse
from apps.core.cognition.world_state import get_world_state
from apps.core.cognition.reflection_engine import get_reflection_engine
from apps.core.cognition.episodic_memory import get_episodic_memory

__all__ = [
    "get_aria_mind", "AriaMind", "MindResponse",
    "get_world_state",
    "get_reflection_engine",
    "get_episodic_memory",
]
