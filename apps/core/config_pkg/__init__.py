"""Compatibilidad para importaciones históricas de configuración.

Algunos módulos importan `settings` desde `apps.core.config_pkg`, mientras que
la configuración real vive en `apps.core.config`. Reexportamos aquí para evitar
fallos de arranque y mantener compatibilidad hacia atrás.
"""

from apps.core.config import Settings, settings

__all__ = ["Settings", "settings"]
