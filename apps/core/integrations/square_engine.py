"""
square_engine.py — Motor de ejecución para Square API (Pagos y Catálogo)
Permite a Aria vender productos físicos y digitales usando Square.
"""
import logging
import httpx
from typing import Dict, Any, Optional, List
from apps.core.config import settings

logger = logging.getLogger("aria.square_engine")

class SquareEngine:
    def __init__(self, access_token: Optional[str] = None, environment: str = "sandbox"):
        self.access_token = access_token or getattr(settings, "SQUARE_ACCESS_TOKEN", None)
        self.environment = environment
        self.base_url = "https://connect.squareupsandbox.com/v2" if environment == "sandbox" else "https://connect.squareup.com/v2"
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Square-Version": "2024-01-17"
        }

    async def create_catalog_item(self, name: str, description: str, price_money: int, currency: str = "USD") -> Dict[str, Any]:
        """Crea un item en el catálogo de Square."""
        if not self.access_token:
            return {"success": False, "error": "SQUARE_ACCESS_TOKEN no configurado"}
        
        url = f"{self.base_url}/catalog/object"
        import uuid
        idempotency_key = str(uuid.uuid4())
        
        payload = {
            "idempotency_key": idempotency_key,
            "object": {
                "type": "ITEM",
                "id": f"#{name.lower().replace(' ', '_')}",
                "item_data": {
                    "name": name,
                    "description": description,
                    "variations": [
                        {
                            "type": "ITEM_VARIATION",
                            "id": f"#var_{name.lower().replace(' ', '_')}",
                            "item_variation_data": {
                                "name": "Regular",
                                "pricing_type": "FIXED_PRICING",
                                "price_money": {
                                    "amount": price_money,
                                    "currency": currency
                                }
                            }
                        }
                    ]
                }
            }
        }
        
        async with httpx.AsyncClient() as client:
            res = await client.post(url, headers=self.headers, json=payload)
            if res.status_code in (200, 201):
                return {"success": True, "data": res.json()}
            return {"success": False, "error": res.text}

    async def create_payment_link(self, item_id: str, name: str, price_money: int, currency: str = "USD") -> Dict[str, Any]:
        """Crea un enlace de pago para un item."""
        url = f"{self.base_url}/online-checkout/payment-links"
        import uuid
        payload = {
            "idempotency_key": str(uuid.uuid4()),
            "order": {
                "location_id": getattr(settings, "SQUARE_LOCATION_ID", ""),
                "line_items": [
                    {
                        "name": name,
                        "quantity": "1",
                        "base_price_money": {
                            "amount": price_money,
                            "currency": currency
                        }
                    }
                ]
            }
        }
        
        async with httpx.AsyncClient() as client:
            res = await client.post(url, headers=self.headers, json=payload)
            if res.status_code in (200, 201):
                return {"success": True, "payment_link": res.json().get("payment_link", {}).get("url")}
            return {"success": False, "error": res.text}
