"""
business_os_connector.py — Business Systems Connector for ARIA AI.

Allows ARIA to operate real management software:
  - ERPNext / Odoo: Inventory, invoicing, and finance management.
  - Twenty CRM / Salesforce: Customer relationship management.
  - Plane: Project and task management.

ARIA stops recommending and starts operating the business.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("aria.business_os")


class AriaBusinessOSConnector:
    """
    Business Operating Systems Connector.
    Abstracts ERP and CRM APIs for ARIA.
    """

    def __init__(self, erp_url: str = "", api_key: str = "") -> None:
        self.erp_url = erp_url
        self.api_key = api_key
        self.client = httpx.AsyncClient(headers={"Authorization": f"token {api_key}"})

    async def create_invoice(self, customer_id: str, items: list[dict[str, Any]]):
        """Creates an invoice in the ERP (ERPNext/Odoo). Not implemented — the real
        ERP is never called, so reporting success would fabricate an
        invoice that doesn't exist in any system."""
        raise NotImplementedError(
            "create_invoice: real integration with ERPNext/Odoo not yet implemented"
        )

    async def update_crm_lead(self, lead_id: str, status: str):
        """Updates a lead's status in the CRM. Not implemented — see
        create_invoice."""
        raise NotImplementedError(
            "update_crm_lead: real integration with the CRM not yet implemented"
        )


# ── Singleton ────────────────────────────────────────────────────────────────
_business_os_instance: AriaBusinessOSConnector | None = None


def get_business_os_connector() -> AriaBusinessOSConnector:
    """Returns the singleton of the Business OS connector."""
    global _business_os_instance
    if _business_os_instance is None:
        import os

        _business_os_instance = AriaBusinessOSConnector(
            erp_url=os.getenv("ERP_URL", ""), api_key=os.getenv("ERP_API_KEY", "")
        )
    return _business_os_instance
