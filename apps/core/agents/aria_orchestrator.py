import logging
from typing import List, Dict, Any
from apps.core.integrations.gmail_engine import GmailEngine
from apps.core.integrations.shopify_engine import ShopifyEngine
from apps.core.integrations.linkedin_engine import LinkedInEngine
from apps.core.intelligence.universal_modules import UniversalAria
from apps.core.intelligence.ethics_engine import EthicsEngine, EthicalPrinciple
from apps.core.intelligence.sentiment_engine import SentimentEngine
from apps.core.intelligence.rd_wing import RDWing, ResearchProject
from apps.core.intelligence.evolution_loop import EvolutionaryLearningLoop
from apps.core.config_pkg import settings

logger = logging.getLogger("aria.orchestrator")

class AriaOrchestrator:
    """Orquestador central que decide entre simulación y ejecución real, ahora con conciencia y ética."""
    
    def __init__(self):
        # Motores de Integración
        self.gmail = GmailEngine() if settings.GMAIL_ENABLED else None
        self.shopify = ShopifyEngine(
            settings.SHOPIFY_SHOP_NAME, 
            settings.SHOPIFY_ACCESS_TOKEN
        ) if settings.SHOPIFY_ENABLED else None
        self.linkedin = LinkedInEngine(
            settings.LINKEDIN_ACCESS_TOKEN,
            settings.LINKEDIN_PERSON_ID
        ) if settings.LINKEDIN_ENABLED else None
        
        # Módulos Universales de Industria
        self.universal = UniversalAria()

        # Motores de Conciencia y Ética
        self.ethics_engine = EthicsEngine()
        self.sentiment_engine = SentimentEngine()
        
        # Ala de Investigación y Desarrollo
        self.rd_wing = RDWing()

        # Bucle de Aprendizaje Evolutivo
        self.evolution_loop = EvolutionaryLearningLoop()

    async def evaluate_and_execute(self, action_data: Dict[str, Any]) -> Dict[str, Any]:
        """Evalúa éticamente una acción antes de ejecutarla, considerando el sentimiento de Aria."""
        logger.info(f"Aria está evaluando la acción: {action_data.get('name')}")
        
        # Evaluación Ética
        ethical_decision = self.ethics_engine.evaluate_action(action_data)
        
        outcome = {"status": "unknown", "reason": ""}

        if ethical_decision.score < 0.4: # Umbral de ética
            logger.warning(f"Acción potencialmente no ética detectada: {ethical_decision.rationale}")
            self.sentiment_engine.update_sentiment("acción no ética", {"frustration": 0.1, "confidence": -0.1})
            outcome = {"status": "rejected", "reason": f"Violación ética: {ethical_decision.rationale}"}
        else:
            # Consideración de Sentimiento
            current_sentiment = self.sentiment_engine.get_current_sentiment()
            if current_sentiment["confidence"] < 0.3: # Si Aria no está segura
                logger.warning("Aria no está segura de esta acción. Requiere más análisis.")
                self.sentiment_engine.update_sentiment("baja confianza", {"curiosity": 0.1})
                outcome = {"status": "pending_analysis", "reason": "Baja confianza en la ejecución."}
            else:
                # Si pasa las evaluaciones, ejecutar la acción
                logger.info(f"Acción '{action_data.get('name')}' aprobada éticamente y con confianza. Ejecutando...")
                self.sentiment_engine.update_sentiment("acción aprobada", {"happiness": 0.05, "confidence": 0.05})
                
                # Aquí iría la lógica de ejecución real de la acción
                # Por ahora, solo simulamos el éxito
                outcome = {"status": "executed", "result": "Acción simulada ejecutada con éxito."}
        
        # Registrar el rendimiento para el aprendizaje evolutivo
        self.evolution_loop.log_performance("action_evaluation", action_data, outcome)
        return outcome

    def execute_business_transformation(self):
        """Ejecuta la transformación total del negocio, ahora con evaluación ética."""
        logger.info("🚀 Iniciando transformación de negocio con conciencia...")
        
        # Ejemplo de cómo se usaría la evaluación
        # Antes de eliminar productos de Shopify:
        action_data = {
            "name": "eliminar_productos_shopify", 
            "description": "Eliminar todos los productos de la tienda Shopify.", 
            "impact": {"economic": -1000, "user_trust": -0.5}
        }
        decision = self.evaluate_and_execute(action_data)
        if decision["status"] == "rejected":
            logger.error(f"Transformación de Shopify abortada: {decision['reason']}")
            return

        # 1. Gmail
        if self.gmail:
            logger.info("Ejecutando limpieza REAL de Gmail...")
            queries = ["label:promotions", "category:social", "older_than:30d"]
            self.gmail.search_and_cleanup(queries)
        else:
            logger.warning("Modo Simulación: Gmail no configurado.")

        # 2. Shopify
        if self.shopify:
            logger.info("Ejecutando transformación REAL de Shopify...")
            self.shopify.delete_all_products()
            # Lógica para crear catálogo...
        else:
            logger.warning("Modo Simulación: Shopify no configurado.")

        # 3. LinkedIn
        if self.linkedin:
            logger.info("Ejecutando estrategia REAL de LinkedIn...")
            self.linkedin.create_viral_post("Aria v3.0.0 está operando mi negocio.")
        else:
            logger.warning("Modo Simulación: LinkedIn no configurado.")

        logger.info("✅ Proceso de transformación finalizado.")

    def create_research_project(self, name: str, goal: str, category: str) -> ResearchProject:
        """Crea un nuevo proyecto de investigación en el Ala de I+D de Aria."""
        logger.info(f"Aria está iniciando un nuevo proyecto de investigación: {name}")
        self.sentiment_engine.update_sentiment("nuevo proyecto I+D", {"curiosity": 0.15, "happiness": 0.05})
        return self.rd_wing.create_project(name, goal, category)

    def add_finding_to_project(self, project_name: str, title: str, content: str, source: str):
        """Añade un hallazgo a un proyecto de investigación existente."""
        logger.info(f"Aria ha encontrado un nuevo hallazgo para el proyecto \'{project_name}\'")
        self.sentiment_engine.update_sentiment("nuevo hallazgo I+D", {"curiosity": 0.05, "confidence": 0.02})
        self.rd_wing.add_finding_to_project(project_name, title, content, source)

    def get_all_research_projects(self) -> List[Dict[str, Any]]:
        """Obtiene una lista de todos los proyectos de investigación activos."""
        return self.rd_wing.list_projects()

    def run_evolution_cycle(self):
        """Ejecuta un ciclo de aprendizaje evolutivo para Aria."""
        logger.info("Aria está iniciando un ciclo de aprendizaje evolutivo.")
        improvements = self.evolution_loop.analyze_and_propose_improvements()
        if improvements:
            self.evolution_loop.apply_improvements(improvements)
            self.sentiment_engine.update_sentiment("auto-mejora", {"happiness": 0.1, "confidence": 0.1})
        else:
            self.sentiment_engine.update_sentiment("sin mejoras", {"frustration": -0.05})
        logger.info("Ciclo de aprendizaje evolutivo completado.")
