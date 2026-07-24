"""
Regression test: /static/* must actually be served.

There was no StaticFiles mount anywhere in apps/core/main.py — every
<script src="/static/js/...">/<link href="/static/css/...">` on the landing
and app pages 404'd, meaning every Web Component that renders its own content
in connectedCallback() (<aria-hero>, <aria-pricing>, <aria-agent-dashboard>)
silently produced empty tags in production, and aria.css never applied.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.core.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestStaticFilesMounted:
    def test_hero_component_js_is_served(self, client):
        r = client.get("/static/js/components/aria-hero.js")
        assert r.status_code == 200
        assert "customElements.define" in r.text

    def test_agent_dashboard_component_js_is_served(self, client):
        r = client.get("/static/js/components/aria-agent-dashboard.js")
        assert r.status_code == 200
        assert "aria-agent-dashboard" in r.text

    def test_pricing_component_js_is_served(self, client):
        r = client.get("/static/js/components/aria-pricing.js")
        assert r.status_code == 200

    def test_app_bootstrap_js_is_served(self, client):
        r = client.get("/static/js/aria-app.js")
        assert r.status_code == 200

    def test_stylesheet_is_served(self, client):
        r = client.get("/static/css/aria.css")
        assert r.status_code == 200
        assert "text/css" in r.headers.get("content-type", "")

    def test_unknown_static_path_is_404_not_500(self, client):
        r = client.get("/static/js/does-not-exist.js")
        assert r.status_code == 404
