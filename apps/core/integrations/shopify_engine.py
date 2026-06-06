import requests
import logging
from typing import List, Dict, Any

logger = logging.getLogger("aria.shopify_engine")

class ShopifyEngine:
    """Motor de ejecución real para Shopify Admin API."""
    
    def __init__(self, shop_name: str, access_token: str):
        self.shop_name = shop_name
        self.access_token = access_token
        self.base_url = f"https://{shop_name}.myshopify.com/admin/api/2024-01"
        self.headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json"
        }

    def delete_all_products(self):
        """Elimina todos los productos de la tienda de forma real."""
        url = f"{self.base_url}/products.json"
        response = requests.get(url, headers=self.headers)
        products = response.json().get("products", [])
        
        for product in products:
            delete_url = f"{self.base_url}/products/{product['id']}.json"
            requests.delete(delete_url, headers=self.headers)
            logger.info(f"Producto eliminado: {product['title']}")
            
        return len(products)

    def create_premium_product(self, product_data: Dict[str, Any]):
        """Crea un producto con imágenes, inventario y descripción optimizada."""
        url = f"{self.base_url}/products.json"
        payload = {
            "product": {
                "title": product_data["title"],
                "body_html": product_data["description"],
                "vendor": "Aria Premium",
                "product_type": product_data.get("category", "Electronics"),
                "status": "active",
                "images": [{"src": img} for img in product_data.get("images", [])],
                "variants": [
                    {
                        "price": str(product_data["price"]),
                        "sku": product_data["sku"],
                        "inventory_management": "shopify",
                        "inventory_quantity": product_data.get("inventory", 10)
                    }
                ]
            }
        }
        response = requests.post(url, json=payload, headers=self.headers)
        if response.status_code == 201:
            logger.info(f"Producto creado: {product_data['title']}")
            return response.json()["product"]["id"]
        else:
            logger.error(f"Error creando producto: {response.text}")
            return None

    def update_storefront_theme(self, theme_id: str, assets: Dict[str, str]):
        """Actualiza el diseño de la tienda modificando los assets del tema."""
        for asset_key, content in assets.items():
            url = f"{self.base_url}/themes/{theme_id}/assets.json"
            payload = {
                "asset": {
                    "key": asset_key,
                    "value": content
                }
            }
            requests.put(url, json=payload, headers=self.headers)
            logger.info(f"Asset actualizado: {asset_key}")
