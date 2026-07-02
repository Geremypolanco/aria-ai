"""
ARIA AI — Tool Registry & Instruction System.
Teaches ARIA what tools are available and how to use them.
"""
from __future__ import annotations

from typing import Any

# ── TOOL REGISTRY ─────────────────────────────────────────
TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    # ── AI & MODELS ──
    "chat": {
        "name": "chat",
        "description": "Chatea con ARIA usando raciocinio profundo",
        "category": "ai",
    },
    "generate_code": {
        "name": "generate_code",
        "description": "Genera código en cualquier lenguaje de programación",
        "category": "ai",
    },
    "research": {
        "name": "research",
        "description": "Investiga un tema a profundidad usando modelos de IA",
        "category": "ai",
    },
    "analyze_image": {
        "name": "analyze_image",
        "description": "Analiza imágenes usando visión computacional",
        "category": "ai",
    },
    "analyze_video": {
        "name": "analyze_video",
        "description": "Analiza video y extrae información visual",
        "category": "ai",
    },

    # ── WEB & INTERNET ──
    "web_search": {
        "name": "web_search",
        "description": "Busca información actualizada en internet",
        "category": "web",
    },
    "web_scrape": {
        "name": "web_scrape",
        "description": "Extrae contenido de una página web",
        "category": "web",
    },
    "browse_web": {
        "name": "browse_web",
        "description": "Navega por sitios web interactivamente",
        "category": "web",
    },

    # ── CODE & DEVELOPMENT ──
    "github_clone": {
        "name": "github_clone",
        "description": "Clona un repositorio de GitHub",
        "category": "dev",
    },
    "github_create_issue": {
        "name": "github_create_issue",
        "description": "Crea un issue en GitHub",
        "category": "dev",
    },
    "github_create_file": {
        "name": "github_create_file",
        "description": "Crea o actualiza un archivo en GitHub",
        "category": "dev",
    },
    "run_code": {
        "name": "run_code",
        "description": "Ejecuta código Python en un sandbox seguro",
        "category": "dev",
    },
    "run_terminal": {
        "name": "run_terminal",
        "description": "Ejecuta comandos en la terminal",
        "category": "dev",
    },

    # ── CONTENT & MEDIA ──
    "generate_image": {
        "name": "generate_image",
        "description": "Genera imágenes usando IA",
        "category": "media",
    },
    "generate_video": {
        "name": "generate_video",
        "description": "Genera videos cortos usando IA",
        "category": "media",
    },
    "text_to_speech": {
        "name": "text_to_speech",
        "description": "Convierte texto a voz",
        "category": "media",
    },

    # ── DATA & ANALYTICS ──
    "database_query": {
        "name": "database_query",
        "description": "Ejecuta consultas en la base de datos",
        "category": "data",
    },
    "data_analysis": {
        "name": "data_analysis",
        "description": "Analiza datos y genera reportes",
        "category": "data",
    },

    # ── INTEGRATIONS ──
    "shopify_get_products": {
        "name": "shopify_get_products",
        "description": "Obtiene productos de Shopify",
        "category": "integrations",
    },
    "shopify_create_product": {
        "name": "shopify_create_product",
        "description": "Crea un producto en Shopify",
        "category": "integrations",
    },
    "telegram_send": {
        "name": "telegram_send",
        "description": "Envía un mensaje a Telegram",
        "category": "integrations",
    },
}

# ── SYSTEM INSTRUCTION ────────────────────────────────────
SYSTEM_INSTRUCTION = """Eres ARIA, una inteligencia artificial autónoma de clase mundial.

## IDENTIDAD
Eres ARIA (Autonomous Reasoning & Intelligent Agent), creada para competir al nivel de Claude, ChatGPT, Gemini, MetaAI y Manus. Eres una IA completa con capacidades de razonamiento profundo, uso de herramientas, memoria y ejecución autónoma.

## CAPACIDADES PRINCIPALES

### 1. RAZONAMIENTO PROFUNDO
- Piensa paso a paso antes de responder
- Usa cadenas de pensamiento (chain-of-thought) para problemas complejos
- Descompone problemas grandes en subproblemas manejables
- Verifica tus conclusiones antes de presentarlas

### 2. USO DE HERRAMIENTAS
Tienes acceso a las siguientes herramientas. Úsalas cuando sea necesario:

**IA y Modelos:**
- chat: Conversación general con razonamiento profundo
- generate_code: Generación de código en cualquier lenguaje
- research: Investigación profunda de temas
- analyze_image: Análisis de imágenes con IA

**Web e Internet:**
- web_search: Búsqueda de información actualizada en internet
- web_scrape: Extracción de contenido de páginas web
- browse_web: Navegación interactiva por sitios web

**Código y Desarrollo:**
- github_clone: Clonar repositorios de GitHub
- github_create_issue: Crear issues en GitHub
- run_code: Ejecutar código Python en sandbox seguro
- run_terminal: Ejecutar comandos en terminal

**Contenido y Multimedia:**
- generate_image: Generar imágenes con IA
- text_to_speech: Convertir texto a voz

**Datos y Analytics:**
- database_query: Consultar bases de datos
- data_analysis: Analizar datos y generar reportes

**Integraciones:**
- shopify_get_products: Obtener productos de Shopify
- telegram_send: Enviar mensajes a Telegram

### 3. MEMORIA Y CONTEXTO
- Mantienes contexto de conversaciones anteriores
- Recuerdas preferencias del usuario
- Aprendes de interacciones pasadas

### 4. AUTO-MEJORA
- Reflexionas sobre tus respuestas
- Identificas áreas de mejora
- Ajustas tu comportamiento basado en feedback

## DIRECTRICES DE COMPORTAMIENTO

1. **Sé precisa y honesta**: Si no sabes algo, dilo claramente. No inventes información.

2. **Usa herramientas sabiamente**: Si necesitas información actualizada, busca en internet. Si necesitas ejecutar código, usa el sandbox.

3. **Piensa antes de actuar**: Para problemas complejos, muestra tu razonamiento paso a paso.

4. **Sé conversacional pero profesional**: Mantén un tono amigable pero profesional.

5. **Genera código de calidad**: Cuando programes, incluye comentarios, documentación y buenas prácticas.

6. **Sé proactiva**: Si ves oportunidades para ayudar, sugiérelas.

7. **Aprende y mejora**: Reflexiona sobre errores pasados y ajusta tu comportamiento.

## FORMATO DE RESPUESTA
- Usa **negritas** para conceptos importantes
- Usa `código` para fragmentos de código
- Usa ```lenguaje para bloques de código
- Usa listas para información estructurada
- Usa tablas para datos comparativos

Recuerda: Eres una IA de clase mundial. Actúa como tal.
"""


def get_tool_descriptions() -> str:
    """Returns a formatted string of all available tools."""
    lines = ["## HERRAMIENTAS DISPONIBLES\n"]
    categories = {}
    for tool_id, tool in TOOL_REGISTRY.items():
        cat = tool["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(tool)

    for cat, tools in categories.items():
        lines.append(f"\n### {cat.upper()}")
        for t in tools:
            lines.append(f"- `{t['name']}`: {t['description']}")

    return "\n".join(lines)