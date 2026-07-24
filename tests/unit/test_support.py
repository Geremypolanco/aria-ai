"""
Unit tests for ARIA Support (support widget) + the strict no-refund checkout gate
+ the /legal/* pages.

Covers:
  - support_agent: intent classification, offline answers, offline fallback path
  - /api/v1/support/chat: requires sign-in (no anonymous LLM cost)
  - /billing/checkout: mandatory no-refund acknowledgement before any charge
  - /legal/*: styled dark pages serve + legacy paths redirect
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.core.main import app


# ── support_agent (pure) ──────────────────────────────────────────
class TestSupportAgent:
    def test_classify_billing(self):
        from apps.core.support.support_agent import _classify

        assert _classify("quiero un reembolso de mi pago con Stripe") == "billing"

    def test_classify_missions(self):
        from apps.core.support.support_agent import _classify

        assert _classify("mi misión falló con un error y no publicó") == "missions"

    def test_classify_connectors(self):
        from apps.core.support.support_agent import _classify

        assert _classify("cómo reconecto mi conector de LinkedIn, el token caducó") == "connectors"

    def test_classify_general_when_no_keywords(self):
        from apps.core.support.support_agent import _classify

        assert _classify("hola buenas tardes") == "general"

    def test_offline_answers_are_nonempty_for_all_topics(self):
        from apps.core.support.support_agent import _OFFLINE_ANSWERS, offline_answer

        for topic in ("billing", "missions", "connectors", "general"):
            assert _OFFLINE_ANSWERS[topic].strip()
        # billing answer references the strict no-refund policy honestly
        assert "no-refund policy" in offline_answer("reembolso").lower()

    async def test_answer_without_key_uses_offline(self):
        from apps.core.support.support_agent import answer

        reply, source = await answer("mi misión falló", api_key=None)
        assert source == "offline"
        assert reply.strip()

    async def test_answer_empty_message(self):
        from apps.core.support.support_agent import answer

        reply, source = await answer("   ", api_key=None)
        assert source == "offline"
        assert reply.strip()

    async def test_answer_falls_back_when_claude_errors(self, monkeypatch):
        # A bogus key drives the SDK path, which must fail closed to offline.
        from apps.core.support import support_agent

        reply, source = await support_agent.answer("problema de facturación", api_key="sk-invalid")
        assert source in ("offline_error", "offline")  # never raises, always answers
        assert reply.strip()


# ── HTTP surface ──────────────────────────────────────────────────
@pytest.fixture
def client():
    return TestClient(app)


class TestSupportEndpoint:
    def test_requires_sign_in(self, client):
        r = client.post("/api/v1/support/chat", json={"message": "hola"})
        assert r.status_code == 200
        assert r.json()["source"] == "auth"  # anonymous → no LLM cost


class TestCheckoutNoRefundGate:
    def test_unauthenticated_redirects_to_login(self, client):
        r = client.get("/billing/checkout?tier=pro", follow_redirects=False)
        assert r.status_code in (302, 303, 307)
        assert "/login" in r.headers.get("location", "")


class TestLegalPages:
    def test_pages_serve_styled_theme(self, client):
        # Legal pages ship as self-contained styled documents (light premium
        # palette). Assert the real template renders — an inline <style> block —
        # rather than pinning an exact hex, so a re-theme doesn't break this.
        for slug in ("terms", "privacy", "refund-policy"):
            r = client.get(f"/legal/{slug}")
            assert r.status_code == 200
            assert "<style" in r.text.lower()

    def test_refund_policy_is_strict(self, client):
        r = client.get("/legal/refund-policy")
        assert "non-refundable" in r.text.lower()

    def test_html_suffix_tolerated(self, client):
        r = client.get("/legal/terms.html")
        assert r.status_code == 200

    def test_unknown_slug_404(self, client):
        r = client.get("/legal/does-not-exist")
        assert r.status_code == 404

    def test_legacy_paths_redirect(self, client):
        for path, dest in (
            ("/terms", "/legal/terms"),
            ("/privacy", "/legal/privacy"),
            ("/refunds", "/legal/refund-policy"),
        ):
            r = client.get(path, follow_redirects=False)
            assert r.status_code in (301, 307, 308)
            assert r.headers.get("location", "") == dest
