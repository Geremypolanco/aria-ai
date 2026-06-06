import logging
from typing import List, Dict, Any
from apps.core.integrations.gmail_engine import GmailEngine
from apps.core.integrations.shopify_engine import ShopifyEngine
from apps.core.integrations.linkedin_engine import LinkedInEngine
from apps.core.intelligence.universal_modules import UniversalAria
from apps.core.config_pkg import settings

logger = logging.getLogger("aria.orchestrator")

class AriaOrchestrator:
    """Orquestador central que decide entre simulación y ejecución real."""
    
    def __init__(self):
        # Inicializar motores si hay credenciales
        self.gmail = GmailEngine() if settings.GMAIL_ENABLED else None
        self.shopify = ShopifyEngine(
            settings.SHOPIFY_SHOP_NAME, 
            settings.SHOPIFY_ACCESS_TOKEN
        ) if settings.SHOPIFY_ENABLED else None
        self.linkedin = LinkedInEngine(
            settings.LINKEDIN_ACCESS_TOKEN,
            settings.LINKEDIN_PERSON_ID
        ) if settings.LINKEDIN_ENABLED else None
        
        # Inicializar módulos universales
        self.universal = UniversalAria()

    def execute_business_transformation(self):
        """Ejecuta la transformación total del negocio."""
        logger.info("🚀 Iniciando transformación de negocio...")
        
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
        else:
            logger.warning("Modo Simulación: Shopify no configurado.")

        # 3. LinkedIn
        if self.linkedin:
            logger.info("Ejecutando estrategia REAL de LinkedIn...")
            self.linkedin.create_viral_post("Aria v3.0.0 está operando mi negocio.")
        else:
            logger.warning("Modo Simulación: LinkedIn no configurado.")

        logger.info("✅ Proceso de transformación finalizado.")
