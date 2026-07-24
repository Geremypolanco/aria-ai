"""
training/ — Continuous self-improvement module for ARIA AI.
The SelfTrainer runs in the background and evaluates/improves ARIA's capabilities.
"""

from apps.core.training.continuous_trainer import get_trainer

__all__ = ["get_trainer"]
