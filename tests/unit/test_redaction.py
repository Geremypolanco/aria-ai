"""Feature test: apps/core/safety/redaction.py closes the gap CodeRabbit
flagged on PR #131 — AITrace's tool_args/raw_observation fields were bounded
for size but never checked for sensitivity, so a real secret passed as a
tool argument (an API key, a password) would be persisted and broadcast to
the admin_activity feed verbatim within that bound.

Scoped to tool_args only (a dict, so keys are well-defined) — free-text
raw_observation would need pattern-based scrubbing, a harder, separate
problem intentionally left as open follow-up (see redaction.py's docstring).
"""

from __future__ import annotations

from apps.core.safety.redaction import redact_sensitive_args


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
