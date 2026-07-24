"""Regression test: RDWing (apps/core/intelligence/rd_wing.py) — a persistent,
cross-session research-project tracker — had a complete, working implementation
but was never reachable from anywhere in the live app. Its own trailing comment
said "Integrate into the orchestrator and the ResearchAgent" as an unfinished
TODO, and scripts/start_rd_projects.py (the only thing that tried to use it)
actually imported a nonexistent `apps.core.agents.aria_orchestrator.AriaOrchestrator`
and would ImportError on line 1 — it never ran.

Now wired into aria_mind.py's tool dispatcher as three real tools:
create_research_project, add_research_finding, list_research_projects. This
test exercises them through AriaMind._execute_tool exactly as a live
conversation would, not by calling RDWing directly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.core.intelligence.rd_wing import RDWing

pytestmark = pytest.mark.asyncio


@pytest.fixture
def rd_wing(tmp_path):
    return RDWing(storage_path=str(tmp_path / "rd_projects"))


async def test_create_research_project_reachable_from_tool_dispatch(rd_wing):
    with patch("apps.core.intelligence.rd_wing.get_rd_wing", return_value=rd_wing):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "create_research_project",
            {
                "name": "Liver Cancer Cure",
                "goal": "Develop a definitive cure for liver cancer.",
                "category": "Medicine/Oncology",
            },
        )

    assert media == {}
    assert "Liver Cancer Cure" in obs
    project = rd_wing.get_project("Liver Cancer Cure")
    assert project is not None
    assert project.category == "Medicine/Oncology"


async def test_create_research_project_requires_name_and_goal(rd_wing):
    with patch("apps.core.intelligence.rd_wing.get_rd_wing", return_value=rd_wing):
        mind = AriaMind()
        obs, media = await mind._execute_tool("create_research_project", {"name": "X"})

    assert media == {}
    assert "goal" in obs.lower()
    assert rd_wing.get_project("X") is None


async def test_add_research_finding_persists_on_existing_project(rd_wing):
    rd_wing.create_project("Total Solar Energy", "Capture 100% of available solar energy.", "Energy")
    with patch("apps.core.intelligence.rd_wing.get_rd_wing", return_value=rd_wing):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "add_research_finding",
            {
                "project": "Total Solar Energy",
                "title": "New perovskite cell hits 31% efficiency",
                "content": "Lab result from a partner university.",
                "source": "Nature Energy",
            },
        )

    assert media == {}
    assert "Total Solar Energy" in obs
    project = rd_wing.get_project("Total Solar Energy")
    assert len(project.findings) == 1
    assert project.findings[0]["title"] == "New perovskite cell hits 31% efficiency"


async def test_add_research_finding_rejects_unknown_project(rd_wing):
    with patch("apps.core.intelligence.rd_wing.get_rd_wing", return_value=rd_wing):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "add_research_finding",
            {"project": "Nonexistent", "title": "t", "content": "c"},
        )

    assert media == {}
    assert "No R&D project" in obs


async def test_list_research_projects_reflects_dispatcher_created_projects(rd_wing):
    with patch("apps.core.intelligence.rd_wing.get_rd_wing", return_value=rd_wing):
        mind = AriaMind()
        await mind._execute_tool(
            "create_research_project",
            {"name": "AI-Humanity Biological Chip", "goal": "BCI research.", "category": "Biotech"},
        )
        obs, media = await mind._execute_tool("list_research_projects", {})

    assert media == {}
    assert "AI-Humanity Biological Chip" in obs
    assert "Biotech" in obs


async def test_rd_wing_projects_survive_across_get_rd_wing_calls(tmp_path):
    """The 5-strikes-style bug class this session keeps finding: a fresh
    instance per call would silently lose state. get_rd_wing() must return
    the same singleton so a project created in one turn is still there in
    the next."""
    import apps.core.intelligence.rd_wing as rd_wing_module

    rd_wing_module._rd_wing = None
    with patch(
        "apps.core.intelligence.rd_wing.RDWing",
        side_effect=lambda storage_path="./aria_rd_projects": RDWing(str(tmp_path)),
    ):
        a = rd_wing_module.get_rd_wing()
        b = rd_wing_module.get_rd_wing()
        assert a is b
    rd_wing_module._rd_wing = None
