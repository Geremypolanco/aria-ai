"""Regression test: _bwrap_path() must not just check that the `bwrap`
binary exists — it must verify bwrap can actually create unprivileged
namespaces in the current runtime. Some container platforms block
unshare(CLONE_NEWUSER) via seccomp/AppArmor even when the bwrap binary is
present, in which case every invocation would fail with "Creating new
namespace failed: Operation not permitted". Without this probe, CodeRunner
would treat that as a real error and refuse to run code at all — worse
than falling back to unsandboxed execution.
"""

from __future__ import annotations

import os
import stat
import textwrap

import apps.core.tools.code_runner as code_runner_module
from apps.core.tools.code_runner import CodeRunner


def _write_fake_binary(path: str, script: str) -> None:
    with open(path, "w") as f:
        f.write(script)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


def test_bwrap_path_returns_none_when_binary_present_but_unusable(tmp_path, monkeypatch):
    fake_bwrap = tmp_path / "bwrap"
    _write_fake_binary(
        str(fake_bwrap),
        textwrap.dedent(
            """\
            #!/bin/sh
            echo "bwrap: Creating new namespace failed: Operation not permitted" >&2
            exit 1
            """
        ),
    )

    monkeypatch.setattr("shutil.which", lambda name: str(fake_bwrap) if name == "bwrap" else None)
    if hasattr(code_runner_module._bwrap_path, "_cached"):
        del code_runner_module._bwrap_path._cached

    assert code_runner_module._bwrap_path() is None


async def _run_and_get_result():
    runner = CodeRunner()
    return await runner.run("print('still works')", language="python")


def test_code_still_executes_when_bwrap_binary_is_broken(tmp_path, monkeypatch):
    import asyncio

    fake_bwrap = tmp_path / "bwrap"
    _write_fake_binary(
        str(fake_bwrap),
        textwrap.dedent(
            """\
            #!/bin/sh
            exit 1
            """
        ),
    )

    monkeypatch.setattr("shutil.which", lambda name: str(fake_bwrap) if name == "bwrap" else None)
    if hasattr(code_runner_module._bwrap_path, "_cached"):
        del code_runner_module._bwrap_path._cached

    result = asyncio.run(_run_and_get_result())

    assert result["success"] is True
    assert "still works" in result["stdout"]
    assert result["sandboxed"] is False

    # Clean up the cache so later tests see the real environment's bwrap again.
    if hasattr(code_runner_module._bwrap_path, "_cached"):
        del code_runner_module._bwrap_path._cached
