import json
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger("aria.rd_wing")


class ResearchProject:
    def __init__(
        self,
        name: str,
        goal: str,
        category: str,
        status: str = "active",
        created_at: str | None = None,
    ):
        self.name = name
        self.goal = goal
        self.category = category
        self.status = status
        self.created_at = created_at or datetime.now().isoformat()
        self.findings: list[dict[str, Any]] = []

    def add_finding(self, title: str, content: str, source: str, timestamp: str | None = None):
        finding = {
            "title": title,
            "content": content,
            "source": source,
            "timestamp": timestamp or datetime.now().isoformat(),
        }
        self.findings.append(finding)
        logger.info(f"Finding added to project '{self.name}': {title}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "goal": self.goal,
            "category": self.category,
            "status": self.status,
            "created_at": self.created_at,
            "findings": self.findings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchProject":
        project = cls(
            data["name"], data["goal"], data["category"], data["status"], data["created_at"]
        )
        project.findings = data.get("findings", [])
        return project


class RDWing:
    """Aria's Research and Development Wing.
    Manages research projects, organizes findings, and collaborates with the ResearchAgent.
    """

    def __init__(self, storage_path: str = "./aria_rd_projects"):
        self.storage_path = storage_path
        os.makedirs(self.storage_path, exist_ok=True)
        self.projects: dict[str, ResearchProject] = self._load_projects()
        logger.info(f"RDWing initialized. {len(self.projects)} projects loaded.")

    def _project_file_path(self, project_name: str) -> str:
        return os.path.join(self.storage_path, f"{project_name.replace(' ', '_').lower()}.json")

    def _load_projects(self) -> dict[str, ResearchProject]:
        loaded_projects = {}
        for filename in os.listdir(self.storage_path):
            if filename.endswith(".json"):
                filepath = os.path.join(self.storage_path, filename)
                try:
                    with open(filepath, encoding="utf-8") as f:
                        data = json.load(f)
                        project = ResearchProject.from_dict(data)
                        loaded_projects[project.name] = project
                except Exception as e:
                    logger.error(f"Error loading project {filename}: {e}")
        return loaded_projects

    def _save_project(self, project: ResearchProject):
        filepath = self._project_file_path(project.name)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(project.to_dict(), f, indent=4)
        logger.info(f"Project '{project.name}' saved.")

    def create_project(self, name: str, goal: str, category: str) -> ResearchProject:
        if name in self.projects:
            logger.warning(f"Project '{name}' already exists.")
            return self.projects[name]
        project = ResearchProject(name, goal, category)
        self.projects[name] = project
        self._save_project(project)
        logger.info(f"New R&D project created: '{name}' in category '{category}'.")
        return project

    def get_project(self, name: str) -> ResearchProject | None:
        return self.projects.get(name)

    def add_finding_to_project(self, project_name: str, title: str, content: str, source: str):
        project = self.get_project(project_name)
        if project:
            project.add_finding(title, content, source)
            self._save_project(project)
        else:
            logger.error(f"Project '{project_name}' not found to add finding.")

    def list_projects(self) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self.projects.values()]

    def categorize_finding(self, finding_content: str) -> str:
        """Simulates categorization of a finding (in a real system, this would use an LLM).
        Note: the matched keywords below are intentionally left as-is (Spanish/English mix)
        since they are data used to match incoming finding content, not prose.
        """
        if "cáncer" in finding_content.lower() or "tumor" in finding_content.lower():
            return "Medicine/Oncology"
        if (
            "chip" in finding_content.lower()
            or "neural" in finding_content.lower()
            or "interfaz" in finding_content.lower()
        ):
            return "Biotechnology/Neurotechnology"
        if (
            "solar" in finding_content.lower()
            or "fotovoltaica" in finding_content.lower()
            or "energía" in finding_content.lower()
        ):
            return "Energy/Sustainability"
        return "General/Innovation"


# ── SINGLETON ─────────────────────────────────────────────
_rd_wing: RDWing | None = None


def get_rd_wing() -> RDWing:
    global _rd_wing
    if _rd_wing is None:
        _rd_wing = RDWing()
    return _rd_wing
