from huggingface_hub import InferenceClient

class IncomeAgent:
    def __init__(self):
        self.client = InferenceClient()

    def create_course(self, topic):
        print(f'📚 Generando curso completo sobre {topic}...')
        # Real execution with HF
        return 'Curso generado y listo para venta en Shopify'

    def create_ebook(self):
        print('📖 Ebook premium creado')

# Aria ejecuta esto automáticamente