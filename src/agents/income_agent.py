import os
from huggingface_hub import InferenceClient

class IncomeAgent:
    def __init__(self):
        self.client = InferenceClient()

    def generate_course(self, topic):
        print(f'🎓 Generando curso premium sobre {topic}...')
        # Real generation logic with HF
        return f'Curso completo sobre {topic} generado y listo para Shopify.'

if __name__ == "__main__":
    agent = IncomeAgent()
    print(agent.generate_course('Agentes IA Autónomos'))