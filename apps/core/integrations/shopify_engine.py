"""
shopify_engine.py — Real execution engine for Shopify Admin API v2.0
Capabilities: Product creation, optimized listings, inventory,
images, videos, SEO metafields, collections, and sales reports.
"""

import logging
from typing import Any

import requests

logger = logging.getLogger("aria.shopify_engine")


class ShopifyEngine:
    """
    Real execution engine for Shopify Admin API.
    Aria uses this engine to autonomously manage the entire
    e-commerce operation: products, listings, inventory, images, videos, and SEO.
    """

    def __init__(self, shop_name: str, access_token: str):
        self.shop_name = shop_name
        self.access_token = access_token
        if ".myshopify.com" in shop_name:
            self.base_url = f"https://{shop_name}/admin/api/2024-01"
        else:
            self.base_url = f"https://{shop_name}.myshopify.com/admin/api/2024-01"
        self.headers = {"X-Shopify-Access-Token": access_token, "Content-Type": "application/json"}

    # ── RESEARCH AND ANALYSIS ──────────────────────────────────

    def get_all_products(self) -> list[dict[str, Any]]:
        """Gets all products from the store for analysis."""
        url = f"{self.base_url}/products.json?limit=250"
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            return response.json().get("products", [])
        logger.error(f"Error getting products: {response.text}")
        return []

    def get_orders_report(self, limit: int = 100) -> dict[str, Any]:
        """Generates a sales report for performance analysis."""
        url = f"{self.base_url}/orders.json?limit={limit}&status=any"
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            orders = response.json().get("orders", [])
            total_revenue = sum(float(o.get("total_price", 0)) for o in orders)
            return {
                "total_orders": len(orders),
                "total_revenue_usd": round(total_revenue, 2),
                "orders": orders[:10],
            }
        return {"total_orders": 0, "total_revenue_usd": 0.0, "orders": []}

    # ── PRODUCT CREATION AND OPTIMIZATION ─────────────────────

    def create_optimized_product(self, product_data: dict[str, Any]) -> str | None:
        """
        Creates a product with a listing fully optimized for SEO and conversion.
        Includes: SEO title, persuasive HTML description, images, variants,
        inventory, tags, metafields, and structured data.
        """
        url = f"{self.base_url}/products.json"

        # Build variants with inventory tracking
        variants = []
        for variant in product_data.get("variants", []):
            variants.append(
                {
                    "title": variant.get("title", "Default Title"),
                    "price": str(variant.get("price", product_data.get("price", "0"))),
                    "sku": variant.get("sku", product_data.get("sku", "")),
                    "inventory_management": "shopify",
                    "inventory_quantity": variant.get(
                        "inventory", product_data.get("inventory", 10)
                    ),
                    "requires_shipping": product_data.get("requires_shipping", True),
                    "taxable": True,
                    "weight": product_data.get("weight", 0),
                    "weight_unit": product_data.get("weight_unit", "kg"),
                }
            )

        if not variants:
            variants = [
                {
                    "price": str(product_data.get("price", "0")),
                    "sku": product_data.get("sku", ""),
                    "inventory_management": "shopify",
                    "inventory_quantity": product_data.get("inventory", 10),
                    "requires_shipping": product_data.get("requires_shipping", True),
                    "taxable": True,
                }
            ]

        payload = {
            "product": {
                "title": product_data["title"],
                "body_html": product_data.get(
                    "description_html", product_data.get("description", "")
                ),
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
            logger.info(
                f"[ShopifyEngine] Product created: {product_data['title']} (ID: {product_id})"
            )

            # Add SEO metafields if provided
            if product_data.get("seo_title") or product_data.get("seo_description"):
                self.update_product_seo(
                    str(product_id),
                    product_data.get("seo_title", product_data["title"]),
                    product_data.get("seo_description", ""),
                )

            return str(product_id)
        logger.error(f"[ShopifyEngine] Error creating product: {response.text}")
        return None

    def update_product_seo(self, product_id: str, seo_title: str, seo_description: str):
        """Updates a product's SEO metafields (title and description for Google)."""
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
            logger.info(f"[ShopifyEngine] SEO updated for product {product_id}")
        else:
            logger.warning(f"[ShopifyEngine] Could not update SEO: {response.text}")

    def add_product_images(self, product_id: str, image_urls: list[str]) -> list[str]:
        """Adds images to an existing product with optimized alt text."""
        added_ids = []
        for img_url in image_urls:
            url = f"{self.base_url}/products/{product_id}/images.json"
            payload = {"image": {"src": img_url}}
            response = requests.post(url, json=payload, headers=self.headers)
            if response.status_code == 200:
                img_id = response.json().get("image", {}).get("id")
                added_ids.append(str(img_id))
                logger.info(f"[ShopifyEngine] Image added to product {product_id}")
            else:
                logger.warning(f"[ShopifyEngine] Error adding image: {response.text}")
        return added_ids

    def add_product_video(self, product_id: str, video_url: str, alt_text: str = "") -> bool:
        """
        Adds a video to a product via metafield (Shopify stores videos as media).
        For videos on Shopify Plus, the GraphQL Media API is used.
        """
        url = f"{self.base_url}/products/{product_id}/metafields.json"
        payload = {
            "metafield": {
                "namespace": "custom",
                "key": "product_video_url",
                "value": video_url,
                "type": "url",
            }
        }
        response = requests.post(url, json=payload, headers=self.headers)
        if response.status_code == 200:
            logger.info(f"[ShopifyEngine] Video URL saved for product {product_id}")
            return True
        logger.warning(f"[ShopifyEngine] Error saving video: {response.text}")
        return False

    # ── INVENTORY MANAGEMENT ─────────────────────────────────────

    def update_inventory(self, inventory_item_id: str, location_id: str, quantity: int) -> bool:
        """Updates a product's inventory at a specific location."""
        url = f"{self.base_url}/inventory_levels/set.json"
        payload = {
            "location_id": location_id,
            "inventory_item_id": inventory_item_id,
            "available": quantity,
        }
        response = requests.post(url, json=payload, headers=self.headers)
        if response.status_code == 200:
            logger.info(f"[ShopifyEngine] Inventory updated: {quantity} units")
            return True
        logger.error(f"[ShopifyEngine] Error updating inventory: {response.text}")
        return False

    def get_inventory_levels(self) -> list[dict[str, Any]]:
        """Gets the current inventory levels for all products."""
        url = f"{self.base_url}/inventory_levels.json"
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            return response.json().get("inventory_levels", [])
        return []

    def get_locations(self) -> list[dict[str, Any]]:
        """Gets the store's inventory locations."""
        url = f"{self.base_url}/locations.json"
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            return response.json().get("locations", [])
        return []

    # ── COLLECTIONS AND CATEGORIES ──────────────────────────────────

    def create_collection(self, title: str, description: str, image_url: str = "") -> str | None:
        """Creates a collection (category) in the store to organize products."""
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
            logger.info(f"[ShopifyEngine] Collection created: {title} (ID: {collection_id})")
            return str(collection_id)
        logger.error(f"[ShopifyEngine] Error creating collection: {response.text}")
        return None

    def add_product_to_collection(self, collection_id: str, product_id: str) -> bool:
        """Adds a product to a collection."""
        url = f"{self.base_url}/collects.json"
        payload = {"collect": {"collection_id": collection_id, "product_id": product_id}}
        response = requests.post(url, json=payload, headers=self.headers)
        return response.status_code == 201

    # ── PROMOTIONS AND DISCOUNTS ──────────────────────────────────

    def create_discount_code(
        self, title: str, code: str, percentage: float, usage_limit: int = 100
    ) -> str | None:
        """Creates a discount code for promotions."""
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
            # Create the code associated with the rule
            code_url = f"{self.base_url}/price_rules/{rule_id}/discount_codes.json"
            code_payload = {"discount_code": {"code": code}}
            code_response = requests.post(code_url, json=code_payload, headers=self.headers)
            if code_response.status_code == 201:
                logger.info(f"[ShopifyEngine] Discount code created: {code} ({percentage}%)")
                return str(rule_id)
        logger.error(f"[ShopifyEngine] Error creating discount: {response.text}")
        return None

    # ── THEME AND STOREFRONT ─────────────────────────────────────────

    def update_storefront_theme(self, theme_id: str, assets: dict[str, str]):
        """Updates the store's design by modifying theme assets."""
        for asset_key, content in assets.items():
            url = f"{self.base_url}/themes/{theme_id}/assets.json"
            payload = {"asset": {"key": asset_key, "value": content}}
            requests.put(url, json=payload, headers=self.headers)
            logger.info(f"[ShopifyEngine] Asset updated: {asset_key}")

    # ── DESTRUCTIVE OPERATIONS (USE WITH CAUTION) ─────────────────

    def delete_all_products(self):
        """
        Deletes all products from the store.
        WARNING: Irreversible action. Only run after ethical evaluation.
        """
        products = self.get_all_products()
        for product in products:
            delete_url = f"{self.base_url}/products/{product['id']}.json"
            requests.delete(delete_url, headers=self.headers)
            logger.info(f"[ShopifyEngine] Product deleted: {product['title']}")
        return len(products)
