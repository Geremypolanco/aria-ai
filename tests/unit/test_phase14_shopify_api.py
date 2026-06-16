"""Phase 14 tests — ShopifyAPIClient."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def client():
    from apps.shopify.api_client import ShopifyAPIClient
    return ShopifyAPIClient()


# ── Configuration ─────────────────────────────────────────────────────────────

def test_client_not_configured_by_default(client):
    assert client.is_configured is False


def test_client_status_has_required_keys(client):
    status = client.client_status()
    required = {"configured", "domain", "api_version", "cached_products", "cached_orders"}
    assert required.issubset(status.keys())


def test_client_status_not_configured(client):
    status = client.client_status()
    assert status["configured"] is False


def test_client_api_version_set(client):
    assert len(client._api_version) > 0


def test_client_cached_products_starts_empty(client):
    assert client.client_status()["cached_products"] == 0


def test_client_cached_orders_starts_empty(client):
    assert client.client_status()["cached_orders"] == 0


# ── Unconfigured graceful degradation ────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_products_returns_empty_when_unconfigured(client):
    result = await client.get_products()
    assert isinstance(result, list)
    assert len(result) == 0


@pytest.mark.asyncio
async def test_get_orders_returns_empty_when_unconfigured(client):
    result = await client.get_orders()
    assert isinstance(result, list)
    assert len(result) == 0


@pytest.mark.asyncio
async def test_update_product_returns_none_when_unconfigured(client):
    result = await client.update_product("123", {"title": "New"})
    assert result is None


@pytest.mark.asyncio
async def test_get_revenue_analytics_returns_analytics_when_unconfigured(client):
    from apps.shopify.api_client import ShopifyAnalytics
    result = await client.get_revenue_analytics()
    assert isinstance(result, ShopifyAnalytics)


@pytest.mark.asyncio
async def test_revenue_analytics_period_set(client):
    result = await client.get_revenue_analytics(days=30)
    assert "30" in result.period or "last" in result.period


@pytest.mark.asyncio
async def test_graphql_query_returns_dict(client):
    result = await client.graphql_query("{ shop { name } }")
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_optimize_product_seo_returns_false_unconfigured(client):
    result = await client.optimize_product_seo("123", "SEO Title", "SEO Description")
    assert result is False


# ── Dataclass tests ───────────────────────────────────────────────────────────

def test_shopify_product_to_dict():
    from apps.shopify.api_client import ShopifyProduct
    p = ShopifyProduct(product_id="1", title="Test", description="Desc", price=29.99, inventory_qty=10)
    d = p.to_dict()
    required = {"product_id", "title", "description", "price", "inventory_qty", "status", "tags"}
    assert required.issubset(d.keys())


def test_shopify_order_to_dict():
    from apps.shopify.api_client import ShopifyOrder
    o = ShopifyOrder(order_id="100", total_price=99.99, status="closed")
    d = o.to_dict()
    required = {"order_id", "total_price", "status", "customer_email", "line_items", "created_at"}
    assert required.issubset(d.keys())


def test_shopify_analytics_to_dict():
    from apps.shopify.api_client import ShopifyAnalytics
    a = ShopifyAnalytics(period="last_30_days", total_revenue=5000.0, orders_count=50, avg_order_value=100.0)
    d = a.to_dict()
    required = {"period", "total_revenue", "orders_count", "avg_order_value", "top_products", "conversion_rate_pct"}
    assert required.issubset(d.keys())


# ── Configured client with mocked HTTP ───────────────────────────────────────

@pytest.fixture
def configured_client():
    import os
    with patch.dict(os.environ, {"SHOPIFY_SHOP_DOMAIN": "test.myshopify.com", "SHOPIFY_ACCESS_TOKEN": "test_token"}):
        from apps.shopify.api_client import ShopifyAPIClient
        c = ShopifyAPIClient()
    return c


def test_configured_client_is_configured(configured_client):
    assert configured_client.is_configured is True


def test_configured_client_base_url(configured_client):
    assert "test.myshopify.com" in configured_client.base_url
    assert "admin/api" in configured_client.base_url


@pytest.mark.asyncio
async def test_get_products_handles_http_error(configured_client):
    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
        mock_cls.return_value = mock_client
        result = await configured_client.get_products()
    assert isinstance(result, list)
    assert len(result) == 0


@pytest.mark.asyncio
async def test_get_orders_handles_http_error(configured_client):
    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("Timeout"))
        mock_cls.return_value = mock_client
        result = await configured_client.get_orders()
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_get_products_parses_response(configured_client):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "products": [
            {"id": "1", "title": "Test Product", "body_html": "Description", "status": "active",
             "tags": "tag1,tag2", "variants": [{"price": "29.99", "inventory_quantity": 100}]}
        ]
    }
    mock_response.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_http
        products = await configured_client.get_products()
    assert len(products) == 1
    assert products[0].title == "Test Product"


# ── Singleton ─────────────────────────────────────────────────────────────────

def test_get_shopify_api_client_returns_instance():
    from apps.shopify.api_client import get_shopify_api_client
    c = get_shopify_api_client()
    assert c is not None
