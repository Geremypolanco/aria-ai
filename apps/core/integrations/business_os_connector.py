"""
business_os_connector.py — Business Systems Connector for ARIA AI.

Intended to let ARIA operate real management software:
  - ERPNext / Odoo: Inventory, invoicing, and finance management.
  - Twenty CRM / Salesforce: Customer relationship management.
  - Plane: Project and task management.

STATUS: disabled by default (see settings.ERP_ENABLED). The ERP/CRM
integration is NOT implemented — every mutating call raises
NotImplementedError with a clear message instead of pretending to
succeed. Wire a real backend and flip ERP_ENABLED=True to use it.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("aria.business_os")

_NOT_CONFIGURED = (
    "ERPNext/Odoo integration not configured: ERP_ENABLED is False. "
    "Set ERP_ENABLED=True plus ERP_URL/ERP_API_KEY in the environment "
    "once a real ERP backend is implemented."
)


class AriaBusinessOSConnector:
    """
    Business Operating Systems Connector.
    Abstracts ERP and CRM APIs for ARIA.

    When disabled (the default), mutating operations raise
    NotImplementedError immediately so callers can never mistake this
    for a working integration.
    """

    def __init__(self, erp_url: str = "", api_key: str = "", enabled: bool = False) -> None:
        self.erp_url = erp_url
        self.api_key = api_key
        self.enabled = enabled
        self.client = httpx.AsyncClient(headers={"Authorization": f"token {api_key}"}, timeout=30.0)

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise NotImplementedError(_NOT_CONFIGURED)

    async def create_invoice(self, customer_id: str, items: list[dict[str, Any]]):
        """Creates an invoice in the ERP (ERPNext/Odoo).

        Raises NotImplementedError while the real integration is not
        implemented — reporting success here would fabricate an invoice
        that doesn't exist in any system.
        """
        self._require_enabled()
        raise NotImplementedError(
            "create_invoice: real integration with ERPNext/Odoo not yet implemented"
        )

    async def update_crm_lead(self, lead_id: str, status: str):
        """Updates a lead's status in the CRM.

        Raises NotImplementedError while the real integration is not
        implemented — see create_invoice.
        """
        self._require_enabled()
        raise NotImplementedError(
            "update_crm_lead: real integration with the CRM not yet implemented"
        )


# ── Singleton ────────────────────────────────────────────────────────────────
_business_os_instance: AriaBusinessOSConnector | None = None


def get_business_os_connector() -> AriaBusinessOSConnector:
    """Returns the singleton of the Business OS connector.

    The connector is disabled unless ERP_ENABLED=True is set in the
    environment — mutating calls raise NotImplementedError otherwise.
    """
    global _business_os_instance
    if _business_os_instance is None:
        enabled = os.getenv("ERP_ENABLED", "false").strip().lower() in ("1", "true", "yes")
        _business_os_instance = AriaBusinessOSConnector(
            erp_url=os.getenv("ERP_URL", ""),
            api_key=os.getenv("ERP_API_KEY", ""),
            enabled=enabled,
        )
    return _business_os_instance
