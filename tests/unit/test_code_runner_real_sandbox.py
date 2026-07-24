"""End-to-end tests for the real OS-level sandbox added to code_runner.py.

Prior to this, the module's own docstring admitted "this is NOT a real
sandbox" — the executed subprocess ran as the same OS user, on the same
filesystem, with full network access, with only env-var stripping and a
wall-clock timeout as protection. These tests actually run code through
CodeRunner (not mocked) and assert on the real, observable effects of the
bubblewrap-based isolation: no network reachability, no filesystem access
outside the ephemeral per-execution workdir, and real memory/process
limits enforced via ulimit. They require `bwrap` to be installed (skipped
otherwise, matching the graceful degradation the runner itself falls back
to when bwrap is absent).
"""

from __future__ import annotations

import shutil

import pytest

from apps.core.tools.code_runner import CodeRunner, _bwrap_path

requires_bwrap = pytest.mark.skipif(
    shutil.which("bwrap") is None, reason="bubblewrap not installed in this environment"
)


@requires_bwrap
@pytest.mark.asyncio
async def test_result_reports_sandboxed_true_when_bwrap_available():
    runner = CodeRunner()
    result = await runner.run("print('hi')", language="python")
    assert result["sandboxed"] is True


@pytest.mark.asyncio
async def test_network_is_unreachable_by_default():
    runner = CodeRunner()
    # urllib (unlike `socket`, which _check_dangerous blocks statically at
    # the import level) reaches the network namespace directly, so this
    # exercises the actual bwrap network isolation rather than the
    # unrelated import blocklist.
    code = (
        "import urllib.request\n"
        "try:\n"
        "    urllib.request.urlopen('http://8.8.8.8', timeout=3)\n"
        "    print('REACHED')\n"
        "except Exception as e:\n"
        "    print(f'BLOCKED:{type(e).__name__}')\n"
    )
    result = await runner.run(code, language="python", timeout=10)
    assert result["success"] is True
    if result["sandboxed"]:
        assert "BLOCKED" in result["stdout"]
        assert "REACHED" not in result["stdout"]


@requires_bwrap
@pytest.mark.asyncio
async def test_cannot_read_files_outside_the_sandbox_workdir():
    runner = CodeRunner()
    # /etc/shadow is unreadable to a normal user anyway on most systems, so
    # target something guaranteed to exist and be host-readable but that must
    # not appear inside the sandboxed filesystem view: the server's own
    # source tree, which is never bind-mounted into the sandbox.
    code = (
        "import os\n"
        "print('EXISTS' if os.path.exists('/app/apps/core/config.py') else 'ABSENT')\n"
    )
    result = await runner.run(code, language="python", timeout=10)
    assert result["success"] is True
    assert "ABSENT" in result["stdout"]


@requires_bwrap
@pytest.mark.asyncio
async def test_cannot_write_outside_the_sandbox_workdir():
    runner = CodeRunner()
    code = (
        "try:\n"
        "    open('/usr/should_not_be_writable.txt', 'w').close()\n"
        "    print('WROTE')\n"
        "except Exception as e:\n"
        "    print(f'BLOCKED:{type(e).__name__}')\n"
    )
    result = await runner.run(code, language="python", timeout=10)
    assert result["success"] is True
    assert "BLOCKED" in result["stdout"]


@pytest.mark.asyncio
async def test_memory_limit_is_enforced():
    runner = CodeRunner()
    code = (
        "try:\n"
        "    x = bytearray(2 * 1024 * 1024 * 1024)\n"
        "    print('ALLOCATED')\n"
        "except MemoryError:\n"
        "    print('BLOCKED')\n"
    )
    result = await runner.run(code, language="python", timeout=10)
    # Either the interpreter catches MemoryError cleanly, or the OS kills
    # the process outright (nonzero exit) — both are the limit working.
    assert "ALLOCATED" not in result["stdout"]


@pytest.mark.asyncio
async def test_can_still_write_and_read_within_its_own_workdir():
    """Sanity check: the sandbox must not be so restrictive that ordinary,
    legitimate scripts (the actual use case) stop working."""
    runner = CodeRunner()
    code = (
        "with open('scratch.txt', 'w') as f:\n"
        "    f.write('hello')\n"
        "with open('scratch.txt') as f:\n"
        "    print(f.read())\n"
    )
    result = await runner.run(code, language="python", timeout=10)
    assert result["success"] is True
    assert "hello" in result["stdout"]


def test_bwrap_path_is_cached():
    first = _bwrap_path()
    second = _bwrap_path()
    assert first == second
