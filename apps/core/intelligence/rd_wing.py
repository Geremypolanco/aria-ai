import logging
import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("aria.rd_wing")

class ResearchProject:
    def __init__(self, name: str, goal: str, category: str, status: str = "active", created_at: Optional[str] = None):
        self.name = name
        self.goal = goal
        self.category = category
        self.status = status
        self.created_at = created_at or datetime.now().isoformat()
        self.findings: List[Dict[str, Any]] = []

    def add_finding(self, title: str, content: str, source: str, timestamp: Optional[str] = None):
        finding = {
            "title": title,
            "content": content,
            "source": source,
            "timestamp": timestamp or datetime.now().isoformat()
        }
        self.findings.append(finding)
        logger.info(f"Hallazgo añadido al proyecto '{self.name}': {title}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "goal": self.goal,
            "category": self.category,
            "status": self.status,
            "created_at": self.created_at,
            "findings": self.findings
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResearchProject":
        project = cls(data["name"], data["goal"], data["category"], data["status"], data["created_at"])
        project.findings = data.get("findings", [])
        return project

class RDWing:
    """Ala de Investigación y Desarrollo de Aria.
    Gestiona proyectos de investigación, organiza hallazgos y colabora con el ResearchAgent.
    """
    
    def __init__(self, storage_path: str = "./aria_rd_projects"):
        self.storage_path = storage_path
        os.makedirs(self.storage_path, exist_ok=True)
        self.projects: Dict[str, ResearchProject] = self._load_projects()
        logger.info(f"RDWing inicializado. {len(self.projects)} proyectos cargados.")

    def _project_file_path(self, project_name: str) -> str:
        return os.path.join(self.storage_path, f"{project_name.replace(' ', '_').lower()}.json")

    def _load_projects(self) -> Dict[str, ResearchProject]:
        loaded_projects = {}
        for filename in os.listdir(self.storage_path):
            if filename.endswith(".json"):
                filepath = os.path.join(self.storage_path, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        project = ResearchProject.from_dict(data)
                        loaded_projects[project.name] = project
                except Exception as e:
                    logger.error(f"Error cargando proyecto {filename}: {e}")
        return loaded_projects

    def _save_project(self, project: ResearchProject):
        filepath = self._project_file_path(project.name)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(project.to_dict(), f, indent=4)
        logger.info(f"Proyecto '{project.name}' guardado.")

    def create_project(self, name: str, goal: str, category: str) -> ResearchProject:
        if name in self.projects:
            logger.warning(f"El proyecto '{name}' ya existe.")
            return self.projects[name]
        project = ResearchProject(name, goal, category)
        self.projects[name] = project
        self._save_project(project)
        logger.info(f"Nuevo proyecto de I+D creado: '{name}' en categoría '{category}'.")
        return project

    def get_project(self, name: str) -> Optional[ResearchProject]:
        return self.projects.get(name)

    def add_finding_to_project(self, project_name: str, title: str, content: str, source: str):
        project = self.get_project(project_name)
        if project:
            project.add_finding(title, content, source)
            self._save_project(project)
        else:
            logger.error(f"Proyecto '{project_name}' no encontrado para añadir hallazgo.")

    def list_projects(self) -> List[Dict[str, Any]]:
        return [p.to_dict() for p in self.projects.values()]

    def categorize_finding(self, finding_content: str) -> str:
        """Simula la categorización de un hallazgo (en un sistema real, usaría LLM)."""
        if "cáncer" in finding_content.lower() or "tumor" in finding_content.lower():
            return "Medicina/Oncología"
        if "chip" in finding_content.lower() or "neural" in finding_content.lower() or "interfaz" in finding_content.lower():
            return "Biotecnología/Neurotecnología"
        if "solar" in finding_content.lower() or "fotovoltaica" in finding_content.lower() or "energía" in finding_content.lower():
            return "Energía/Sostenibilidad"
        return "General/Innovación"

# Integrar en el orquestador y el ResearchAgent
# Ejemplo de uso:
# rd_wing = RDWing()
# project = rd_wing.create_project("Cura Cáncer Hígado", "Desarrollar una cura definitiva para el cáncer de hígado.", "Medicina")
# rd_wing.add_finding_to_project(project.name, "Nuevo compuesto X muestra promesa", "Nature Medicine", "Estudio de fase II.")
