"""Compatibility shim for legacy configuration imports.

Some modules import `settings` from `apps.core.config_pkg`, while the
actual configuration lives in `apps.core.config`. We re-export it here to
avoid startup failures and maintain backward compatibility.
"""

from apps.core.config import Settings, settings

__all__ = ["Settings", "settings"]
