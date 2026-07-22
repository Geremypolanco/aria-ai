"""Regression test: three dead expression-statements in income_loop.py
computed a value (a filename slug, or a pricing sum) and immediately
discarded it — the result was never assigned to a variable or used
anywhere, in _exec_reddit_organic, _exec_tiktok_script, and
_exec_api_marketplace_lister. Harmless (no crash) but pure wasted
computation masking what looks like a forgotten `slug = ...` assignment.
Removed the dead statements; verified the surrounding logic doesn't
reference the would-be variable anywhere.
"""

from __future__ import annotations

import inspect

from apps.core.tools.income_loop import IncomeLoop


def test_reddit_organic_has_no_dead_slug_expression():
    source = inspect.getsource(IncomeLoop._exec_reddit_organic)
    assert 'replace("[", "")' not in source


def test_tiktok_script_has_no_dead_slug_expression():
    source = inspect.getsource(IncomeLoop._exec_tiktok_script)
    assert source.count("hook.lower()") == 0


def test_api_marketplace_lister_has_no_dead_sum_expression():
    source = inspect.getsource(IncomeLoop._exec_api_marketplace_lister)
    assert "non-free tiers" not in source
