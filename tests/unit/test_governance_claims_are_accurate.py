"""Regression test: governance.SECURITY_CONTROLS (rendered on the public Trust
Center) used to claim "Sign-in is delegated to Google and GitHub OAuth — ARIA
never sees or stores your password" — false, since /signup and /login
(main.py) are a fully-functional email+password flow and auth_accounts.py
stores a PBKDF2-HMAC-SHA256 hash + salt per account. A false compliance claim
on a public trust page is a real legal/compliance risk, not just a copy nit."""

from __future__ import annotations

from apps.core.governance import SECURITY_CONTROLS


def test_no_control_falsely_claims_aria_never_stores_a_password():
    joined = " ".join(SECURITY_CONTROLS).lower()
    assert "never sees or stores your password" not in joined
    assert "never stores your password" not in joined


def test_password_control_accurately_describes_hashing():
    password_controls = [c for c in SECURITY_CONTROLS if "password" in c.lower()]
    assert password_controls, "expected at least one control mentioning passwords"
    assert any("pbkdf2" in c.lower() for c in password_controls)
