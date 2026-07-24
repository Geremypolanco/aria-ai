"""Regression test: CodeRunner._install_packages() used to run
`pip install <packages>` with no --target, writing straight into the same
site-packages the ARIA server process itself imports from. That meant:
(a) a sandboxed execution could silently shadow/break a dependency the
server relies on, and (b) installed packages persisted across executions
instead of being ephemeral like the rest of the sandbox — one execution's
installed package would be visible to unrelated later executions. Now
installs into an ephemeral --target directory inside that execution's own
workdir and wires it in via PYTHONPATH, so it never touches the server's
real site-packages and is deleted with the rest of the workdir afterward.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.tools.code_runner import CodeRunner

pytestmark = pytest.mark.asyncio


async def test_install_packages_targets_an_ephemeral_dir_not_global_site_packages(tmp_path):
    runner = CodeRunner()
    workdir = str(tmp_path)

    captured = {}

    async def fake_exec(cmd, timeout, cwd=None, network=False, extra_env=None):
        captured["cmd"] = cmd
        captured["network"] = network
        captured["cwd"] = cwd
        return {"success": True, "stdout": "", "stderr": "", "exit_code": 0, "sandboxed": True}

    with patch.object(runner, "_exec", fake_exec):
        site_dir = await runner._install_packages(["requests"], workdir)

    assert site_dir is not None
    assert site_dir.startswith(workdir)
    assert "--target" in captured["cmd"]
    target_idx = captured["cmd"].index("--target")
    assert captured["cmd"][target_idx + 1] == site_dir
    assert captured["network"] is True


async def test_run_python_wires_installed_packages_into_pythonpath():
    runner = CodeRunner()

    captured = {}

    async def fake_install_packages(packages, workdir):
        return f"{workdir}/site-packages"

    async def fake_exec(cmd, timeout, cwd=None, network=False, extra_env=None):
        captured["extra_env"] = extra_env
        return {"success": True, "stdout": "", "stderr": "", "exit_code": 0, "sandboxed": True}

    with patch.object(runner, "_install_packages", fake_install_packages), patch.object(
        runner, "_exec", fake_exec
    ):
        await runner._run_python("print(1)", timeout=5, packages=["requests"])

    assert "PYTHONPATH" in captured["extra_env"]
    assert captured["extra_env"]["PYTHONPATH"].endswith("site-packages")
