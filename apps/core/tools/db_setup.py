"""
db_setup.py — Verifica y crea las tablas de Supabase que ARIA necesita.
Se ejecuta automáticamente al inicio de la aplicación.
"""

from __future__ import annotations

import logging

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.db_setup")


async def setup_database() -> dict:
    """Verifica que las tablas existan en Supabase."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        logger.warning("[DB Setup] Sin credenciales Supabase — saltando")
        return {"status": "skipped", "reason": "no credentials"}

    tables = [
        "autonomous_cycles",
        "content_published",
        "products",
        "market_opportunities",
        "system_logs",
        "revenue_events",
        "self_improvements",
    ]
    results = {}
    headers = {
        "apikey": settings.SUPABASE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        for table in tables:
            try:
                resp = await client.get(
                    f"{settings.SUPABASE_URL}/rest/v1/{table}?limit=1",
                    headers=headers,
                )
                if resp.status_code == 200:
                    results[table] = "ok"
                elif resp.status_code in (404, 406) or "does not exist" in resp.text:
                    results[table] = "missing"
                    logger.warning("[DB Setup] Tabla '%s' no existe", table)
                else:
                    results[table] = f"status_{resp.status_code}"
            except Exception as exc:
                results[table] = f"error: {str(exc)[:40]}"

    missing = [t for t, v in results.items() if v != "ok"]
    if not missing:
        logger.info("[DB Setup] Todas las tablas existen en Supabase")
    else:
        logger.warning("[DB Setup] Tablas faltantes: %s", ", ".join(missing))

    return {"status": "ok" if not missing else "partial", "tables": results}


async def log_to_supabase(table: str, data: dict) -> bool:
    """Inserta un registro en Supabase. Falla silenciosamente."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        return False
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"{settings.SUPABASE_URL}/rest/v1/{table}",
                json=data,
                headers={
                    "apikey": settings.SUPABASE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
            )
            return resp.status_code in (200, 201)
    except Exception as exc:
        logger.debug("[DB] Error en %s: %s", table, exc)
        return False


async def update_cycle_status(cycle_id: str, data: dict) -> bool:
    """Actualiza el estado de un ciclo autónomo."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        return False
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.patch(
                f"{settings.SUPABASE_URL}/rest/v1/autonomous_cycles?id=eq.{cycle_id}",
                json=data,
                headers={
                    "apikey": settings.SUPABASE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
            )
            return resp.status_code in (200, 204)
    except Exception:
        return False
