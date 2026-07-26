"""
redaction.py — centralized redaction policy for audit-trail tool_args and
raw_observation.

CodeRabbit (PR #131) flagged that AITrace's tool_args/raw_observation fields
(added to close a debugging gap — see tracer.py) are persisted and broadcast
verbatim once bounded for size, with no check for whether the payload itself
is sensitive. A tool's arguments can carry a real secret (an API key passed
through by the user, a password field on a login-automation tool) alongside
the genuinely useful debugging context (a search query, a product name, a
file path).

tool_args (a dict) is redacted by KEY NAME — value-pattern matching there
would be far more failure-prone in both directions than the well-understood,
low-risk technique most production logging frameworks already use for this
(e.g. Sentry's default PII scrubbing).

raw_observation is free text with no keys to match on, so redact_sensitive_
text() instead matches a short list of HIGH-CONFIDENCE secret formats —
provider-specific prefixes (sk-, ghp_, xox[baprs]-, AKIA...) and structural
patterns (a Bearer header, a JWT's three dot-separated segments) that almost
never occur in ordinary prose. Deliberately NOT a general-purpose secret
scanner: no generic high-entropy-string heuristic, which is exactly the
speculative, false-positive-prone approach this module's tool_args redaction
already rejected for the same reason. A tool observation that happens to
embed a secret in some other, less recognizable format still gets through —
this closes the common, verifiable cases, not every conceivable one.
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

# Ordered so more specific patterns (JWT, Bearer header) are tried before
# anything that could coincidentally overlap with a broader one.
_SECRET_TEXT_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9\-_.]{20,}"),  # Authorization: Bearer <token>
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),  # JWT
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),  # OpenAI/Anthropic-style API key
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"),  # GitHub personal/OAuth/app token
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]+"),  # Slack token
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key ID
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),  # Google API key
    re.compile(r"\b[sr]k_(?:live|test)_[0-9A-Za-z]{16,}"),  # Stripe key
)


def redact_sensitive_text(text: str) -> str:
    """Replaces any high-confidence secret-shaped substring in free text
    with REDACTED. Safe to call on arbitrary text — returns it unchanged if
    nothing matches."""
    if not text:
        return text
    for pattern in _SECRET_TEXT_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


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
        # Recurse via _redact_value itself, not just for dict items — a
        # list can nest another list (e.g. {"batches": [[{"api_key": ...}]]}),
        # and a dict-only check here would let that inner list's dict through
        # unredacted since it's never itself a dict at this level.
        return [_redact_value("", item) for item in value]
    return value
