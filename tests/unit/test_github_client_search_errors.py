"""Regression test: github_dispatch(action="search", type="code"|"issues")
swallowed API errors. gh.search_code()/search_issues() return {"error": ...}
on a failed call (403 rate-limited, 422 malformed query, network exception),
but the code|issues branches went straight to `data.get("items", [])` without
checking for an "error" key first — unlike the "repos" branch just below,
which does check. That silently turned real errors into a misleading
"Sin resultados." (no results) message instead of surfacing the failure.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from apps.core.tools.github_client import github_dispatch

pytestmark = pytest.mark.asyncio


async def test_search_code_surfaces_error_instead_of_no_results():
    with patch(
        "apps.core.tools.github_client.AriaGitHubClient.search_code",
        AsyncMock(return_value={"error": "Acceso denegado (403) — verifica GITHUB_TOKEN"}),
    ):
        result = await github_dispatch("search", {"query": "foo", "type": "code"})
    assert "Error:" in result
    assert "Sin resultados" not in result


async def test_search_issues_surfaces_error_instead_of_no_results():
    with patch(
        "apps.core.tools.github_client.AriaGitHubClient.search_issues",
        AsyncMock(return_value={"error": "Acceso denegado (403) — verifica GITHUB_TOKEN"}),
    ):
        result = await github_dispatch("search", {"query": "foo", "type": "issues"})
    assert "Error:" in result
    assert "Sin resultados" not in result
