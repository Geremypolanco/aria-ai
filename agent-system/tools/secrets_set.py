"""
ARIA Agent System — Tool: secrets_set.
Guarda secretos en Hashicorp Vault.

Sintaxis:
    tool: secrets_set
    params:
        path: string - Ruta del secreto
        data: dict - Datos a guardar
        cas: int (opcional) - Check-And-Set (versión esperada)

Retorna:
    {
        "path": string,
        "success": bool,
        "action": "created" | "updated"
    }

Seguridad:
    - Auditoría completa
    - No expone valores en logs
"""
from __future__ import annotations

import logging
from typing import Any

from core.vault.client import VaultClient

logger = logging.getLogger("aria.tools.secrets_set")


async def execute(
    vault: VaultClient,
    params: dict[str, Any],
    task_id: str | None = None,
) -> dict[str, Any]:
    """
    Guarda un secreto en Vault.
    """
    path = params.get("path", "")
    data = params.get("data", {})
    cas = params.get("cas")

    if not path:
        return {
            "success": False,
            "error": "Ruta de secreto requerida",
            "path": "",
        }

    if not data:
        return {
            "success": False,
            "error": "Datos requeridos para guardar el secreto",
            "path": path,
        }

    try:
        # Verificar si ya existe (para determinar created vs updated)
        existing = await vault.get_secret(path)
        action = "updated" if existing else "created"

        await vault.set_secret(path, data, cas=cas)

        logger.info(
            "secrets_set: %s secreto en %s (%d campos)",
            action,
            path,
            len(data),
        )

        return {
            "success": True,
            "path": path,
            "action": action,
            "field_count": len(data),
            "fields": list(data.keys()),
        }

    except Exception as e:
        logger.error("secrets_set error: %s", e)
        return {
            "success": False,
            "error": str(e)[:300],
            "path": path,
        }
