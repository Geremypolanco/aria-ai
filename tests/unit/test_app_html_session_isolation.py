"""Regression test: a shared/reused browser leaked one user's chat history to
the next person who signed in on it.

apps/core/templates/app.html used a single fixed localStorage key
("aria_missions_v1") for the mission/chat history shown in the UI, with no
per-account scoping. /logout (apps/core/main.py) only clears the server-side
session cookie — it never touches localStorage. So on a shared computer:
User A signs in, chats (missions saved under the shared key), signs out
(cookie cleared, localStorage untouched) -> User B signs in on the same
browser -> the app loads and renders User A's mission/chat history to User B.

Fixed by (1) keying storage per-account (MKEY includes USER.email), (2) a
wipeOtherAccountsData() guard that clears all aria_* localStorage keys the
moment the signed-in account differs from whoever last used this browser,
and (3) signOutCleanup() wired to the sign-out link so data is cleared
immediately rather than waiting for the next sign-in.

This test actually executes the real extracted <script> from app.html under
Node with a minimal in-memory localStorage shim, simulating two different
users sharing one browser — not just grepping for the fix.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP_HTML = Path(__file__).parent.parent.parent / "apps" / "core" / "templates" / "app.html"

requires_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def _render(email: str) -> str:
    html = APP_HTML.read_text(encoding="utf-8")
    html = (
        html.replace("__NAME__", "Test User")
        .replace("__FIRST__", "Test")
        .replace("__AVATAR__", "T")
        .replace("__INITIAL__", "T")
        .replace("__EMAIL__", email)
        .replace("__PLAN__", "Free")
        .replace("__ONBOARDED__", "true")
        .replace("__PROFILE_JSON__", "{}")
        .replace("__IS_OWNER__", "false")
        .replace("__ADMIN_LINK__", "")
    )
    match = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    assert match, "app.html must contain a <script> block"
    return match.group(1)


def _extract_between(script: str, start_marker: str, end_marker: str) -> str:
    start = script.index(start_marker)
    end = script.index(end_marker, start)
    return script[start:end]


@requires_node
def test_switching_accounts_on_the_same_browser_wipes_the_previous_users_data(tmp_path):
    script_a = _render("usera@example.com")
    script_b = _render("userb@example.com")

    # Pull out just the init block (USER/MKEY/wipeOtherAccountsData/signOutCleanup)
    # rather than the whole app — the rest depends on DOM elements this test
    # doesn't render.
    init_a = _extract_between(script_a, "const USER", "let missions = [];")
    init_b = _extract_between(script_b, "const USER", "let missions = [];")

    harness = f"""
const store = {{}};
const localStorage = {{
  getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
  setItem: (k, v) => {{ store[k] = String(v); }},
  removeItem: (k) => {{ delete store[k]; }},
  get length() {{ return Object.keys(store).length; }},
  key: (i) => Object.keys(store)[i] ?? null,
}};

// ── Session 1: user A signs in, uses the app, a mission gets saved ──
// Each session is its own block scope so re-declaring `const USER`/`MKEY`
// for the next user doesn't collide with the previous session's bindings —
// mirrors two separate page loads in real life, not one shared scope.
let userBMissions, userBKeyScoped;
{{
  {init_a}
  localStorage.setItem(MKEY, JSON.stringify([{{id: "m1", goal: "user A's private question"}}]));

  // ── User A signs out: our fix clears their data immediately ──
  signOutCleanup();
}}

// ── Session 2: user B signs in on the SAME browser/localStorage ──
{{
  {init_b}
  userBMissions = localStorage.getItem(MKEY);
  userBKeyScoped = MKEY.includes("userb@example.com");
}}

console.log(JSON.stringify({{
  userBSeesOwnKeyEmpty: userBMissions === null,
  userAKeyGone: localStorage.getItem("aria_missions_v1:usera@example.com") === null,
  keysScopedByEmail: userBKeyScoped,
}}));
"""
    script_path = tmp_path / "harness.js"
    script_path.write_text(harness, encoding="utf-8")
    result = subprocess.run(
        ["node", str(script_path)], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["userBSeesOwnKeyEmpty"] is True
    assert out["userAKeyGone"] is True
    assert out["keysScopedByEmail"] is True


@requires_node
def test_stale_data_from_a_browser_that_never_called_logout_is_still_wiped(tmp_path):
    """Covers the case our own signOutCleanup() can't: the tab was just
    closed / cookie expired without ever hitting /logout. The next sign-in's
    wipeOtherAccountsData() guard must catch it independently."""
    script_a = _render("usera@example.com")
    script_b = _render("userb@example.com")
    init_a = _extract_between(script_a, "const USER", "let missions = [];")
    init_b = _extract_between(script_b, "const USER", "let missions = [];")

    harness = f"""
const store = {{}};
const localStorage = {{
  getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
  setItem: (k, v) => {{ store[k] = String(v); }},
  removeItem: (k) => {{ delete store[k]; }},
  get length() {{ return Object.keys(store).length; }},
  key: (i) => Object.keys(store)[i] ?? null,
}};

let userBSeesUserAData;
// User A's browser session ends WITHOUT hitting /logout (no signOutCleanup call).
{{
  {init_a}
  localStorage.setItem(MKEY, JSON.stringify([{{id: "m1", goal: "user A's private question"}}]));
}}

// User B opens the same browser later and signs in directly.
{{
  {init_b}
  userBSeesUserAData = localStorage.getItem(MKEY) !== null;
}}

console.log(JSON.stringify({{
  userBSeesUserAData: userBSeesUserAData,
  userAKeyGone: localStorage.getItem("aria_missions_v1:usera@example.com") === null,
}}));
"""
    script_path = tmp_path / "harness2.js"
    script_path.write_text(harness, encoding="utf-8")
    result = subprocess.run(
        ["node", str(script_path)], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["userBSeesUserAData"] is False
    assert out["userAKeyGone"] is True


def test_logout_route_is_paired_with_client_side_cleanup():
    """/logout only clears the server-side cookie (apps/core/main.py) — the
    sign-out link must call signOutCleanup() to clear localStorage too."""
    html = APP_HTML.read_text(encoding="utf-8")
    assert 'href="/logout"' in html
    assert 'onclick="signOutCleanup()"' in html
    logout_line = next(line for line in html.splitlines() if 'href="/logout"' in line)
    assert "signOutCleanup()" in logout_line
