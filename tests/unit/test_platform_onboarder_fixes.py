"""Regression test for a bug found auditing platform_onboarder.py:

`PlatformOnboarder.onboard_all()`'s `platforms` list used two settings-field
names that don't exist anywhere in the real Pydantic Settings model
(apps/core/config.py): "HUGGINGFACE_API_KEY" and "GUMROAD_ACCESS_TOKEN".
The real fields are HF_TOKEN and GUMROAD_TOKEN. Because `_has_token()` reads
the field via `getattr(settings, attr, None)`, the typo'd names silently
always returned None/False — so even when a real token was already
configured via Fly.io secrets, the onboarder believed no token existed and
re-ran browser automation every cycle. Worse, any token it did acquire was
stored under a key nothing else in the app ever reads (ai_client.py reads
settings.hf_key / HF_TOKEN, gumroad_tools.py reads settings.GUMROAD_TOKEN),
so the acquired credential was effectively discarded.
"""

from __future__ import annotations

import pytest

from apps.core.tools.platform_onboarder import PlatformOnboarder, _has_token


def test_onboard_all_platform_list_uses_real_settings_field_names(monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.ARIA_EMAIL", "bot@example.com")
    monkeypatch.setattr("apps.core.config.settings.ARIA_PASSWORD", "secret")

    onboarder = PlatformOnboarder()
    assert onboarder._can_automate() is True


@pytest.mark.asyncio
async def test_has_token_recognizes_configured_huggingface_token(monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.HF_TOKEN", "hf_abcdefghijklmnop")
    monkeypatch.setattr("apps.core.config.settings.GUMROAD_TOKEN", None)

    assert _has_token("HF_TOKEN") is True
    assert _has_token("GUMROAD_TOKEN") is False


@pytest.mark.asyncio
async def test_has_token_recognizes_configured_gumroad_token(monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.GUMROAD_TOKEN", "gr_live_token_value")

    assert _has_token("GUMROAD_TOKEN") is True


@pytest.mark.asyncio
async def test_onboard_all_skips_platforms_with_already_configured_tokens(monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.ARIA_EMAIL", "bot@example.com")
    monkeypatch.setattr("apps.core.config.settings.ARIA_PASSWORD", "secret")
    monkeypatch.setattr("apps.core.config.settings.HF_TOKEN", "hf_already_configured")
    monkeypatch.setattr("apps.core.config.settings.DEVTO_API_KEY", "already_configured")
    monkeypatch.setattr("apps.core.config.settings.GUMROAD_TOKEN", "already_configured")
    monkeypatch.setattr("apps.core.config.settings.MAILCHIMP_API_KEY", "already_configured")

    onboarder = PlatformOnboarder()
    report = await onboarder.onboard_all()

    assert len(report.results) == 4
    assert all(r.already_had_token for r in report.results)
    token_keys = {r.token_key for r in report.results}
    assert token_keys == {"HF_TOKEN", "DEVTO_API_KEY", "GUMROAD_TOKEN", "MAILCHIMP_API_KEY"}
