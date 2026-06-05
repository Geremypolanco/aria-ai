"""
airtable_tools.py — Base de datos flexible via Airtable API.
Gestiona registros de productos, leads, campañas y métricas.
"""
from __future__ import annotations
import logging
from typing import Any, Optional
import httpx
from apps.core.config import settings

logger = logging.getLogger("aria.airtable_tools")
AIRTABLE_API = "https://api.airtable.com/v0"


class AirtableTools:
    """Gestión de datos via Airtable REST API."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=20.0)
        self._token = settings.AIRTABLE_TOKEN
        self._headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def _configured(self) -> bool:
        return bool(self._token)

    async def list_bases(self) -> dict[str, Any]:
        """Lista todas las bases de Airtable disponibles."""
        if not self._configured():
            return {"success": False, "error": "AIRTABLE_TOKEN no configurado"}
        try:
            res = await self._http.get("https://api.airtable.com/v0/meta/bases", headers=self._headers)
            if res.status_code == 200:
                bases = res.json().get("bases", [])
                return {"success": True, "bases": [{"id": b["id"], "name": b["name"]} for b in bases]}
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def create_record(self, base_id: str, table: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Crea un registro en una tabla de Airtable."""
        if not self._configured():
            return {"success": False, "error": "AIRTABLE_TOKEN no configurado"}
        try:
            res = await self._http.post(
                f"{AIRTABLE_API}/{base_id}/{table}",
                headers={**self._headers, "Content-Type": "application/json"},
                json={"fields": fields},
            )
            if res.status_code in (200, 201):
                record = res.json()
                return {"success": True, "record_id": record["id"], "fields": record["fields"]}
            return {"success": False, "error": f"HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            logger.error("[AirtableTools] create_record error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def list_records(self, base_id: str, table: str, max_records: int = 20, filter_formula: str = "") -> dict[str, Any]:
        """Lista registros de una tabla."""
        if not self._configured():
            return {"success": False, "error": "AIRTABLE_TOKEN no configurado"}
        try:
            params: dict[str, Any] = {"maxRecords": max_records}
            if filter_formula:
                params["filterByFormula"] = filter_formula
            res = await self._http.get(
                f"{AIRTABLE_API}/{base_id}/{table}",
                headers=self._headers, params=params,
            )
            if res.status_code == 200:
                records = res.json().get("records", [])
                return {"success": True, "records": records, "count": len(records)}
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def update_record(self, base_id: str, table: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Actualiza un registro existente."""
        if not self._configured():
            return {"success": False, "error": "AIRTABLE_TOKEN no configurado"}
        try:
            res = await self._http.patch(
                f"{AIRTABLE_API}/{base_id}/{table}/{record_id}",
                headers={**self._headers, "Content-Type": "application/json"},
                json={"fields": fields},
            )
            if res.status_code == 200:
                return {"success": True, "record_id": record_id}
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
