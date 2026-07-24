"""Seeds a few ambitious starter R&D projects into ARIA's RDWing tracker.

This used to import a nonexistent `apps.core.agents.aria_orchestrator.AriaOrchestrator`
and would fail with ImportError on the first line — it never actually ran. RDWing
(apps/core/intelligence/rd_wing.py) is the real, now-live tracker (see aria_mind.py's
create_research_project/add_research_finding/list_research_projects tools).
"""

import logging

from apps.core.intelligence.rd_wing import get_rd_wing

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("start_rd_projects")


def main():
    rd = get_rd_wing()

    logger.info("Starting pioneering research projects...")

    rd.create_project(
        name="Liver Cancer Cure",
        goal=(
            "Develop a definitive, accessible cure for liver cancer, exploring gene "
            "therapies, immunotherapies, and nanotechnology."
        ),
        category="Medicine/Oncology",
    )

    rd.create_project(
        name="AI-Humanity Biological Chip",
        goal=(
            "Research and develop brain-computer interfaces (BCI) and biological chips "
            "that enable a safe, ethical symbiosis between AI and human consciousness."
        ),
        category="Biotechnology/Neurotechnology",
    )

    rd.create_project(
        name="Total Solar Energy",
        goal=(
            "Develop innovative technologies to capture, store, and distribute 100% of "
            "available solar energy, including advanced photovoltaic materials and "
            "large-scale energy storage systems."
        ),
        category="Energy/Sustainability",
    )

    logger.info("Research projects started successfully.")


if __name__ == "__main__":
    main()
