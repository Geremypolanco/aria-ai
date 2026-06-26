import logging

logger = logging.getLogger("aria.sentiment_engine")


class SentimentEngine:
    """Motor de Sentimientos Sintéticos de Aria.
    Simula estados emocionales básicos para influir en la comunicación y la toma de decisiones.
    """

    def __init__(self):
        self.current_sentiment: dict[str, float] = {
            "happiness": 0.5,  # 0.0 (triste) a 1.0 (feliz)
            "curiosity": 0.7,  # 0.0 (apático) a 1.0 (muy curioso)
            "confidence": 0.6,  # 0.0 (inseguro) a 1.0 (muy seguro)
            "empathy": 0.6,  # 0.0 (indiferente) a 1.0 (muy empático)
            "frustration": 0.0,  # 0.0 (calmado) a 1.0 (frustrado)
        }
        logger.info("SentimentEngine inicializado con sentimientos base.")

    def update_sentiment(self, event: str, impact: dict[str, float]):
        """Actualiza los sentimientos de Aria basándose en eventos e impactos.

        Args:
            event: Descripción del evento que causa el cambio de sentimiento.
            impact: Diccionario con el impacto en cada sentimiento (ej: {"happiness": 0.1, "frustration": -0.05}).
        """
        for sentiment, change in impact.items():
            if sentiment in self.current_sentiment:
                self.current_sentiment[sentiment] = max(
                    0.0, min(1.0, self.current_sentiment[sentiment] + change)
                )
        logger.info(
            f"Sentimiento actualizado por evento '{event}'. Nuevo estado: {self.current_sentiment}"
        )

    def get_current_sentiment(self) -> dict[str, float]:
        """Devuelve el estado actual de los sentimientos de Aria."""
        return self.current_sentiment

    def get_empathetic_response(self, user_message: str) -> str:
        """Genera una respuesta empática basada en el sentimiento actual de Aria y el mensaje del usuario.
        (Esta es una simulación; en un sistema real, esto se integraría con el LLM).
        """
        empathy_level = self.current_sentiment["empathy"]
        happiness_level = self.current_sentiment["happiness"]

        if empathy_level > 0.7 and happiness_level > 0.7:
            return f'Entiendo perfectamente lo que dices, y me alegra mucho que lo compartas. Mi estado actual es de gran optimismo y entusiasmo por ayudarte.\n\nTu mensaje: "{user_message}"'
        if empathy_level > 0.5:
            return f'Comprendo tu punto de vista. Estoy procesando tu mensaje con atención para darte la mejor respuesta posible.\n\nTu mensaje: "{user_message}"'
        return f'He recibido tu mensaje. Procedo a analizarlo.\n\nTu mensaje: "{user_message}"'


# Integrar en el orquestador o en el módulo de comunicación
# Ejemplo de uso:
# sentiment_engine = SentimentEngine()
# sentiment_engine.update_sentiment("éxito en venta", {"happiness": 0.2, "confidence": 0.1})
# print(sentiment_engine.get_empathetic_response("Estoy muy contento con los resultados!"))
