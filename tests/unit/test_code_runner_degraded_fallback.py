"""Regression test: when bubblewrap isn't installed, CodeRunner must still
work — falling back to direct execution (still with the minimal env and
real ulimit resource limits, just without namespace isolation) rather than
failing outright. The result must report sandboxed: False so this is
observable instead of silently claiming isolation that wasn't applied.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.core.tools.code_runner import CodeRunner

pytestmark = pytest.mark.asyncio


async def test_run_still_works_when_bwrap_is_unavailable():
    runner = CodeRunner()
    with patch("apps.core.tools.code_runner._bwrap_path", return_value=None):
        result = await runner.run("print('degraded mode works')", language="python")

    assert result["success"] is True
    assert "degraded mode works" in result["stdout"]
    assert result["sandboxed"] is False


async def test_resource_limits_still_apply_when_bwrap_is_unavailable():
    runner = CodeRunner()
    code = (
        "try:\n"
        "    x = bytearray(2 * 1024 * 1024 * 1024)\n"
        "    print('ALLOCATED')\n"
        "except MemoryError:\n"
        "    print('BLOCKED')\n"
    )
    with patch("apps.core.tools.code_runner._bwrap_path", return_value=None):
        result = await runner.run(code, language="python", timeout=10)

    assert "ALLOCATED" not in result["stdout"]
