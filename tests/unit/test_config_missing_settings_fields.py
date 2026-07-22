"""Regression test: a repo-wide audit of apps/core/tools/income_loop.py (and
autonomous_scheduler.py, capabilities/catalog.py, lemon_squeezy_tools.py)
found dozens of getattr(settings, "SOME_NAME", default) call sites
referencing settings fields that were never declared on the Settings model.
Because Settings uses extra="ignore", an undeclared env var is silently
dropped and getattr's default always wins — permanently and silently
disabling the gated feature (SMTP email fallback, LemonSqueezy checkout,
direct-API Reddit/LinkedIn/YouTube posting, GitHub repo override) no matter
what the operator configures. Added the missing fields so these gates can
actually be satisfied once configured.

Also fixed two call sites that referenced a WRONG existing field name
(rather than a missing one): TWITTER_ACCESS_SECRET -> the real field is
TWITTER_ACCESS_TOKEN_SECRET; SENDGRID_FROM_EMAIL -> the real field is
EMAIL_FROM. Those are covered separately in test_income_loop_settings_fixes.py.
"""

from __future__ import annotations

from apps.core.config import settings


def test_previously_missing_settings_fields_now_exist():
    for field, default in [
        ("REDDIT_REFRESH_TOKEN", None),
        ("SMTP_HOST", None),
        ("SMTP_PORT", 587),
        ("SMTP_USER", None),
        ("SMTP_PASSWORD", None),
        ("SMTP_FROM", None),
        ("LEMONSQUEEZY_API_KEY", None),
        ("LEMONSQUEEZY_STORE_ID", None),
        ("YOUTUBE_API_KEY", None),
        ("LINKEDIN_ACCESS_TOKEN", None),
        ("LINKEDIN_PERSON_URN", None),
        ("GITHUB_REPO", None),
    ]:
        assert hasattr(settings, field), f"Settings is missing field {field}"
        assert getattr(settings, field) == default
