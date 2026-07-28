"""Tests for apps/shopify/api_client.py's get_shopify_client_for(workspace_id)
— the piece that makes Shopify multi-tenant rather than every workspace
sharing one real store.

Before this, ALL Shopify tools read a single global SHOPIFY_SHOP_DOMAIN/
SHOPIFY_ACCESS_TOKEN, so even scoping CashflowEngine/ROITracker's Redis keys
per workspace wouldn't have given a team an actually-isolated store — every
workspace would still hit the owner's real Shopify account. Real per-tenant
isolation requires each workspace to have its OWN connected store
(apps/core/connectors/oauth_hub.py's Shopify OAuth flow), which is what this
resolver looks up.

The critical case under test, mirroring CashflowEngine/ROITracker's legacy-
key fallback: the owner's env-configured store must be used ONLY for the
real owner's own workspace_id, never for any other/new workspace that
hasn't connected its own store — that would leak the owner's real store
credentials to a workspace that never granted access.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.shopify.api_client import ShopifyAPIClient, get_shopify_client_for

pytestmark = pytest.mark.asyncio


async def test_returns_unconfigured_client_for_blank_workspace():
    client = await get_shopify_client_for("")
    assert client.is_configured is False


async def test_workspace_with_its_own_connected_store_uses_it():
    connected_record = {
        "access_token": "shpat_team_own_token",
        "shop_domain": "team-store.myshopify.com",
    }
    with (
        patch(
            "apps.core.connectors.oauth_hub.get_token",
            AsyncMock(return_value=connected_record),
        ),
        patch("apps.core.auth.owner_emails", return_value=set()),
    ):
        client = await get_shopify_client_for("team@example.com")

    assert client.is_configured is True
    assert client._domain == "team-store.myshopify.com"
    assert client._token == "shpat_team_own_token"


async def test_non_owner_workspace_without_a_connected_store_gets_no_credentials():
    """The critical isolation guarantee: a workspace that hasn't connected
    its own Shopify store must NOT fall back to the owner's real store —
    that would leak the owner's actual store data/write-access to a tenant
    who never granted it."""
    with (
        patch("apps.core.connectors.oauth_hub.get_token", AsyncMock(return_value=None)),
        patch("apps.core.auth.owner_emails", return_value={"real-owner@example.com"}),
        patch.dict(
            "os.environ",
            {
                "SHOPIFY_SHOP_DOMAIN": "owners-real-store.myshopify.com",
                "SHOPIFY_ACCESS_TOKEN": "shpat_owner_real_token",
            },
        ),
    ):
        client = await get_shopify_client_for("brand-new-team@example.com")

    assert client.is_configured is False
    assert client._domain == ""
    assert client._token == ""


async def test_the_real_owners_own_workspace_gets_the_legacy_env_store():
    with (
        patch("apps.core.connectors.oauth_hub.get_token", AsyncMock(return_value=None)),
        patch("apps.core.auth.owner_emails", return_value={"real-owner@example.com"}),
        patch.dict(
            "os.environ",
            {
                "SHOPIFY_SHOP_DOMAIN": "owners-real-store.myshopify.com",
                "SHOPIFY_ACCESS_TOKEN": "shpat_owner_real_token",
            },
        ),
    ):
        client = await get_shopify_client_for("real-owner@example.com")

    assert client.is_configured is True
    assert client._domain == "owners-real-store.myshopify.com"
    assert client._token == "shpat_owner_real_token"


async def test_connected_store_takes_priority_over_the_owner_fallback():
    """Even the real owner, if they've connected their OWN store via the
    per-workspace flow, should use THAT — not silently keep reading the
    legacy env-configured store."""
    connected_record = {
        "access_token": "shpat_newly_connected",
        "shop_domain": "newly-connected.myshopify.com",
    }
    with (
        patch(
            "apps.core.connectors.oauth_hub.get_token",
            AsyncMock(return_value=connected_record),
        ),
        patch("apps.core.auth.owner_emails", return_value={"real-owner@example.com"}),
        patch.dict(
            "os.environ",
            {
                "SHOPIFY_SHOP_DOMAIN": "owners-legacy-store.myshopify.com",
                "SHOPIFY_ACCESS_TOKEN": "shpat_legacy",
            },
        ),
    ):
        client = await get_shopify_client_for("real-owner@example.com")

    assert client._domain == "newly-connected.myshopify.com"
    assert client._token == "shpat_newly_connected"


async def test_resolution_is_not_cached_across_calls():
    """Regression guard: a cached-per-workspace client would freeze whatever
    credentials resolved on the FIRST call — meaning a workspace that
    connects its own store after an earlier unconfigured lookup would stay
    stuck reading nothing until the process restarts. Each call must
    re-resolve from the current state instead."""
    with (
        patch("apps.core.connectors.oauth_hub.get_token", AsyncMock(return_value=None)),
        patch("apps.core.auth.owner_emails", return_value=set()),
    ):
        first = await get_shopify_client_for("team@example.com")
    assert first.is_configured is False

    connected_record = {
        "access_token": "shpat_just_connected",
        "shop_domain": "just-connected.myshopify.com",
    }
    with (
        patch(
            "apps.core.connectors.oauth_hub.get_token",
            AsyncMock(return_value=connected_record),
        ),
        patch("apps.core.auth.owner_emails", return_value=set()),
    ):
        second = await get_shopify_client_for("team@example.com")

    assert second.is_configured is True
    assert second._domain == "just-connected.myshopify.com"


async def test_client_constructor_accepts_explicit_domain_and_token():
    """Regression: the constructor used to unconditionally read from
    os.environ, so there was no way to build a client for anything other
    than this deployment's single global store."""
    client = ShopifyAPIClient(domain="explicit.myshopify.com", token="explicit-token")
    assert client._domain == "explicit.myshopify.com"
    assert client._token == "explicit-token"
    assert client.is_configured is True
