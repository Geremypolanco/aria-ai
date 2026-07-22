"""Regression test: MetaMarketingTools hardcoded Meta Graph/Marketing API
v19.0, deprecated 2026-06-09 (all versions prior to v24.0 were sunset on
that date; current version is v25.0 as of the 2026-02-18 release). Every
call in this file was targeting an already-retired API version.
"""

from __future__ import annotations

from apps.core.tools import marketing_tools


def test_marketing_tools_does_not_use_deprecated_api_version():
    with open(marketing_tools.__file__) as f:
        text = f.read()

    assert "v19.0" not in text
    assert "graph.facebook.com/v25.0" in text
