"""Regression test: SelfImprovementEngine.push_file()/push_improvement() only
checked file_path against PROTECTED_FILES (a 10-entry blacklist) — the
declared MODIFIABLE_FILES whitelist was never actually enforced. push_file()
is called from EvolutionAgent._implement_feature_code() with a file_path
taken directly from an LLM-generated JSON proposal
(proposal["file_to_create"]), so an untrusted/hallucinated path pointing at
e.g. .github/workflows/deploy.yml, docs/*, tests/*, or .env* would have been
written straight to the real GitHub repo — triggering a real CI/CD deploy
per this module's own docstring — since none of those paths were in the
small hardcoded blacklist.
"""

from __future__ import annotations

from apps.core.tools.self_improvement import SelfImprovementEngine


def test_writable_path_rejects_protected_files():
    engine = SelfImprovementEngine()
    assert engine._is_writable_path("apps/core/config.py") is False
    assert engine._is_writable_path("apps/core/main.py") is False


def test_writable_path_rejects_paths_outside_tools_and_agents():
    engine = SelfImprovementEngine()
    assert engine._is_writable_path(".github/workflows/deploy.yml") is False
    assert engine._is_writable_path("docs/README.md") is False
    assert engine._is_writable_path(".env") is False
    assert engine._is_writable_path("tests/unit/test_foo.py") is False


def test_writable_path_allows_declared_modifiable_files():
    engine = SelfImprovementEngine()
    for f in engine.MODIFIABLE_FILES:
        assert engine._is_writable_path(f) is True


def test_writable_path_allows_new_tool_and_agent_files():
    engine = SelfImprovementEngine()
    assert engine._is_writable_path("apps/core/tools/brand_new_feature.py") is True
    assert engine._is_writable_path("apps/core/agents/brand_new_agent.py") is True


def test_writable_path_rejects_non_python_files_under_tools():
    engine = SelfImprovementEngine()
    assert engine._is_writable_path("apps/core/tools/config.yaml") is False
