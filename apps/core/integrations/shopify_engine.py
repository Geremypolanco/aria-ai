"""
shopify_engine.py — Motor de ejecución real para Shopify Admin API v2.0
Capacidades: Creación de productos, listings optimizados, inventario,
imágenes, videos, metafields SEO, colecciones y reportes de ventas.
"""
import requests
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("aria.shopify_engine")


class ShopifyEngine:
    """
    Motor de ejecución real para Shopify Admin API.
    Aria usa este motor para gestionar de forma autónoma toda la operación
    de e-commerce: productos, listings, inventario, imágenes, videos y SEO.
    """

    def __init__(self, shop_name: str, access_token: str):
        self.shop_name = shop_name
        self.access_token = access_token
        self.base_url = f"https://{shop_name}.myshopify.com/admin/api/2024-01"
        self.headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json"
        }

    # ── INVESTIGACIÓN Y ANÁLISIS ──────────────────────────────────

    def get_all_products(self) -> List[Dict[str, Any]]:
        """Obtiene todos los productos de la tienda para análisis."""
        url = f"{self.base_url}/products.json?limit=250"
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            return response.json().get("products", [])
        logger.error(f"Error obteniendo productos: {response.text}")
        return []

    def get_orders_report(self, limit: int = 100) -> Dict[str, Any]:
        """Genera un reporte de ventas para análisis de rendimiento."""
        url = f"{self.base_url}/orders.json?limit={limit}&status=any"
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            orders = response.json().get("orders", [])
            total_revenue = sum(float(o.get("total_price", 0)) for o in orders)
            return {
                "total_orders": len(orders),
                "total_revenue_usd": round(total_revenue, 2),
                "orders": orders[:10]
            }
        return {"total_orders": 0, "total_revenue_usd": 0.0, "orders": []}

    # ── CREACIÓN Y OPTIMIZACIÓN DE PRODUCTOS ─────────────────────

    def create_optimized_product(self, product_data: Dict[str, Any]) -> Optional[str]:
        """
        Crea un producto con listing completamente optimizado para SEO y conversión.
        Incluye: título SEO, descripción HTML persuasiva, imágenes, variantes,
        inventario, tags, metafields y datos estructurados.
        """
        url = f"{self.base_url}/products.json"

        # Construir variantes con control de inventario
        variants = []
        for variant in product_data.get("variants", []):
            variants.append({
                "title": variant.get("title", "Default Title"),
                "price": str(variant.get("price", product_data.get("price", "0"))),
                "sku": variant.get("sku", product_data.get("sku", "")),
                "inventory_management": "shopify",
                "inventory_quantity": variant.get("inventory", product_data.get("inventory", 10)),
                "requires_shipping": product_data.get("requires_shipping", True),
                "taxable": True,
                "weight": product_data.get("weight", 0),
                "weight_unit": product_data.get("weight_unit", "kg"),
            })

        if not variants:
            variants = [{
                "price": str(product_data.get("price", "0")),
                "sku": product_data.get("sku", ""),
                "inventory_management": "shopify",
                "inventory_quantity": product_data.get("inventory", 10),
                "requires_shipping": product_data.get("requires_shipping", True),
                "taxable": True,
            }]

        payload = {
            "product": {
                "title": product_data["title"],
                "body_html": product_data.get("description_html", product_data.get("description", "")),
                "vendor": product_data.get("vendor", "Aria Premium"),
                "product_type": product_data.get("category", "General"),
                "status": product_data.get("status", "active"),
                "tags": ", ".join(product_data.get("tags", [])),
                "images": [
                    {"src": img, "alt": product_data.get("title", "")}
                    for img in product_data.get("images", [])
                ],
                "variants": variants,
            }
        }

        response = requests.post(url, json=payload, headers=self.headers)
        if response.status_code == 201:
            product = response.json().get("product", {})
            product_id = product.get("id")
            logger.info(f"[ShopifyEngine] Producto creado: {product_data['title']} (ID: {product_id})")

            # Añadir metafields SEO si se proporcionan
            if product_data.get("seo_title") or product_data.get("seo_description"):
                self.update_product_seo(
                    str(product_id),
                    product_data.get("seo_title", product_data["title"]),
                    product_data.get("seo_description", "")
                )

            return str(product_id)
        else:
            logger.error(f"[ShopifyEngine] Error creando producto: {response.text}")
            return None

    def update_product_seo(self, product_id: str, seo_title: str, seo_description: str):
        """Actualiza los metafields de SEO de un producto (título y descripción para Google)."""
        url = f"{self.base_url}/products/{product_id}.json"
        payload = {
            "product": {
                "id": product_id,
                "metafields_global_title_tag": seo_title,
                "metafields_global_description_tag": seo_description,
            }
        }
        response = requests.put(url, json=payload, headers=self.headers)
        if response.status_code == 200:
            logger.info(f"[ShopifyEngine] SEO actualizado para producto {product_id}")
        else:
            logger.warning(f"[ShopifyEngine] No se pudo actualizar SEO: {response.text}")

    def add_product_images(self, product_id: str, image_urls: List[str]) -> List[str]:
        """Añade imágenes a un producto existente con alt text optimizado."""
        added_ids = []
        for img_url in image_urls:
            url = f"{self.base_url}/products/{product_id}/images.json"
            payload = {"image": {"src": img_url}}
            response = requests.post(url, json=payload, headers=self.headers)
            if response.status_code == 200:
                img_id = response.json().get("image", {}).get("id")
                added_ids.append(str(img_id))
                logger.info(f"[ShopifyEngine] Imagen añadida al producto {product_id}")
            else:
                logger.warning(f"[ShopifyEngine] Error añadiendo imagen: {response.text}")
        return added_ids

    def add_product_video(self, product_id: str, video_url: str, alt_text: str = "") -> bool:
        """
        Añade un video a un producto via metafield (Shopify almacena videos como media).
        Para videos en Shopify Plus se usa la GraphQL Media API.
        """
        url = f"{self.base_url}/products/{product_id}/metafields.json"
        payload = {
            "metafield": {
                "namespace": "custom",
                "key": "product_video_url",
                "value": video_url,
                "type": "url"
            }
        }
        response = requests.post(url, json=payload, headers=self.headers)
        if response.status_code == 200:
            logger.info(f"[ShopifyEngine] Video URL guardado para producto {product_id}")
            return True
        logger.warning(f"[ShopifyEngine] Error guardando video: {response.text}")
        return False

    # ── GESTIÓN DE INVENTARIO ─────────────────────────────────────

    def update_inventory(self, inventory_item_id: str, location_id: str, quantity: int) -> bool:
        """Actualiza el inventario de un producto en una ubicación específica."""
        url = f"{self.base_url}/inventory_levels/set.json"
        payload = {
            "location_id": location_id,
            "inventory_item_id": inventory_item_id,
            "available": quantity
        }
        response = requests.post(url, json=payload, headers=self.headers)
        if response.status_code == 200:
            logger.info(f"[ShopifyEngine] Inventario actualizado: {quantity} unidades")
            return True
        logger.error(f"[ShopifyEngine] Error actualizando inventario: {response.text}")
        return False

    def get_inventory_levels(self) -> List[Dict[str, Any]]:
        """Obtiene los niveles de inventario actuales de todos los productos."""
        url = f"{self.base_url}/inventory_levels.json"
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            return response.json().get("inventory_levels", [])
        return []

    def get_locations(self) -> List[Dict[str, Any]]:
        """Obtiene las ubicaciones de inventario de la tienda."""
        url = f"{self.base_url}/locations.json"
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            return response.json().get("locations", [])
        return []

    # ── COLECCIONES Y CATEGORÍAS ──────────────────────────────────

    def create_collection(self, title: str, description: str, image_url: str = "") -> Optional[str]:
        """Crea una colección (categoría) en la tienda para organizar productos."""
        url = f"{self.base_url}/custom_collections.json"
        payload = {
            "custom_collection": {
                "title": title,
                "body_html": description,
                "published": True,
            }
        }
        if image_url:
            payload["custom_collection"]["image"] = {"src": image_url}

        response = requests.post(url, json=payload, headers=self.headers)
        if response.status_code == 201:
            collection_id = response.json().get("custom_collection", {}).get("id")
            logger.info(f"[ShopifyEngine] Colección creada: {title} (ID: {collection_id})")
            return str(collection_id)
        logger.error(f"[ShopifyEngine] Error creando colección: {response.text}")
        return None

    def add_product_to_collection(self, collection_id: str, product_id: str) -> bool:
        """Añade un producto a una colección."""
        url = f"{self.base_url}/collects.json"
        payload = {"collect": {"collection_id": collection_id, "product_id": product_id}}
        response = requests.post(url, json=payload, headers=self.headers)
        return response.status_code == 201

    # ── PROMOCIONES Y DESCUENTOS ──────────────────────────────────

    def create_discount_code(self, title: str, code: str, percentage: float, usage_limit: int = 100) -> Optional[str]:
        """Crea un código de descuento para promociones."""
        url = f"{self.base_url}/price_rules.json"
        payload = {
            "price_rule": {
                "title": title,
                "target_type": "line_item",
                "target_selection": "all",
                "allocation_method": "across",
                "value_type": "percentage",
                "value": f"-{percentage}",
                "customer_selection": "all",
                "starts_at": "2024-01-01T00:00:00Z",
                "usage_limit": usage_limit,
            }
        }
        response = requests.post(url, json=payload, headers=self.headers)
        if response.status_code == 201:
            rule_id = response.json().get("price_rule", {}).get("id")
            # Crear el código asociado a la regla
            code_url = f"{self.base_url}/price_rules/{rule_id}/discount_codes.json"
            code_payload = {"discount_code": {"code": code}}
            code_response = requests.post(code_url, json=code_payload, headers=self.headers)
            if code_response.status_code == 201:
                logger.info(f"[ShopifyEngine] Código de descuento creado: {code} ({percentage}%)")
                return str(rule_id)
        logger.error(f"[ShopifyEngine] Error creando descuento: {response.text}")
        return None

    # ── TEMA Y STOREFRONT ─────────────────────────────────────────

    def update_storefront_theme(self, theme_id: str, assets: Dict[str, str]):
        """Actualiza el diseño de la tienda modificando los assets del tema."""
        for asset_key, content in assets.items():
            url = f"{self.base_url}/themes/{theme_id}/assets.json"
            payload = {"asset": {"key": asset_key, "value": content}}
            requests.put(url, json=payload, headers=self.headers)
            logger.info(f"[ShopifyEngine] Asset actualizado: {asset_key}")

    # ── OPERACIONES DESTRUCTIVAS (CON PRECAUCIÓN) ─────────────────

    def delete_all_products(self):
        """
        Elimina todos los productos de la tienda.
        ADVERTENCIA: Acción irreversible. Solo ejecutar tras evaluación ética.
        """
        products = self.get_all_products()
        for product in products:
            delete_url = f"{self.base_url}/products/{product['id']}.json"
            requests.delete(delete_url, headers=self.headers)
            logger.info(f"[ShopifyEngine] Producto eliminado: {product['title']}")
        return len(products)
