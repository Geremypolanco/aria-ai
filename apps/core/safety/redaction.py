"""
redaction.py — centralized redaction policy for audit-trail tool_args.

CodeRabbit (PR #131) flagged that AITrace's tool_args/raw_observation fields
(added to close a debugging gap — see tracer.py) are persisted and broadcast
verbatim once bounded for size, with no check for whether the payload itself
is sensitive. A tool's arguments can carry a real secret (an API key passed
through by the user, a password field on a login-automation tool) alongside
the genuinely useful debugging context (a search query, a product name, a
file path).

This module redacts by KEY NAME, not by scanning values for secret-looking
patterns: value-pattern matching (regex for "looks like an API key") is far
more failure-prone in both directions — it misses secrets in unusual formats
and mangles legitimate content that merely resembles one — where key-name
matching is a well-understood, low-risk technique already used by most
production logging frameworks (e.g. Sentry's default PII scrubbing) and
covers the concrete, verifiable case CodeRabbit's finding centered on: a
credential passed as a tool argument under a recognizable name.

Deliberately scoped to tool_args (a dict, so keys are well-defined) — free-
text raw_observation would need pattern-based scrubbing to redact anything,
which is exactly the harder, more speculative problem this module avoids by
design. That remains open follow-up work, tracked separately.
"""

from __future__ import annotations

REDACTED = "[REDACTED]"

# Substrings matched case-insensitively against dict keys — a key containing
# any of these anywhere in its name (e.g. "stripe_api_key", "auth_token",
# "db_password") gets its value replaced. Deliberately broad: a false
# positive here just redacts a harmless value that happened to be named
# similarly (e.g. "token_count"), which is a cosmetic loss; a false negative
# lets a real secret through the exact vector this module exists to close.
_SENSITIVE_KEY_SUBSTRINGS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "credential",
    "auth",
    "ssn",
    "social_security",
    "cvv",
    "cvc",
    "card_number",
    "cardnumber",
    "ccnum",
    "session_id",
    "cookie",
)


def _is_sensitive_key(key: str) -> bool:
    low = key.lower()
    return any(marker in low for marker in _SENSITIVE_KEY_SUBSTRINGS)


def redact_sensitive_args(args: dict | None) -> dict | None:
    """Returns a new dict with sensitive-looking values replaced by
    REDACTED, recursing into nested dicts/lists so a tool that nests its
    arguments (e.g. {"config": {"api_key": "..."}}) is still covered.
    Never mutates the input. None/empty input passes through unchanged."""
    if not args:
        return args
    return {k: _redact_value(k, v) for k, v in args.items()}


def _redact_value(key: str, value):
    if _is_sensitive_key(key):
        return REDACTED
    if isinstance(value, dict):
        return redact_sensitive_args(value)
    if isinstance(value, list):
        return [redact_sensitive_args(item) if isinstance(item, dict) else item for item in value]
    return value
