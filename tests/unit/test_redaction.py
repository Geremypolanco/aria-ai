"""Feature test: apps/core/safety/redaction.py closes the gap CodeRabbit
flagged on PR #131 — AITrace's tool_args/raw_observation fields were bounded
for size but never checked for sensitivity, so a real secret passed as a
tool argument (an API key, a password) or embedded in a tool's raw output
(a leaked token in an error message) would be persisted and broadcast to
the admin_activity feed verbatim within that bound.

tool_args (a dict) is redacted by key name; raw_observation (free text) by
a short list of high-confidence secret-format patterns — see redaction.py's
module docstring for why each approach fits its input shape.
"""

from __future__ import annotations

from apps.core.safety.redaction import redact_sensitive_args, redact_sensitive_text


def test_redacts_a_top_level_sensitive_key():
    result = redact_sensitive_args({"api_key": "sk-real-secret-value", "query": "yoga tips"})
    assert result["api_key"] == "[REDACTED]"
    assert result["query"] == "yoga tips"


def test_case_insensitive_and_substring_match():
    result = redact_sensitive_args({"Stripe_API_Key": "sk_live_abc123", "DB_PASSWORD": "hunter2"})
    assert result["Stripe_API_Key"] == "[REDACTED]"
    assert result["DB_PASSWORD"] == "[REDACTED]"


def test_recurses_into_nested_dicts():
    result = redact_sensitive_args({"config": {"api_key": "secret", "region": "us-east-1"}})
    assert result["config"]["api_key"] == "[REDACTED]"
    assert result["config"]["region"] == "us-east-1"


def test_recurses_into_lists_of_dicts():
    result = redact_sensitive_args({"accounts": [{"token": "abc"}, {"name": "no secret here"}]})
    assert result["accounts"][0]["token"] == "[REDACTED]"
    assert result["accounts"][1] == {"name": "no secret here"}


def test_recurses_into_nested_lists_of_lists():
    """Regression (CodeRabbit, PR #135): {"batches": [[{"api_key": "..."}]]}
    used to leak — the list branch only recursed into dict items directly
    inside the list, so a list nested inside that list (itself not a dict)
    passed through unchanged, and its inner dict's secret was never reached.
    """
    result = redact_sensitive_args({"batches": [[{"api_key": "secret"}, {"name": "ok"}]]})
    assert result["batches"][0][0]["api_key"] == "[REDACTED]"
    assert result["batches"][0][1] == {"name": "ok"}


def test_leaves_non_sensitive_args_completely_unchanged():
    original = {"product_name": "Widget Pro", "category": "gadgets", "price": 19.99}
    result = redact_sensitive_args(original)
    assert result == original


def test_does_not_mutate_the_input():
    original = {"password": "hunter2"}
    redact_sensitive_args(original)
    assert original["password"] == "hunter2"


def test_none_and_empty_pass_through_unchanged():
    assert redact_sensitive_args(None) is None
    assert redact_sensitive_args({}) == {}


# ── redact_sensitive_text (free-text raw_observation) ────────────────────


def test_redacts_a_bearer_header():
    text = "Request failed: Authorization: Bearer sk-abcDEF123456789012345 was rejected"
    result = redact_sensitive_text(text)
    assert "sk-abcDEF123456789012345" not in result
    assert "[REDACTED]" in result


def test_redacts_a_jwt():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PYb4NJx-Ta8Q"
    result = redact_sensitive_text(f"token: {jwt}")
    assert jwt not in result
    assert "[REDACTED]" in result


def test_redacts_openai_style_api_key():
    result = redact_sensitive_text("Error using key sk-proj-abcdefghijklmnopqrstuvwxyz1234567890")
    assert "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890" not in result
    assert "[REDACTED]" in result


def test_redacts_a_github_token():
    result = redact_sensitive_text("cloning with ghp_" + "a" * 36 + " failed: permission denied")
    assert "ghp_" + "a" * 36 not in result
    assert "[REDACTED]" in result


def test_redacts_a_github_fine_grained_pat():
    """Regression (CodeRabbit, PR #136): fine-grained PATs use the
    github_pat_ prefix, a completely different literal string from the
    legacy ghp_/gho_/ghu_/ghs_/ghr_ tokens — not covered by that pattern."""
    token = "github_pat_11ABCDEFG0abcdefghijklmnop_" + "a" * 20
    result = redact_sensitive_text(f"push rejected using {token}")
    assert token not in result
    assert "[REDACTED]" in result


def test_redacts_a_new_format_stateless_github_app_installation_token():
    """Regression (CodeRabbit, PR #136): GitHub's 2026 stateless rollout for
    ghs_ installation tokens embeds a JWT after the prefix, so the token can
    contain dots — the legacy [A-Za-z0-9]{36,} character class stops at the
    first dot and lets this format through."""
    token = "ghs_APPID_" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20
    result = redact_sensitive_text(f"installation token {token} expired")
    assert token not in result
    assert "[REDACTED]" in result


def test_redacts_an_aws_access_key_id():
    result = redact_sensitive_text("credentials rejected: AKIAABCDEFGHIJ1234K5")
    assert "AKIAABCDEFGHIJ1234K5" not in result
    assert "[REDACTED]" in result


def test_leaves_ordinary_prose_completely_unchanged():
    text = "1. Article A — https://example.com/a\n2. Article B — https://example.com/b"
    assert redact_sensitive_text(text) == text


def test_empty_text_passes_through_unchanged():
    assert redact_sensitive_text("") == ""
