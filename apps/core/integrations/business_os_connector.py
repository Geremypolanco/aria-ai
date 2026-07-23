"""
business_os_connector.py — Conector de Sistemas Empresariales para ARIA AI.

Permite que ARIA opere software de gestión real:
  - ERPNext / Odoo: Gestión de inventario, facturación y finanzas.
  - Twenty CRM / Salesforce: Gestión de relaciones con clientes.
  - Plane: Gestión de proyectos y tareas.

ARIA deja de recomendar y empieza a operar el negocio.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("aria.business_os")


class AriaBusinessOSConnector:
    """
    Conector de Sistemas Operativos de Negocio.
    Abstrae las APIs de ERPs y CRMs para ARIA.
    """

    def __init__(self, erp_url: str = "", api_key: str = "") -> None:
        self.erp_url = erp_url
        self.api_key = api_key
        self.client = httpx.AsyncClient(headers={"Authorization": f"token {api_key}"})

    async def create_invoice(self, customer_id: str, items: list[dict[str, Any]]):
        """Crea una factura en el ERP (ERPNext/Odoo). No implementado — el ERP
        real nunca se llama, así que reportar éxito sería fabricar una
        factura que no existe en ningún sistema."""
        raise NotImplementedError(
            "create_invoice: integración real con ERPNext/Odoo aún no implementada"
        )

    async def update_crm_lead(self, lead_id: str, status: str):
        """Actualiza el estado de un lead en el CRM. No implementado — ver
        create_invoice."""
        raise NotImplementedError(
            "update_crm_lead: integración real con el CRM aún no implementada"
        )


# ── Singleton ────────────────────────────────────────────────────────────────
_business_os_instance: AriaBusinessOSConnector | None = None


def get_business_os_connector() -> AriaBusinessOSConnector:
    """Retorna el singleton del conector de Business OS."""
    global _business_os_instance
    if _business_os_instance is None:
        import os

        _business_os_instance = AriaBusinessOSConnector(
            erp_url=os.getenv("ERP_URL", ""), api_key=os.getenv("ERP_API_KEY", "")
        )
    return _business_os_instance
