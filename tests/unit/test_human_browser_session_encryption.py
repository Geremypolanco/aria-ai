"""Regression test: human_browser.py's _save_session()/_load_session() wrote
Playwright session cookies (live login credentials for HuggingFace, Dev.to,
Gumroad, Mailchimp, LinkedIn, Twitter, Reddit, etc. — acquired via
platform_onboarder.py/PlatformLogin) to a plaintext JSON file on local disk
(_SESSION_DIR, default /tmp/aria_sessions/{name}.json). Anyone able to read
that file/directory could hijack every one of those sessions. This is the
same plaintext-credential-storage bug class already fixed for
social_session.py's cookies and social_media.py's OAuth tokens — now reusing
the same AES-256-GCM token_crypto module, with legacy plaintext files still
readable.
"""

from __future__ import annotations

import json

from apps.core.tools.human_browser import SessionData, _load_session, _save_session


def test_save_session_encrypts_cookies_at_rest(tmp_path, monkeypatch):
    monkeypatch.setattr("apps.core.tools.human_browser._SESSION_DIR", tmp_path)

    session = SessionData(cookies=[{"name": "auth_token", "value": "super-secret-cookie-value"}])
    _save_session("gumroad", session)

    raw = (tmp_path / "gumroad.json").read_text()
    assert raw.startswith("enc:v1:")
    assert "super-secret-cookie-value" not in raw


def test_load_session_decrypts_cookies(tmp_path, monkeypatch):
    monkeypatch.setattr("apps.core.tools.human_browser._SESSION_DIR", tmp_path)

    session = SessionData(cookies=[{"name": "auth_token", "value": "super-secret-cookie-value"}])
    _save_session("gumroad", session)

    loaded = _load_session("gumroad")

    assert loaded is not None
    assert loaded.cookies == [{"name": "auth_token", "value": "super-secret-cookie-value"}]


def test_load_session_still_reads_legacy_plaintext_sessions(tmp_path, monkeypatch):
    """A session file written before encryption shipped stored raw JSON —
    must still load correctly."""
    monkeypatch.setattr("apps.core.tools.human_browser._SESSION_DIR", tmp_path)

    legacy = SessionData(cookies=[{"name": "auth_token", "value": "legacy-value"}])
    (tmp_path / "gumroad.json").write_text(json.dumps(legacy.to_dict()))

    loaded = _load_session("gumroad")

    assert loaded is not None
    assert loaded.cookies == [{"name": "auth_token", "value": "legacy-value"}]
