"""Regression test: four near-identical HuggingFace Hub fallback blocks
(_exec_content_pipeline, _exec_niche_rotator, _exec_product_factory,
_exec_shopify_listing) created a HF repo/Space, then PUT the README.md
content but DISCARDED that PUT response — appending the URL and returning
"success": True unconditionally, regardless of whether the content upload
actually succeeded. If the repo/Space creation succeeded (200/201/409) but
the follow-up PUT failed (e.g. 401 read-only token, 413 too large, a
transient 5xx), the loop still reported a successful publish with a real
URL and a nonzero revenue_potential — feeding the Thompson bandit a false
positive and telling ARIA it published a product it did not.
"""

from __future__ import annotations

import inspect
import re

from apps.core.tools.income_loop import IncomeLoop

_METHODS = [
    "_exec_content_pipeline",
    "_exec_niche_rotator",
    "_exec_product_factory",
    "_exec_shopify_listing",
]


def test_hf_fallback_put_response_is_checked_before_reporting_success():
    for name in _METHODS:
        source = inspect.getsource(getattr(IncomeLoop, name))
        # Every PUT to a HF raw/main/README.md endpoint must have its
        # response captured into a variable (not just `await ...put(...)`)
        put_calls = re.findall(r"(\w+)\s*=\s*await \w+\.put\(\s*\n\s*f\"https://huggingface", source)
        assert put_calls, f"{name}: no captured HF PUT response found"
        for var in put_calls:
            assert f"{var}.status_code in (200, 201)" in source, (
                f"{name}: PUT response {var!r} is captured but never checked before success"
            )
