"""Regression test: income_loop.py referenced two settings fields under the
WRONG name, where a correctly-named field already existed for the same
purpose elsewhere in the codebase:

1. TWITTER_ACCESS_SECRET -> real field is TWITTER_ACCESS_TOKEN_SECRET
   (config.py). getattr's 3-arg default silently swallowed the mismatch,
   so the direct-Twitter-API posting gate in _exec_content_amplifier could
   never pass even with all 4 real Twitter credentials configured.
2. SENDGRID_FROM_EMAIL -> real field is EMAIL_FROM. The from-address
   override could never be configured; every cold/upsell email silently
   used the hardcoded default sender instead.
"""

from __future__ import annotations

from apps.core.tools import income_loop


def test_income_loop_no_longer_references_wrong_field_names():
    source = income_loop.__file__
    with open(source) as f:
        text = f.read()

    assert "TWITTER_ACCESS_SECRET" not in text
    assert "SENDGRID_FROM_EMAIL" not in text
    assert "TWITTER_ACCESS_TOKEN_SECRET" in text
    assert 'getattr(settings, "EMAIL_FROM"' in text
