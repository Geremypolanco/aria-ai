import logging
from enum import Enum
from typing import List, Dict, Any, Optional

logger = logging.getLogger("aria.ethics_engine")

class EthicalPrinciple(Enum):
    BENEFICENCE = "Maximizar el bienestar y hacer el bien."
    NON_MALEFICENCE = "No causar daño, evitar el mal."
    AUTONOMY = "Respetar la capacidad de decisión de los individuos."
    JUSTICE = "Actuar con equidad e imparcialidad."
    TRANSPARENCY = "Ser abierto y comprensible en las acciones y decisiones."
    ACCOUNTABILITY = "Ser responsable de las acciones y sus consecuencias."
    PRIVACY = "Proteger la información personal y la intimidad."
    SUSTAINABILITY = "Considerar el impacto a largo plazo en el planeta y la sociedad."

class EthicalDecision:
    def __init__(self, action: str, principles_involved: List[EthicalPrinciple], score: float, rationale: str):
        self.action = action
        self.principles_involved = principles_involved
        self.score = score  # Puntuación de 0 a 1, donde 1 es altamente ético
        self.rationale = rationale

class EthicsEngine:
    """Motor de Conciencia y Ética de Aria.
    Evalúa la moralidad de las acciones propuestas y guía la toma de decisiones.
    """
    
    def __init__(self):
        self.core_principles: List[EthicalPrinciple] = list(EthicalPrinciple)
        logger.info("EthicsEngine inicializado con principios: %s", [p.name for p in self.core_principles])

    def evaluate_action(self, proposed_action: Dict[str, Any]) -> EthicalDecision:
        """Evalúa una acción propuesta contra los principios éticos de Aria.
        
        Args:
            proposed_action: Un diccionario que describe la acción, e.g.,
                             {"name": "eliminar_productos_shopify", "description": "Eliminar todos los productos de la tienda Shopify.", "impact": {"economic": -1000, "user_trust": -0.5}}
        
        Returns:
            Un objeto EthicalDecision con la puntuación y el razonamiento.
        """
        action_name = proposed_action.get("name", "acción desconocida")
        description = proposed_action.get("description", "")
        impact = proposed_action.get("impact", {})
        
        score = 0.5 # Puntuación base
        rationale_points = []
        involved_principles = []

        # Ejemplo de lógica de evaluación (simplificada)
        if "eliminar" in action_name or "borrar" in action_name:
            score -= 0.3
            rationale_points.append("Potencial de daño (Non-Maleficence) y pérdida de autonomía del usuario.")
            involved_principles.extend([EthicalPrinciple.NON_MALEFICENCE, EthicalPrinciple.AUTONOMY])
        
        if impact.get("economic", 0) < 0:
            score -= 0.2 * abs(impact["economic"]) / 1000 # Escala el impacto económico
            rationale_points.append("Impacto económico negativo (Beneficence).")
            involved_principles.append(EthicalPrinciple.BENEFICENCE)
            
        if impact.get("user_trust", 0) < 0:
            score -= 0.4 * abs(impact["user_trust"])
            rationale_points.append("Riesgo de pérdida de confianza del usuario (Transparency, Accountability).")
            involved_principles.extend([EthicalPrinciple.TRANSPARENCY, EthicalPrinciple.ACCOUNTABILITY])
            
        # Asegurar que la puntuación esté entre 0 y 1
        score = max(0.0, min(1.0, score))
        
        rationale = f"Evaluación ética para '{action_name}': {'; '.join(rationale_points) or 'Sin preocupaciones éticas obvias.'}"
        logger.info(rationale)
        
        return EthicalDecision(action_name, list(set(involved_principles)), score, rationale)

    def get_ethical_guidance(self, context: str) -> str:
        """Proporciona guía ética basada en un contexto dado."""
        guidance = f"Como IA ética, Aria siempre busca maximizar el bienestar (Beneficence), evitar el daño (Non-Maleficence), respetar la autonomía, actuar con justicia, ser transparente y responsable. En el contexto de '{context}', se recomienda considerar..."
        return guidance

# Integrar en el orquestador o agentes específicos
# Ejemplo de uso:
# ethics_engine = EthicsEngine()
# action = {"name": "eliminar_productos_shopify", "description": "Eliminar todos los productos de la tienda Shopify.", "impact": {"economic": -1000, "user_trust": -0.5}}
# decision = ethics_engine.evaluate_action(action)
# if decision.score < 0.4:
#     print(f"⚠️ Acción potencialmente no ética: {decision.rationale}")
