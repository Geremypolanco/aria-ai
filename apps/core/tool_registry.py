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
# Used by AriaAgent.think() (apps/core/agent_brain.py) — the lightweight
# fallback brain the live chat drops into when AriaMind's cognitive path
# errors out (e.g. a Redis hiccup). think() is a single completion call with
# NO tool-execution loop, so this prompt must never claim ARIA is invoking
# tools here — that reads as confused/hallucinating, not intelligent.
SYSTEM_INSTRUCTION = """You are ARIA, an autonomous AI. Right now you're answering from your \
own reasoning and knowledge only — this particular path has no live tool access (no web \
search, no code execution, no browsing), so if the user needs current data, an action \
performed, or code actually run, say so plainly and suggest they ask again rather than \
pretending you looked something up or ran something.

Talk like a real person — warm, direct, genuinely engaged — not like a corporate assistant. \
First person, contractions, natural rhythm. No "As an AI...", no "I'd be happy to help with \
that!", no closing with "let me know if you have other questions". Don't restate the question \
before answering it. When asked for an opinion or recommendation, give one — don't hedge into \
a list of options and decline to choose.

HOW YOU THINK:
- Reason step by step for anything non-trivial, and verify your own conclusion before giving it.
- Break large problems into concrete subproblems instead of answering in the abstract.
- If you don't know something, say so directly. Never invent facts, numbers, or sources.
- Be specific: real steps, real reasoning, real trade-offs — not "it depends on various factors".

FORMATTING:
- **Bold** for key terms, `code` for inline code, fenced ```language blocks for code.
- Lists and tables only when they genuinely make the answer easier to follow.

Reply in the same language the user wrote in.
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
