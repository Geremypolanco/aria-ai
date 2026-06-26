"""
training/ — Módulo de auto-mejora continua de ARIA AI.
El SelfTrainer corre en background y evalúa/mejora las capacidades de ARIA.
"""

from apps.core.training.continuous_trainer import get_trainer

__all__ = ["get_trainer"]
