"""ARIA capability & connector registry — self-knowledge of what ARIA can do."""

from apps.core.capabilities.registry import (
    Capability,
    CapabilityRegistry,
    CapabilityStatus,
    Quality,
    get_capability_registry,
)

__all__ = [
    "Capability",
    "CapabilityRegistry",
    "CapabilityStatus",
    "Quality",
    "get_capability_registry",
]
