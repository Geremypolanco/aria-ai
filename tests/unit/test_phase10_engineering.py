"""
Phase 10 tests — Engineering Division.

Covers:
  - EngineeringDivision: frontend_task, backend_task, mlops_task,
    api_integration_task, qa_task, automation_task
  - execute_sprint: multi-task execution
  - engineering_stats: aggregate statistics
  - recent_tasks: list retrieval
  - task_by_id: lookup by ID
  - WorkTask: dataclass contract
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ── Shared mock helpers ────────────────────────────────────────────────────────

_RICH_CONTENT = "def component(): pass\n" * 50  # 250 words — enough for quality score


def _mock_cache():
    """In-memory cache mock — get returns None, set returns True."""
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content: str = _RICH_CONTENT):
    """Sync AI client mock whose .complete() is async."""
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


def _mock_ai_failed():
    """AI client mock that always returns a failed response."""
    ai = MagicMock()
    r = MagicMock()
    r.success = False
    r.content = ""
    ai.complete = AsyncMock(return_value=r)
    return ai


# ══════════════════════════════════════════════════════════════════════════════
# WorkTask dataclass
# ══════════════════════════════════════════════════════════════════════════════

class TestWorkTask:
    """3 tests for the WorkTask dataclass."""

    def test_worktask_defaults(self):
        from apps.workforce.engineering.engineering_division import WorkTask
        t = WorkTask()
        assert t.task_id  # non-empty
        assert len(t.task_id) == 8
        assert t.status == "pending"
        assert t.quality_score == 0.0
        assert t.inputs == {}

    def test_worktask_to_dict_has_all_keys(self):
        from apps.workforce.engineering.engineering_division import WorkTask
        t = WorkTask(title="Test", task_type="frontend", agent_type="frontend_engineer")
        d = t.to_dict()
        for key in ("task_id", "task_type", "agent_type", "title", "inputs",
                    "output", "quality_score", "estimated_cost_usd",
                    "duration_ms", "status", "created_at"):
            assert key in d, f"Missing key: {key}"

    def test_worktask_to_dict_values_match(self):
        from apps.workforce.engineering.engineering_division import WorkTask
        t = WorkTask(title="MyTask", task_type="backend", status="done")
        d = t.to_dict()
        assert d["title"] == "MyTask"
        assert d["task_type"] == "backend"
        assert d["status"] == "done"


# ══════════════════════════════════════════════════════════════════════════════
# EngineeringDivision — frontend_task
# ══════════════════════════════════════════════════════════════════════════════

class TestFrontendTask:
    """4 tests for frontend_task."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        import apps.workforce.engineering.engineering_division as m
        m._instance = None
        with patch("apps.workforce.engineering.engineering_division.get_cache", return_value=_mock_cache()), \
             patch("apps.workforce.engineering.engineering_division.get_ai_client", return_value=_mock_ai()):
            yield
        m._instance = None

    async def test_frontend_task_returns_worktask(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.frontend_task("Button Component", {"type": "button", "variant": "primary"})
        assert wt is not None
        assert wt.task_id

    async def test_frontend_task_status_done(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.frontend_task("Header", {"nav": True})
        assert wt.status == "done"

    async def test_frontend_task_output_non_empty(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.frontend_task("Card", {"image": True})
        assert wt.output
        assert len(wt.output) > 0

    async def test_frontend_task_quality_score_in_range(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.frontend_task("Modal", {"closeable": True})
        assert 0.0 <= wt.quality_score <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# EngineeringDivision — backend_task
# ══════════════════════════════════════════════════════════════════════════════

class TestBackendTask:
    """4 tests for backend_task."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        import apps.workforce.engineering.engineering_division as m
        m._instance = None
        with patch("apps.workforce.engineering.engineering_division.get_cache", return_value=_mock_cache()), \
             patch("apps.workforce.engineering.engineering_division.get_ai_client", return_value=_mock_ai()):
            yield
        m._instance = None

    async def test_backend_task_returns_worktask(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.backend_task("User endpoint", {"method": "POST", "path": "/users"})
        assert wt.task_id

    async def test_backend_task_status_done(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.backend_task("Auth endpoint", {"method": "GET", "path": "/auth"})
        assert wt.status == "done"

    async def test_backend_task_output_non_empty(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.backend_task("Products API", {})
        assert wt.output

    async def test_backend_task_correct_agent_type(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.backend_task("Orders API", {})
        assert wt.agent_type == "backend_engineer"


# ══════════════════════════════════════════════════════════════════════════════
# EngineeringDivision — mlops_task
# ══════════════════════════════════════════════════════════════════════════════

class TestMlopsTask:
    """3 tests for mlops_task."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        import apps.workforce.engineering.engineering_division as m
        m._instance = None
        with patch("apps.workforce.engineering.engineering_division.get_cache", return_value=_mock_cache()), \
             patch("apps.workforce.engineering.engineering_division.get_ai_client", return_value=_mock_ai()):
            yield
        m._instance = None

    async def test_mlops_task_returns_worktask(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.mlops_task("Training Pipeline", {"model": "xgboost", "dataset": "s3://data"})
        assert wt.task_id
        assert wt.status == "done"

    async def test_mlops_task_output_non_empty(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.mlops_task("Deployment Config", {"cloud": "aws"})
        assert wt.output

    async def test_mlops_task_cost_estimate(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.mlops_task("Feature Store", {})
        assert wt.estimated_cost_usd == 0.05


# ══════════════════════════════════════════════════════════════════════════════
# EngineeringDivision — api_integration_task
# ══════════════════════════════════════════════════════════════════════════════

class TestApiIntegrationTask:
    """3 tests for api_integration_task."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        import apps.workforce.engineering.engineering_division as m
        m._instance = None
        with patch("apps.workforce.engineering.engineering_division.get_cache", return_value=_mock_cache()), \
             patch("apps.workforce.engineering.engineering_division.get_ai_client", return_value=_mock_ai()):
            yield
        m._instance = None

    async def test_api_integration_task_returns_worktask(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.api_integration_task("Stripe Integration", "Stripe", ["/charges", "/customers"])
        assert wt.task_id
        assert wt.status == "done"

    async def test_api_integration_task_inputs_stored(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.api_integration_task("Twilio", "Twilio", ["/messages"])
        assert "api_name" in wt.inputs
        assert wt.inputs["api_name"] == "Twilio"

    async def test_api_integration_task_quality_score(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.api_integration_task("GitHub API", "GitHub", ["/repos", "/issues"])
        assert 0.0 <= wt.quality_score <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# EngineeringDivision — qa_task
# ══════════════════════════════════════════════════════════════════════════════

class TestQaTask:
    """3 tests for qa_task."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        import apps.workforce.engineering.engineering_division as m
        m._instance = None
        with patch("apps.workforce.engineering.engineering_division.get_cache", return_value=_mock_cache()), \
             patch("apps.workforce.engineering.engineering_division.get_ai_client", return_value=_mock_ai()):
            yield
        m._instance = None

    async def test_qa_task_returns_worktask(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.qa_task("Test UserService", "class UserService:\n    def get(self, id): ...")
        assert wt.task_id
        assert wt.status == "done"

    async def test_qa_task_agent_type(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.qa_task("Test Auth", "def authenticate(token): ...")
        assert wt.agent_type == "qa_engineer"

    async def test_qa_task_cost_estimate(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.qa_task("Test Payment", "def charge(amount): ...")
        assert wt.estimated_cost_usd == 0.02


# ══════════════════════════════════════════════════════════════════════════════
# EngineeringDivision — automation_task
# ══════════════════════════════════════════════════════════════════════════════

class TestAutomationTask:
    """3 tests for automation_task."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        import apps.workforce.engineering.engineering_division as m
        m._instance = None
        with patch("apps.workforce.engineering.engineering_division.get_cache", return_value=_mock_cache()), \
             patch("apps.workforce.engineering.engineering_division.get_ai_client", return_value=_mock_ai()):
            yield
        m._instance = None

    async def test_automation_task_returns_worktask(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.automation_task("Deploy Script", {"steps": ["build", "test", "push"]})
        assert wt.task_id
        assert wt.status == "done"

    async def test_automation_task_output_non_empty(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.automation_task("CI Pipeline", {"trigger": "push"})
        assert wt.output

    async def test_automation_task_correct_agent_type(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.automation_task("Backup Script", {"schedule": "daily"})
        assert wt.agent_type == "automation_engineer"


# ══════════════════════════════════════════════════════════════════════════════
# EngineeringDivision — execute_sprint
# ══════════════════════════════════════════════════════════════════════════════

class TestExecuteSprint:
    """4 tests for execute_sprint."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        import apps.workforce.engineering.engineering_division as m
        m._instance = None
        with patch("apps.workforce.engineering.engineering_division.get_cache", return_value=_mock_cache()), \
             patch("apps.workforce.engineering.engineering_division.get_ai_client", return_value=_mock_ai()):
            yield
        m._instance = None

    async def test_execute_sprint_returns_list(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        tasks = [
            {"type": "frontend", "title": "Navbar", "spec": {}},
            {"type": "backend", "title": "API", "spec": {}},
        ]
        results = await div.execute_sprint(tasks)
        assert isinstance(results, list)
        assert len(results) == 2

    async def test_execute_sprint_all_have_task_ids(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        tasks = [
            {"type": "qa", "title": "Tests", "code_to_test": "def f(): pass"},
            {"type": "automation", "title": "Script", "workflow": {}},
        ]
        results = await div.execute_sprint(tasks)
        for wt in results:
            assert wt.task_id

    async def test_execute_sprint_empty_list(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        results = await div.execute_sprint([])
        assert results == []

    async def test_execute_sprint_unknown_type_marks_failed(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        tasks = [{"type": "unknown_type", "title": "Bad task"}]
        results = await div.execute_sprint(tasks)
        assert len(results) == 1
        assert results[0].status == "failed"


# ══════════════════════════════════════════════════════════════════════════════
# EngineeringDivision — stats and queries
# ══════════════════════════════════════════════════════════════════════════════

class TestEngineeringStats:
    """5 tests for engineering_stats, recent_tasks, task_by_id."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        import apps.workforce.engineering.engineering_division as m
        m._instance = None
        with patch("apps.workforce.engineering.engineering_division.get_cache", return_value=_mock_cache()), \
             patch("apps.workforce.engineering.engineering_division.get_ai_client", return_value=_mock_ai()):
            yield
        m._instance = None

    async def test_engineering_stats_has_required_keys(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        await div.frontend_task("Comp", {})
        stats = div.engineering_stats()
        assert "total_tasks" in stats
        assert "by_agent_type" in stats
        assert "avg_quality_score" in stats
        assert "total_cost_usd" in stats

    async def test_engineering_stats_counts_tasks(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        await div.frontend_task("A", {})
        await div.backend_task("B", {})
        stats = div.engineering_stats()
        assert stats["total_tasks"] == 2

    def test_engineering_stats_empty_division(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        stats = div.engineering_stats()
        assert stats["total_tasks"] == 0
        assert stats["avg_quality_score"] == 0.0

    async def test_recent_tasks_returns_list(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        await div.backend_task("API", {})
        recent = div.recent_tasks(limit=5)
        assert isinstance(recent, list)
        assert len(recent) >= 1

    async def test_task_by_id_finds_task(self):
        from apps.workforce.engineering.engineering_division import EngineeringDivision
        div = EngineeringDivision()
        wt = await div.frontend_task("Searchable", {})
        found = div.task_by_id(wt.task_id)
        assert found is not None
        assert found["task_id"] == wt.task_id


# ══════════════════════════════════════════════════════════════════════════════
# Singleton
# ══════════════════════════════════════════════════════════════════════════════

class TestEngineeringSingleton:
    """2 tests for get_engineering_division singleton."""

    def test_singleton_returns_same_instance(self):
        import apps.workforce.engineering.engineering_division as m
        m._instance = None
        from apps.workforce.engineering.engineering_division import get_engineering_division
        a = get_engineering_division()
        b = get_engineering_division()
        assert a is b
        m._instance = None

    def test_singleton_is_engineering_division(self):
        import apps.workforce.engineering.engineering_division as m
        m._instance = None
        from apps.workforce.engineering.engineering_division import (
            EngineeringDivision, get_engineering_division
        )
        div = get_engineering_division()
        assert isinstance(div, EngineeringDivision)
        m._instance = None
