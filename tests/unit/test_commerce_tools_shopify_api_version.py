"""Regression test: shopify_create_product() and shopify_get_orders() used
different Shopify Admin API versions (2025-07 vs 2024-01). Given Shopify's
~12-month support window per release, the older version used by
shopify_get_orders() was already past end-of-life, meaning order retrieval
could silently fail or behave differently from product creation. Both
endpoints must target the same, current API version.
"""

from __future__ import annotations

import re

from apps.core.tools import commerce_tools


def test_shopify_endpoints_use_the_same_api_version():
    source = commerce_tools.__file__
    with open(source) as f:
        text = f.read()

    versions = set(re.findall(r"/admin/api/(\d{4}-\d{2})/", text))

    assert len(versions) == 1, f"Shopify endpoints use inconsistent API versions: {versions}"
