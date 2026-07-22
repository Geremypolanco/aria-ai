"""Regression test for a widespread bug class found across an 8-way parallel
audit of income_loop.py (22k lines): ~20 _exec_* methods computed a real
outcome-tracking variable (urls_created, distributed_to, published_channels,
pins_created, replies_sent, etc.) reflecting whether GitHub archiving,
social posting, or SMTP sending actually succeeded — then IGNORED it and
returned "success": True unconditionally. In an autonomous income loop,
this means a cycle where every underlying action failed (no GitHub commit,
no tweet, no email sent) was still recorded as a successful cycle with a
fabricated revenue_potential, feeding the Thompson bandit false positives
and never surfacing the real failure anywhere.

Rather than one test per method (20+ near-identical cases), this verifies
via source inspection that each affected method's final return statement
no longer hardcodes "success": True — it must reference a real tracking
variable instead.
"""

from __future__ import annotations

import inspect
import re

from apps.core.tools.income_loop import IncomeLoop

_METHODS = [
    "_exec_pinterest_pins",
    "_exec_cold_email_outreach",
    "_exec_youtube_strategy",
    "_exec_product_hunt_launch",
    "_exec_smart_pricing",
    "_exec_community_launch",
    "_exec_auto_responder",
    "_exec_seo_content_cluster",
    "_exec_price_anchoring",
    "_exec_social_proof_automation",
    "_exec_influencer_collab",
    "_exec_content_licensing",
    "_exec_micro_consulting",
    "_exec_saas_upsell_sequence",
    "_exec_community_monetize",
    "_exec_thought_leadership",
    "_exec_token_economy",
    "_exec_api_product_launch",
    "_exec_growth_experiment",
    "_exec_app_store_listing",
    "_exec_case_study_publisher",
]


def test_no_method_in_batch_hardcodes_unconditional_success():
    for name in _METHODS:
        source = inspect.getsource(getattr(IncomeLoop, name))
        # Every "return {...}" block inside the method must not contain a
        # bare `"success": True,` on its own line as the FINAL happy-path
        # return (the AI-failed early-return `"success": False` cases are
        # unaffected). We look at the last return block specifically.
        last_return_idx = source.rfind('return {\n                "success"')
        assert last_return_idx != -1, f"{name}: expected return block not found"
        tail = source[last_return_idx:]
        first_line_end = tail.index("\n")
        first_line = tail[:first_line_end]
        assert '"success": True,' not in first_line, (
            f"{name}: final return still hardcodes success=True unconditionally"
        )


def test_misleading_or_github_fallback_text_removed():
    """thought_leadership and case_study_publisher both used `or 'GitHub'` as
    the announced-channel fallback text, which asserted a GitHub publish
    succeeded even when it hadn't. Must no longer claim GitHub by default."""
    for name in ["_exec_thought_leadership", "_exec_case_study_publisher"]:
        source = inspect.getsource(getattr(IncomeLoop, name))
        assert re.search(r"or 'GitHub'", source) is None
