import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db as db_module  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    """Every test gets its own throwaway SQLite file — no shared state, no
    dependency on ARIA's Supabase/Postgres stack."""
    db_module.reset_for_tests(str(tmp_path / "test.db"))
    yield


def dev_login(client, email: str) -> None:
    """Simulates a completed Google login for a test client (no real Google
    credentials configured in the test environment, so `dev_login_enabled`
    is true — see config.Settings.dev_login_enabled). Sets either a pending
    cookie (first time) or a session cookie (returning user) on the client's
    cookie jar, exactly like a real Google OAuth callback would."""
    res = client.get("/auth/dev-login", params={"email": email}, follow_redirects=False)
    assert res.status_code == 303
