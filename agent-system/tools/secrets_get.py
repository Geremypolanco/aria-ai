"""
ARIA Agent System — Tool: secrets_get.
Obtiene secretos de Hashicorp Vault de forma segura.

Sintaxis:
    tool: secrets_get
    params:
        path: string - Ruta del secreto (ej: "agents/shopify")
        key: string (opcional) - Clave específica

Retorna:
    {
        "path": string,
        "exists": bool,
        "keys": list[string] | None,
        "value": string | None,
        "truncated": bool
    }

Seguridad:
    - No loggea valores de secretos
    - Auditoría completa en Vault
"""
from __future__ import annotations

import logging
from typing import Any

from core.vault.client import VaultClient

logger = logging.getLogger("aria.tools.secrets_get")


async def execute(
    vault: VaultClient,
    params: dict[str, Any],
    task_id: str | None = None,
) -> dict[str, Any]:
    """
    Obtiene un secreto de Vault.
    """
    path = params.get("path", "")
    key = params.get("key")

    if not path:
        return {
            "success": False,
            "error": "Ruta de secreto requerida",
            "path": "",
            "exists": False,
        }

    try:
        secret = await vault.get_secret(path, key)

        if secret is None:
            logger.info("secrets_get: secreto no encontrado en %s", path)
            return {
                "success": True,
                "path": path,
                "exists": False,
                "keys": None,
                "value": None,
            }

        # Si se pidió una clave específica
        if key:
            return {
                "success": True,
                "path": f"{path}/{key}",
                "exists": True,
                "value": str(secret)[:500],  # Truncado por seguridad
                "truncated": len(str(secret)) > 500,
            }

        # Si se pidió todo el secreto, listar las claves
        if isinstance(secret, dict):
            keys = list(secret.keys())
            return {
                "success": True,
                "path": path,
                "exists": True,
                "keys": keys,
                "value": None,
                "note": f"Secreto tiene {len(keys)} claves. Usa 'key' para obtener un valor específico.",
            }

        return {
            "success": True,
            "path": path,
            "exists": True,
            "value": str(secret)[:500],
            "truncated": len(str(secret)) > 500,
        }

    except Exception as e:
        logger.error("secrets_get error: %s", e)
        return {
            "success": False,
            "error": str(e)[:300],
            "path": path,
            "exists": False,
        }
