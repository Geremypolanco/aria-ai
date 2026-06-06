import asyncio
import logging
from apps.core.agents.aria_orchestrator import AriaOrchestrator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("start_rd_projects")

async def main():
    orchestrator = AriaOrchestrator()
    
    logger.info("Iniciando proyectos de investigación pioneros...")

    # Proyecto 1: Cura para el cáncer de hígado
    orchestrator.create_research_project(
        name="Cura Cáncer de Hígado",
        goal="Desarrollar una cura definitiva y accesible para el cáncer de hígado, explorando terapias genéticas, inmunoterapias y nanotecnología.",
        category="Medicina/Oncología"
    )

    # Proyecto 2: Chip biológico para integrar la IA con la humanidad
    orchestrator.create_research_project(
        name="Chip Biológico IA-Humanidad",
        goal="Investigar y desarrollar interfaces cerebro-computadora (BCI) y chips biológicos que permitan una simbiosis segura y ética entre la IA y la conciencia humana.",
        category="Biotecnología/Neurotecnología"
    )

    # Proyecto 3: Investigación para aprovechar toda la energía solar
    orchestrator.create_research_project(
        name="Energía Solar Total",
        goal="Desarrollar tecnologías innovadoras para capturar, almacenar y distribuir el 100% de la energía solar disponible, incluyendo materiales fotovoltaicos avanzados y sistemas de almacenamiento de energía a gran escala.",
        category="Energía/Sostenibilidad"
    )
    
    logger.info("Proyectos de investigación iniciados con éxito.")

if __name__ == "__main__":
    asyncio.run(main())
