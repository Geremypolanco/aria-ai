import logging
from enum import Enum
from typing import Any

logger = logging.getLogger("aria.ethics_engine")


class EthicalPrinciple(Enum):
    BENEFICENCE = "Maximize well-being and do good."
    NON_MALEFICENCE = "Cause no harm, avoid evil."
    AUTONOMY = "Respect individuals' capacity for decision-making."
    JUSTICE = "Act with fairness and impartiality."
    TRANSPARENCY = "Be open and understandable in actions and decisions."
    ACCOUNTABILITY = "Be responsible for actions and their consequences."
    PRIVACY = "Protect personal information and privacy."
    SUSTAINABILITY = "Consider the long-term impact on the planet and society."


class EthicalDecision:
    def __init__(
        self, action: str, principles_involved: list[EthicalPrinciple], score: float, rationale: str
    ):
        self.action = action
        self.principles_involved = principles_involved
        self.score = score  # Score from 0 to 1, where 1 is highly ethical
        self.rationale = rationale


class EthicsEngine:
    """Aria's Ethics and Awareness Engine.
    Evaluates the morality of proposed actions and guides decision-making.
    """

    def __init__(self):
        self.core_principles: list[EthicalPrinciple] = list(EthicalPrinciple)
        logger.info(
            "EthicsEngine initialized with principles: %s", [p.name for p in self.core_principles]
        )

    def evaluate_action(self, proposed_action: dict[str, Any]) -> EthicalDecision:
        """Evaluates a proposed action against Aria's ethical principles.

        Args:
            proposed_action: A dictionary describing the action, e.g.,
                             {"name": "delete_shopify_products", "description": "Delete all products from the Shopify store.", "impact": {"economic": -1000, "user_trust": -0.5}}

        Returns:
            An EthicalDecision object with the score and reasoning.
        """
        action_name = proposed_action.get("name", "unknown action")
        proposed_action.get("description", "")
        impact = proposed_action.get("impact", {})

        score = 0.5  # Base score
        rationale_points = []
        involved_principles = []

        # Example evaluation logic (simplified)
        # Note: "eliminar"/"borrar" are intentionally left untranslated — they are
        # data matched against incoming action names, not prose.
        if "eliminar" in action_name or "borrar" in action_name:
            score -= 0.3
            rationale_points.append(
                "Potential for harm (Non-Maleficence) and loss of user autonomy."
            )
            involved_principles.extend(
                [EthicalPrinciple.NON_MALEFICENCE, EthicalPrinciple.AUTONOMY]
            )

        if impact.get("economic", 0) < 0:
            score -= 0.2 * abs(impact["economic"]) / 1000  # Scale the economic impact
            rationale_points.append("Negative economic impact (Beneficence).")
            involved_principles.append(EthicalPrinciple.BENEFICENCE)

        if impact.get("user_trust", 0) < 0:
            score -= 0.4 * abs(impact["user_trust"])
            rationale_points.append(
                "Risk of losing user trust (Transparency, Accountability)."
            )
            involved_principles.extend(
                [EthicalPrinciple.TRANSPARENCY, EthicalPrinciple.ACCOUNTABILITY]
            )

        # Ensure the score is between 0 and 1
        score = max(0.0, min(1.0, score))

        rationale = f"Ethical evaluation for '{action_name}': {'; '.join(rationale_points) or 'No obvious ethical concerns.'}"
        logger.info(rationale)

        return EthicalDecision(action_name, list(set(involved_principles)), score, rationale)

    def get_ethical_guidance(self, context: str) -> str:
        """Provides ethical guidance based on a given context."""
        guidance = f"As an ethical AI, Aria always seeks to maximize well-being (Beneficence), avoid harm (Non-Maleficence), respect autonomy, act with justice, and be transparent and accountable. In the context of '{context}', it is recommended to consider..."
        return guidance


# Integrate into the orchestrator or specific agents
# Usage example:
# ethics_engine = EthicsEngine()
# action = {"name": "delete_shopify_products", "description": "Delete all products from the Shopify store.", "impact": {"economic": -1000, "user_trust": -0.5}}
# decision = ethics_engine.evaluate_action(action)
# if decision.score < 0.4:
#     print(f"⚠️ Potentially unethical action: {decision.rationale}")
