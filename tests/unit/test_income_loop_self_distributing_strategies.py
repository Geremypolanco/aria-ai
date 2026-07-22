"""Regression test: _SELF_DISTRIBUTING_STRATEGIES listed "github_blog", but
no strategy is ever named that — the real dispatched strategy name is
"github_publish" (STRATEGIES entry, _execute()'s dispatch, and
_exec_github_publish() itself, which does announce on Twitter after
publishing to GitHub). Since "github_blog" never matches result.strategy,
the set entry was dead, and — more importantly — "github_publish" was NOT
actually in the skip-list, so the global social-distribution fallback in
run_cycle() would fire a SECOND, duplicate social post for every successful
github_publish cycle on top of the one _exec_github_publish already sent.
"""

from __future__ import annotations

from apps.core.tools.income_loop import _SELF_DISTRIBUTING_STRATEGIES


def test_github_publish_is_in_self_distributing_strategies():
    assert "github_publish" in _SELF_DISTRIBUTING_STRATEGIES
    assert "github_blog" not in _SELF_DISTRIBUTING_STRATEGIES
