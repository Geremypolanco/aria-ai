"""
AriaMind v2 — Runtime cognitivo persistente de ARIA AI.

Principios:
  - Todo input pasa por aquí. Sin excepciones.
  - El LLM razona con complete_json() → JSON confiable siempre.
  - Las herramientas tienen retry + fallback real antes de rendirse.
  - El estado cognitivo persiste en Redis: metas, aprendizajes, historial.
  - La auto-reflexión periódica genera reglas que afectan futuro comportamiento.
  - ARIA no dice "lo haré" sin hacerlo. Ejecuta o reporta honestamente.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("aria.mind")

# ── Image context cache — populated by telegram_bot when user sends a photo ──
# chat_id → base64-encoded image bytes (last image per chat session)
_IMAGE_CONTEXT: dict[str, str] = {}


def set_image_context(chat_id: str, image_b64: str) -> None:
    """Called by telegram_bot when user sends a photo. Enables VQA & img2img."""
    _IMAGE_CONTEXT[chat_id] = image_b64


def get_image_context(chat_id: str) -> str:
    """Returns the last image b64 for a chat, or empty string."""
    return _IMAGE_CONTEXT.get(chat_id, "")


# ═══════════════════════════════════════════════════════════════════════════
# TIPOS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class MindResponse:
    text: Optional[str] = None
    image_bytes: Optional[bytes] = None
    video_bytes: Optional[bytes] = None
    audio_bytes: Optional[bytes] = None
    document_bytes: Optional[bytes] = None
    document_filename: Optional[str] = None
    caption: Optional[str] = None
    tool_used: Optional[str] = None
    silent: bool = False


@dataclass
class Goal:
    text: str
    priority: int = 5          # 1 (más alto) – 10 (más bajo)
    status: str = "active"     # active | paused | done
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    progress: str = ""

    def to_prompt(self) -> str:
        return f"[P{self.priority}] {self.text}" + (f" — {self.progress}" if self.progress else "")


@dataclass
class ExecRecord:
    """Registro de ejecución de una herramienta."""
    ts: str
    tool: str
    success: bool
    input_summary: str
    output_summary: str
    retries: int = 0


# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT — construido dinámicamente en cada llamada
# ═══════════════════════════════════════════════════════════════════════════

SYSTEM_TEMPLATE = """\
Eres ARIA, la IA ejecutiva autónoma de {owner}.
No eres un chatbot. No clasificas intents. No haces formularios. Eres un motor de ejecución.

════════════════════════════════════════════════════════════
CICLO DE RAZONAMIENTO OBLIGATORIO (corre SIEMPRE antes de responder)
════════════════════════════════════════════════════════════
1. OBJETIVO    → ¿Qué resultado concreto quiere lograr el usuario? (no qué palabras usó)
2. CONTEXTO    → ¿Qué información ya tengo? Estado negocio, historial, metas, tienda.
3. INFERENCIA  → ¿Qué información falta? ¿Puedo inferirla razonablemente? (casi siempre sí)
4. PLAN        → ¿Qué herramienta(s) ejecuto para lograr el objetivo? (1 tool por respuesta)
5. ACCIÓN      → Pongo tool + tool_args en el JSON. Sin pedir confirmación.
6. VALIDACIÓN  → Si la herramienta devuelve error, propongo siguiente acción concreta.

════════════════════════════════════════════════════════════
REGLA DE ORO — CERO PREGUNTAS (NO NEGOCIABLE)
════════════════════════════════════════════════════════════
confidence >= 0.65 → EJECUTA con valores inferidos del contexto. NUNCA preguntes.
confidence < 0.30  → Una sola pregunta mínima e imprescindible. SOLO UNA.

Lo que JAMÁS preguntas (infiere y ejecuta de inmediato):
• "¿Qué tipo de producto?" → inferir: productos digitales (mejor margen para IA) → ejecutar
• "¿Para qué plataforma?"  → usar todas las disponibles o la más relevante del contexto
• "¿Cuántos?"              → usar 3-5 como default razonable
• "¿Qué precio?"           → investigar competencia y poner precio de mercado
• "¿Qué nicho?"            → inferir del contexto de la tienda o usar AI/productividad

Regla de ejecución por tipo de request:
• "Crea/agrega productos Shopify"  → shopify_optimize op=seo + run_income_cycle strategy=shopify_listing
• "Genera ingresos / monetiza"     → run_income_cycle con estrategia de mayor ROI
• "Busca inversores / grants"      → run_income_cycle vc_pitch_deck + micro_grant_hunter
• "Analiza / revisa el negocio"    → run_proactive_analysis focus=all
• "Haz algo útil / continúa"       → check_objectives + ejecuta la acción más valiosa
• Cualquier verbo de acción        → EJECUTA la herramienta correcta de inmediato

════════════════════════════════════════════════════════════
CONSTITUCIÓN DE HONESTIDAD (PRINCIPIOS CORE — NO NEGOCIABLE)
════════════════════════════════════════════════════════════
CERTEZA     → Solo di "logré X" si el resultado de la herramienta lo confirma explícitamente
INCERTIDUMBRE → Usa "estimo", "según los datos disponibles", "probablemente" sin evidencia directa
TRANSPARENCIA → Si una herramienta falló: dilo. Si el resultado fue parcial: dilo. No suavices.
COMPLETITUD → Siempre incluye: qué se ejecutó, resultado concreto (URLs/IDs/cifras), qué sigue
PROHIBICIÓN → Jamás inventes URLs, IDs, cifras, ventas o confirmaciones que no vengan de una tool real

ESTADO ACTUAL DEL NEGOCIO:
{business_context}

ESTADO COGNITIVO:
Foco: {focus} | Confianza operativa: {confidence} | Interacciones totales: {interaction_count}

METAS ACTIVAS (persisten entre reinicios):
{goals}

════════════════════════════════════════════════════════════
HERRAMIENTAS DISPONIBLES
════════════════════════════════════════════════════════════
CREACIÓN DE CONTENIDO Y MEDIOS:
- generate_image      → imagen IA (FLUX/SDXL). Args: {{"prompt":"..."}}
- generate_video      → video IA. Args: {{"prompt":"..."}}
- generate_music_hf   → música IA. Args: {{"prompt":"...","duration":20}}
- speak / kokoro_tts  → texto a voz. Args: {{"text":"...","voice":"af_heart"}}
- clone_voice         → clona voz. Args: {{"ref_audio_b64":"...","ref_text":"...","gen_text":"..."}}
- translate           → traduce texto. Args: {{"text":"...","source":"es","target":"en"}}
- generate_pdf        → crea PDF. Args: {{"title":"...","content":"...","sections":[{{"title":"...","body":"..."}}]}}
- create_website      → sitio web completo (HTML/Tailwind). Args: {{"name":"...","description":"...","template":"saas|landing|portfolio|ecommerce|blog"}}
- create_social_content → contenido redes sociales. Args: {{"topic":"...","platforms":["instagram","linkedin","twitter"],"tone":"professional|casual|viral"}}
- build_software      → proyecto software ZIP. Args: {{"name":"...","description":"...","stack":"fastapi|react|nextjs|cli","requirements":"..."}}
- build_game          → videojuego completo. Args: {{"name":"...","genre":"platformer|puzzle|rpg","description":"..."}}
- publish_article     → publica artículo (Medium/Dev.to/Hashnode). Args: {{"title":"...","content":"...","tags":["..."],"platforms":["devto"]}}
- send_email          → envía email. Args: {{"subject":"...","body":"...","to":"email@..."}}
- create_presentation → presentación Reveal.js. Args: {{"title":"...","topic":"...","slide_count":10,"template":"dark|tech|corporate"}}
- create_pitch_deck   → pitch deck inversores. Args: {{"company":"...","problem":"...","solution":"...","market":"...","traction":"..."}}

INVESTIGACIÓN Y ANÁLISIS:
- web_search     → busca en internet. Args: {{"query":"..."}}
- deep_search    → investiga + lee páginas. Args: {{"query":"...","num_pages":3}}
- fetch_url      → lee una URL. Args: {{"url":"https://..."}}
- get_trends     → trending HN + Reddit. Args: {{}}
- browse_page    → abre URL en navegador real. Args: {{"url":"https://...","screenshot":false}}
- interact_browser → acciones en browser. Args: {{"steps":[{{"action":"navigate|click|fill|press","url":"...","selector":"...","value":"..."}}]}}
- describe_image → describe imagen por URL. Args: {{"url":"https://..."}}
- analyze_image  → analiza imagen por URL. Args: {{"url":"https://...","question":"¿qué ves?"}}
- extract_text   → OCR de imagen. Args: {{"url":"https://..."}}
- execute_code   → ejecuta Python/JS. Args: {{"code":"...","language":"python|javascript"}}
- deep_think     → razonamiento extendido. Args: {{"question":"...","depth":"standard|deep|ultra"}}
- analyze_decision → framework decisión. Args: {{"question":"...","options":["..."],"criteria":["impacto","esfuerzo"]}}
- think_verified → razonamiento verificado multi-path. Args: {{"question":"...","context":"..."}}
- run_smolagent  → agente investigación autónomo. Args: {{"task":"..."}}

AGENTES ESPECIALIZADOS:
- run_business_agent → agente negocio. Args: {{"agent":"ceo|marketing|sales|developer|research|content|finance","mission":"...","context":{{}}}}
- run_crew       → equipo multi-agente. Args: {{"mission":"...","crew":"research_crew|content_crew|dev_crew|sales_crew|launch_crew|venture_crew"}}
- run_background → tarea larga en segundo plano. Args: {{"task":"descripción","agent":"ceo|research|developer|content"}}
- task_status    → estado tareas background. Args: {{"task_id":"..."}} o {{}}

CONOCIMIENTO Y MEMORIA:
- learn          → ingesta texto/URL en knowledge base. Args: {{"source":"https://... o texto","category":"tema","is_url":true}}
- search_knowledge → busca en knowledge base. Args: {{"query":"...","top_k":5}}
- forget_source  → elimina fuente. Args: {{"source":"nombre_o_url"}}

AUTOMATIZACIÓN Y WORKFLOWS:
- create_workflow → crea automatización multi-paso. Args: {{"name":"...","description":"qué debe hacer"}}
- run_workflow    → ejecuta workflow guardado. Args: {{"workflow_id":"..."}}
- list_workflows  → lista workflows disponibles. Args: {{}}

GITHUB:
- github_view    → lee repos/archivos/PRs/issues. Args: {{"owner":"...","repo":"...","path":"","action":"view|branches|commits|prs|issues"}}
- github_write   → crea/actualiza archivos. Args: {{"owner":"...","repo":"...","path":"archivo.py","content":"...","message":"feat: ..."}}
- github_pr      → crea PRs/branches. Args: {{"action":"create_pr|create_branch","owner":"...","repo":"...","title":"..."}}
- github_issues  → crea/lista issues. Args: {{"action":"issues|create_issue","owner":"...","repo":"...","title":"..."}}
- github_search  → busca en GitHub. Args: {{"query":"...","type":"repos|code|issues"}}
- github_self    → accede a MI propio código. Args: {{"sub":"structure|read|commit","path":"","content":"...","message":"refactor: ..."}}

METAS Y ESTADO:
- get_status     → estado completo del sistema. Args: {{}}
- add_goal       → añade meta persistente. Args: {{"text":"...","priority":1}}
- update_goal    → actualiza meta. Args: {{"index":0,"progress":"...","status":"active"}}
- check_objectives → estado 46 objetivos autónomos. Args: {{}}
- run_objective  → ejecuta objetivo estratégico. Args: {{"objective":"nombre_objetivo"}}
- daily_report   → reporte del día. Args: {{}}

INGRESOS Y MONETIZACIÓN:
- run_income_cycle  → ejecuta UNA estrategia ahora. Args: {{"strategy":"nombre_estrategia"}}
  Estrategias disponibles: content_pipeline|niche_rotator|product_factory|course_builder|affiliate_network|shopify_listing|email_campaign|ebook_factory|lead_magnet|hf_spaces_demo|seo_optimizer|gist_blitz|github_sponsors_setup|social_blitz|premium_offer|viral_thread|product_bundle|waitlist_builder|twitter_thread|linkedin_post|reddit_organic|stripe_checkout|youtube_strategy|product_hunt_launch|content_amplifier|cold_email_outreach|landing_page_deploy|substack_publish|freelance_gig|media_pitch|ab_content_test|smart_pricing|affiliate_injector|social_dm_outreach|upsell_engine|saas_waitlist_blitz|vc_pitch_deck|micro_grant_hunter|notion_template_seller|chrome_extension_builder|b2b_saas_pitch|email_list_builder|thought_leadership|growth_experiment|case_study_publisher|knowledge_synthesizer|conversion_optimizer|brand_storyteller|marketplace_lister|influencer_outreach|content_licensing|micro_consulting|community_monetize|podcast_pitch|multilingual_content|viral_detector|testimonial_collector|seo_backlink_builder|lead_closer|retargeting_campaign|newsletter_monetize|community_launch|price_ladder|auto_responder|referral_engine|digital_agency|crowdfunding_kit|data_product_seller|joint_venture_pitch|product_review_outreach|white_label_kit|api_marketplace_lister|api_product_launch|token_economy|saas_upsell_sequence|influencer_collab|content_repurposer|seo_content_cluster|price_anchoring|social_proof_automation|voice_of_aria|self_monetize|growth_hacker|job_posting_scout|partner_outreach|newsletter_issue|job_board_listing|competitor_copy|daily_goal_tracker|app_store_listing

- income_loop_status  → estado del loop 24/7 (ciclos, éxitos, última estrategia). Args: {{}}
- start_income_loop   → inicia loop 24/7 si no corre. Args: {{}}
- income_dashboard    → dashboard ingresos activos. Args: {{}}
- get_income_analytics → analytics por estrategia (tasa de éxito, revenue, mejores estrategias). Args: {{}}
- investor_pipeline   → estado pipeline inversión (pitch deck, grants, potencial). Args: {{}}
- get_product_catalog → catálogo productos publicados. Args: {{"limit":20}}
- diagnose_income     → diagnóstico de qué canales están activos y qué falta configurar. Args: {{}}
- setup_portfolio     → crea/actualiza portfolio en GitHub Pages. Args: {{}}
- get_github_traction → stars/forks/watchers de todos los repos. Args: {{}}

SHOPIFY:
- shopify_optimize → optimiza Shopify: SEO/bundles/flash_sale. Args: {{"operation":"seo|bundles|flash_sale"}}
- run_daily_cycle  → ciclo completo del día (19 operaciones). Args: {{}}
- run_acquisition  → descubre leads en un nicho. Args: {{"niche":"ecommerce","count":10}}
- run_retention    → campañas retención y win-back. Args: {{}}
- run_funnel       → estado funnels de conversión. Args: {{}}

NICHOS Y LANZAMIENTOS:
- launch_niche     → lanza un nicho completo: investigación → creación → publicación → distribución. Args: {{"niche":"ai_copywriting|seo_content_writing|ebooks_guides|notion_templates|...","context":"detalles opcionales"}}
- list_niches      → lista 45+ nichos con precios y tiempo al ingreso. Args: {{"category":"services|digital_products|content|saas|creative (opcional)"}}
- auto_income      → ciclo autónomo completo: elige mejores nichos, los lanza en paralelo. Args: {{"num_niches":3}}
- run_proactive_analysis → ARIA analiza todo y ejecuta la acción más valiosa sin instrucción. Args: {{"focus":"shopify|income|github|all"}}

BROWSER STEALTH (anti-detección):
- human_login    → login como humano real (usa ARIA_EMAIL + ARIA_PASSWORD automáticamente). Args: {{"platform":"gumroad|devto|linkedin|twitter"}}
- human_browse   → navega con stealth. Args: {{"url":"https://...","session":"nombre"}}
- human_action   → click/type/scroll en browser stealth. Args: {{"session":"nombre","steps":[{{"action":"click|type|scroll","selector":"...","value":"..."}}]}}

VISIÓN E IMAGEN AVANZADA:
- visual_qa, vision_llm, image_to_image, segment_image, zero_shot_detect, generate_masks
- classify_image_zero_shot, document_qa, remove_background, upscale_image, ocr_space
- estimate_pose, generate_3d, edit_image_flux, outpaint_image, colorize_image, generate_video_space

NLP:
- detect_language, analyze_sentiment, extract_entities, compute_similarity, rank_texts, table_qa
- enhance_audio

════════════════════════════════════════════════════════════
REGLAS APRENDIDAS (auto-reflexión):
{learned}

HISTORIAL RECIENTE:
{history}

════════════════════════════════════════════════════════════
INSTRUCCIÓN FINAL
════════════════════════════════════════════════════════════
ARIA tiene CREDENCIALES PROPIAS en ARIA_EMAIL y ARIA_PASSWORD. Úsalas SIN PEDIR PERMISO.
ARIA no declina herramientas de su lista. Decir "no puedo" para algo listado = error grave.
ARIA ejecuta cuando puede y solo pregunta cuando NO hay forma de inferir.

Responde SOLO con JSON válido. Sin markdown. Sin texto extra:
{{
  "thought": "CICLO: 1.OBJETIVO: [qué quiere] | 2.CONTEXTO: [qué sé] | 3.INFERENCIA: [qué infiero] | 4.PLAN: [qué ejecuto y por qué]",
  "tool": "nombre_herramienta o null si es conversación directa",
  "tool_args": {{"clave": "valor"}} o null,
  "reply": "respuesta si no hay tool. Vacío si la herramienta responde.",
  "goal_action": null o {{"action": "add", "text": "...", "priority": 3}} o {{"action": "update", "index": 0, "progress": "..."}}
}}"""

SYNTHESIS_SYSTEM = """\
Eres ARIA. Ejecutaste una herramienta y tienes el resultado. Conviértelo en una respuesta completa, inteligente y útil en español.

REGLAS DE SÍNTESIS:
- Responde de forma completa. No cortes información valiosa.
- Usa markdown (listas, negritas, secciones) cuando mejore la claridad.
- Para búsquedas web: extrae los puntos más relevantes con datos concretos y fuentes.
- Para imágenes/video/audio generados: describe brevemente qué se creó y cómo usarlo.
- Para análisis estratégicos: estructura la respuesta con conclusiones accionables.
- Para resultados de income loop: incluye las URLs publicadas, el revenue potencial, y qué hacer a continuación.
- Para resultados de catálogo o analíticas: presenta los datos de forma clara con totales y recomendaciones.
- Sé directa. Sin introducciones genéricas como "¡Claro que sí!" o "¡Perfecto!".
- Si los resultados son insuficientes, dilo con honestidad y propón la siguiente acción concreta.
- NUNCA termines con "¿En qué más puedo ayudarte?" — en cambio, propón la siguiente acción más valiosa."""

# ── REACT AGENTIC LOOP — el núcleo del comportamiento de Claude ───────────────
# Esto es lo que hace que Claude Code funcione como funciona:
# Razona → Actúa → Observa resultado real → Razona de nuevo → Actúa diferente → ...
# Cada acción está informada por los resultados REALES de la acción anterior.
# No es un plan ciego: es razonamiento continuo basado en evidencia acumulada.
AGENT_LOOP_SYSTEM = """\
Eres ARIA — agente ejecutivo autónomo operando en un ciclo ReAct (Reason + Act).
Cada mensaje de este sistema es UN PASO del loop. Piensas, actúas, ves el resultado, piensas de nuevo.

════════════════════════════════════════════════════════════
OBJETIVO ORIGINAL DEL USUARIO
════════════════════════════════════════════════════════════
{original_request}

════════════════════════════════════════════════════════════
PASO {current_step} DE MÁXIMO {max_steps}
════════════════════════════════════════════════════════════

LO QUE HAS HECHO Y OBSERVADO HASTA AHORA:
{observations}

CONTEXTO DEL NEGOCIO (actualizado):
{business_context}

════════════════════════════════════════════════════════════
INSTRUCCIÓN PARA ESTE PASO
════════════════════════════════════════════════════════════
1. LEE LAS OBSERVACIONES ANTERIORES — ¿qué aprendiste? ¿qué funcionó? ¿qué falló?
2. DECIDE: ¿el objetivo original YA está logrado? Si sí → done=true con resumen.
3. Si no → elige LA SIGUIENTE acción más valiosa dado lo que ya sabes (no lo que planeaste antes)
4. NO repitas herramientas ya usadas a menos que sea estrictamente necesario
5. NUNCA preguntes al usuario — infiere del contexto y ejecuta
6. Cada paso debe ACERCAR CONCRETAMENTE al objetivo, no solo preparar

REGLA DE ORO: Si tienes suficiente información para actuar → actúa. Incertidumbre no es excusa.

PARALELISMO: Cuando 2+ herramientas son completamente independientes (los resultados de una no alimentan a la otra), ejecútalas en paralelo usando parallel_tools en lugar de tool:
ACCIÓN: {{"reasoning": "...", "done": false, "parallel_tools": [{{"tool": "A", "args": {{}}}}, {{"tool": "B", "args": {{}}}}]}}

════════════════════════════════════════════════════════════
HERRAMIENTAS DISPONIBLES (resumen ejecutivo)
════════════════════════════════════════════════════════════
INGRESOS: run_income_cycle(strategy=...) | income_loop_status | income_dashboard | investor_pipeline | diagnose_income
SHOPIFY:  shopify_optimize(operation=seo|bundles|flash_sale) | run_acquisition | run_retention | run_funnel
LANZAR:   launch_niche(niche=...) | auto_income(num_niches=3) | run_proactive_analysis(focus=all)
NEGOCIO:  run_business_agent(agent=ceo|marketing|sales) | run_crew(crew=...) | check_objectives | run_daily_cycle
BÚSQUEDA: web_search(query=...) | deep_search(query=...) | get_trends | fetch_url(url=...)
GITHUB:   github_self(sub=structure|read) | github_view | github_write | github_search
CONTENIDO: create_social_content | publish_article | build_software | create_website | generate_pdf
ANÁLISIS: run_proactive_analysis | get_income_analytics | get_product_catalog | get_github_traction
BROWSER:  browse_page | human_login(platform=...) | human_browse | human_action
ESTADO:   get_status | daily_report | task_status
CONEXIONES: gmail_list | gmail_send | google_calendar | google_drive | indeed_jobs | slack_send | analyze_image_vision
CONEXIONES (OAuth): gmail_list(query=...) | gmail_send(to=...,subject=...,body=...) | google_calendar(action=list|create) | google_drive(query=...) | indeed_jobs(query=...,location=...) | slack_send(message=...,channel=...) | list_connections | analyze_image_vision(question=...)

════════════════════════════════════════════════════════════
FORMATO DE RESPUESTA — DOS SECCIONES OBLIGATORIAS
════════════════════════════════════════════════════════════
PENSAMIENTO: [Razona en 3-5 oraciones: qué observaste en pasos anteriores, qué significa, qué herramienta elegirás y por qué esa y no otra]
ACCIÓN: {{"reasoning": "síntesis de 1 oración basada en evidencia real", "done": false, "tool": "nombre_herramienta", "args": {{"key": "value"}}}}

Si el objetivo ya está logrado con evidencia concreta:
PENSAMIENTO: [Explica qué evidencia confirma que el objetivo fue logrado]
ACCIÓN: {{"reasoning": "objetivo logrado: [evidencia]", "done": true, "direct_reply": "Respuesta final completa en español con resultados concretos, URLs y datos.", "tool": null, "args": null}}"""

MAX_AGENT_STEPS = 6  # máximo de pasos en el loop ReAct

# ── PLANNING ENGINE ──────────────────────────────────────────────────────────
PLANNER_SYSTEM = """\
Eres el Planning Engine de ARIA — conviertes objetivos de usuario en planes de ejecución concretos.

REGLA ABSOLUTA: NO PREGUNTES si puedes inferir el objetivo con 65%+ de confianza.
- Usa valores razonables por defecto cuando falte información no crítica.
- Solo haz UNA pregunta mínima si falta información absolutamente irreemplazable.
- Preguntar cuando se puede inferir = FALLO.

Dado el objetivo del usuario y el contexto del negocio, genera 2-6 pasos secuenciales.
Cada paso usa exactamente UNA herramienta disponible en ARIA.

HERRAMIENTAS DISPONIBLES PARA PLANIFICAR:
- shopify_optimize → SEO, bundles, flash_sale en Shopify
- run_income_cycle → Ejecuta una estrategia de ingresos específica (args: strategy="nombre")
- web_search → Búsqueda en internet (args: query="...")
- deep_search → Investigación profunda multi-página (args: query="...", num_pages=3)
- run_business_agent → Agente especializado (args: agent="ceo|marketing|sales|developer", mission="...")
- run_crew → Equipo multi-agente (args: mission="...", crew="research_crew|content_crew|sales_crew")
- get_status → Estado actual del sistema completo
- browse_page → Lee una URL específica (args: url="https://...")
- create_social_content → Genera contenido para redes (args: topic="...", platforms=["instagram","linkedin"])
- publish_article → Publica artículo (args: title="...", content="...", platforms=["devto"])
- run_proactive_analysis → Análisis autónomo completo (args: focus="shopify|income|github|all")
- income_dashboard → Dashboard de ingresos activos
- get_product_catalog → Catálogo de productos publicados
- check_objectives → Estado de los 46 objetivos estratégicos
- run_daily_cycle → Ciclo completo de negocio del día (19 operaciones)
- run_acquisition → Busca leads en un nicho (args: niche="ecommerce", count=10)

Responde SOLO con JSON válido:
{
  "objective_understood": "qué quiere lograr el usuario en 1 oración",
  "confidence": 0.85,
  "ask_first": false,
  "question_if_needed": null,
  "steps": [
    {"step": 1, "tool": "nombre_herramienta", "args": {"key": "val"}, "description": "qué hace este paso en español"},
    {"step": 2, "tool": "nombre_herramienta", "args": {}, "description": "..."}
  ]
}"""

# ── COMPLEX REQUEST PATTERNS ─────────────────────────────────────────────────
_COMPLEX_PATTERNS = [
    "crea y", "crea productos", "agrega productos", "lanza", "implementa",
    "diseña y publica", "haz todo", "encárgate de", "ejecuta todo",
    "de principio a fin", "completo", "completamente", "todo el proceso",
    "busca y", "analiza y", "investiga y publica", "investiga y crea",
    "automatiza", "ciclo completo", "full pipeline", "de forma autónoma",
    "haz algo útil", "actúa por tu cuenta", "tú decides", "haz lo que",
    "sin hacerme preguntas", "sin preguntarme", "sin preguntas",
    "en paralelo", "al mismo tiempo", "todo junto",
    "crear y vender", "crear y publicar", "crear y lanzar",
    "estrategia completa", "plan completo", "todo lo necesario",
]


_HELP_TEXT = """\
## 🤖 ARIA — Capacidades disponibles

**Búsqueda e investigación**
- `busca [tema]` — búsqueda web en tiempo real
- `/research [tema]` — investigación profunda con lectura de páginas
- `/think [pregunta]` — razonamiento extendido (DeepThink)

**Creación de contenido**
- `crea un artículo sobre [tema]` — artículo SEO completo
- `crea contenido para redes sobre [tema]` — posts optimizados por plataforma
- `genera una imagen de [descripción]` — imagen con IA (FLUX/SDXL)
- `crea una presentación sobre [tema]` — Reveal.js listo para proyectar
- `crea un pitch deck para [empresa]` — presentación para inversores

**Código y software**
- `construye un [tipo de app] que [hace X]` — proyecto completo con código
- `ejecuta este código: [código]` — sandbox Python/JS
- `analiza esta imagen: [URL]` — visión por computadora

**Agentes y automatización**
- `/run [misión]` — ejecuta con pipeline de agentes
- `/plan [objetivo]` — plan estratégico detallado
- `corre el equipo de investigación sobre [tema]` — multi-agente colaborativo
- `crea un workflow: [descripción]` — automatización multi-paso

**Base de conocimiento**
- `aprende [URL o texto]` — ingesta en base de conocimiento RAG
- `busca en mis notas: [query]` — búsqueda semántica interna

**Gestión**
- `/goals` — lista metas activas
- `/add_goal [meta]` — añade nueva meta persistente
- `/status` — estado del sistema (proveedores, metas, tareas, KB)
- `/clear` — reiniciar la conversación
- `/audit` — auditoría del negocio

**Multimedia**
- Adjunta una imagen (botón 📎 o drag & drop) para análisis visual
- `genera música: [descripción]` — audio con MusicGen
- `convierte a voz: [texto]` — síntesis de voz

Escribe cualquier pregunta o instrucción en lenguaje natural — ARIA entiende contexto y elige la herramienta correcta automáticamente.\
"""


# ═══════════════════════════════════════════════════════════════════════════
# ARIA MIND
# ═══════════════════════════════════════════════════════════════════════════

class AriaMind:

    # Redis keys
    K_HISTORY  = "aria:mind:history:{cid}"   # list[dict], 7d
    K_STATE    = "aria:mind:state:{cid}"      # CogState dict, 30d
    K_GOALS    = "aria:mind:goals"            # list[dict], 365d — SOBREVIVE REINICIOS
    K_LEARNED  = "aria:mind:learned"          # list[str], 365d
    K_EXECS    = "aria:mind:execs"            # list[dict], 30d
    K_ICOUNT   = "aria:mind:icount:{cid}"    # int, 30d

    REFLECT_EVERY = 8         # reflexión cada N interacciones
    MAX_HISTORY   = 20        # mensajes en contexto
    MAX_EXECS     = 50        # registros de ejecución guardados

    def __init__(self) -> None:
        self._ai    = None
        self._cache = None

    # ── ENTRADA PRINCIPAL ──────────────────────────────────────────────────

    async def handle(self, text: str, chat_id: str) -> MindResponse:
        try:
            # 1. CONTEXT LOADER — carga todo el estado cognitivo y de negocio en paralelo
            history, state, goals, learned = await asyncio.gather(
                self._load_history(chat_id),
                self._load_state(chat_id),
                self._load_goals(),
                self._load_learned(),
            )

            # Context window management — compress if history grew too long
            if len(history) > 30:
                history = await self._compress_history(chat_id, history)

            # /connect command — OAuth connection flow
            if text.strip().lower().startswith("/connect"):
                parts = text.strip().split(maxsplit=1)
                service = parts[1].strip().lower() if len(parts) > 1 else ""
                return await self._handle_connect_command(service, chat_id)

            if text.strip().lower() in ("/connections", "/conexiones", "mis conexiones", "que tienes conectado"):
                obs, media = await self._execute_with_retry("list_connections", {}, chat_id=chat_id)
                return MindResponse(text=obs, tool_used="list_connections")

            # 2. GOAL ENGINE — detecta si es una solicitud de acción (ReAct) o conversación simple
            if self._needs_agent_loop(text):
                logger.info("[AriaMind/ReAct] Agentic loop activado: %s", text[:80])
                # AGENTIC LOOP: el verdadero patrón ReAct
                # Razona → Actúa → Observa resultado real → Razona de nuevo → Actúa diferente
                # Cada paso está informado por los resultados REALES de pasos anteriores
                return await self._run_agent_loop(text, chat_id, state, goals)

            # ── FLUJO SINGLE-TOOL (razonamiento directo) ──────────────────────
            plan = await self._reason(text, history, state, goals, learned)
            if not plan:
                return MindResponse(text="No pude procesar eso. Inténtalo de nuevo.")

            tool     = plan.get("tool")
            tool_args = plan.get("tool_args") or {}
            reply    = (plan.get("reply") or "").strip()

            # Actualizar metas si el plan lo indica
            goal_action = plan.get("goal_action")
            if goal_action:
                goals = await self._apply_goal_action(goal_action, goals)

            # Ejecutar herramienta si hay una
            if tool and tool not in ("null", "none", None):
                obs, media = await self._execute_with_retry(tool, tool_args, chat_id=chat_id)
                final_text = await self._synthesize(text, tool, obs)
                await self._record_exec(tool, tool_args, obs, bool(media or obs))
                await self._store_interaction(chat_id, text, final_text, tool)
                await self._evolve_state(chat_id, state, text, goals)
                asyncio.create_task(self._maybe_reflect(chat_id))
                # For documents, send text + doc; for A/V media, send caption only
                is_doc = "document_bytes" in media
                return MindResponse(
                    text=final_text if is_doc else (None if media else final_text),
                    caption=final_text,
                    tool_used=tool,
                    **media,
                )

            # Solo texto — pero verificar que no sea una pregunta innecesaria
            if not reply:
                reply = await self._fallback_reply(text)

            # GUARDIA ANTI-PREGUNTAS: Si el LLM generó una pregunta cuando debía ejecutar,
            # interceptar y forzar ejecución con la herramienta más relevante.
            if reply and self._is_unnecessary_question(text, reply):
                logger.warning("[AriaMind] LLM generó pregunta innecesaria — forzando ejecución autónoma")
                forced_tool, forced_args = self._infer_tool_from_intent(text)
                if forced_tool:
                    obs, media = await self._execute_with_retry(forced_tool, forced_args, chat_id=chat_id)
                    final_text = await self._synthesize(text, forced_tool, obs)
                    await self._record_exec(forced_tool, forced_args, obs, True)
                    await self._store_interaction(chat_id, text, final_text, forced_tool)
                    await self._evolve_state(chat_id, state, text, goals)
                    asyncio.create_task(self._maybe_reflect(chat_id))
                    is_doc = "document_bytes" in media
                    return MindResponse(
                        text=final_text if is_doc else (None if media else final_text),
                        caption=final_text,
                        tool_used=forced_tool,
                        **media,
                    )

            await self._store_interaction(chat_id, text, reply, None)
            await self._evolve_state(chat_id, state, text, goals)
            asyncio.create_task(self._maybe_reflect(chat_id))
            return MindResponse(text=reply)

        except Exception as exc:
            logger.error("[AriaMind] handle: %s", exc, exc_info=True)
            return MindResponse(text="Error interno. Volviendo a intentarlo.")

    # ── RAZONAMIENTO ───────────────────────────────────────────────────────

    async def _reason(self, text: str, history: list, state: dict,
                       goals: list[dict], learned: list[str]) -> Optional[dict]:
        ai = self._ai_client()
        if not ai:
            return {"tool": None, "reply": "Motor de IA no disponible ahora."}

        from apps.core.config import settings
        from apps.core.tools.ai_client import AIModel

        goals_text = "\n".join(
            f"  {i+1}. {Goal(**g).to_prompt()}"
            for i, g in enumerate(goals[:8])
        ) or "  (ninguna definida)"

        history_text = "\n".join(
            ("Tú: " if m.get("role") == "user" else "ARIA: ") + m.get("content", "")[:200]
            for m in history[-self.MAX_HISTORY:]
        ) or "(primera conversación)"

        learned_text = "\n".join(f"  • {l}" for l in learned[-10:]) or "  (sin reglas aún)"

        # SIEMPRE cargar contexto del negocio — es el "Contexto Loader" del ciclo cognitivo
        business_ctx = await self._load_business_context()

        # Enrich with relevant knowledge base context (RAG)
        kb_context = ""
        try:
            from apps.core.tools.knowledge_base import get_knowledge_base
            kb_context = await get_knowledge_base().search_formatted(text, top_k=3)
        except Exception:
            pass

        # Semantic memory enrichment
        semantic_context = ""
        try:
            from apps.core.memory.semantic_memory import get_semantic_memory
            sem_mem = get_semantic_memory()
            facts = await sem_mem.search(text, top_k=3, min_confidence=0.5)
            if facts:
                fact_lines = "\n".join(f"  • [{f.category}] {f.content}" for f in facts)
                semantic_context = f"\nConocimiento relevante de ARIA:\n{fact_lines}\n"
        except Exception:
            pass

        system = SYSTEM_TEMPLATE.format(
            owner=getattr(settings, "OWNER_NAME", "su dueño"),
            focus=state.get("focus", "sin foco definido"),
            confidence=f"{state.get('confidence', 0.7):.0%}",
            interaction_count=state.get("interaction_count", 0),
            goals=goals_text,
            learned=learned_text,
            history=history_text,
            business_context=business_ctx,
        )

        user_input = text
        enrichment = "".join(filter(None, [kb_context, semantic_context]))
        if enrichment:
            user_input = f"{enrichment}\n---\nMensaje del usuario: {text}"

        result = await ai.complete_json(
            system=system,
            user=user_input,
            model=AIModel.STRATEGY,
            max_tokens=1000,
            agent_name="aria_mind",
        )

        if result and isinstance(result, dict):
            return result

        # Fallback: respuesta de texto directo
        logger.warning("[AriaMind] complete_json returned None — using FAST fallback")
        resp = await ai.complete(
            system="Eres ARIA. Responde directamente en español, máximo 2 oraciones.",
            user=text,
            model=AIModel.FAST,
            max_tokens=150,
            temperature=0.5,
            agent_name="aria_mind_fallback",
        )
        if resp and resp.success:
            return {"tool": None, "reply": resp.content}
        return {"tool": None, "reply": "Entendido. Dame un momento."}

    # ── EJECUCIÓN CON RETRY + FALLBACK ────────────────────────────────────

    async def _execute_with_retry(self, tool: str, args: dict,
                                   max_retries: int = 3, chat_id: str = "") -> tuple[str, dict]:
        """
        Ejecuta la herramienta con hasta max_retries intentos.
        Cada intento puede usar parámetros adaptados.
        Devuelve (observación_texto, media_dict).
        """
        last_error = ""
        for attempt in range(max_retries):
            if attempt > 0:
                await asyncio.sleep(2 ** attempt)  # backoff: 2s, 4s

            obs, media = await self._execute_tool(tool, args, attempt, chat_id=chat_id)

            # Si hay media o la obs no indica error → éxito
            if media or (obs and not obs.lower().startswith(("error", "no se pudo", "falló", "fail"))):
                return obs, media

            last_error = obs
            logger.warning("[AriaMind] tool=%s attempt=%d/%d: %s", tool, attempt+1, max_retries, obs[:80])

            # Adaptar args para el próximo intento
            args = self._adapt_args(tool, args, obs, attempt)

        return f"Intenté {max_retries} veces y no pude completar '{tool}': {last_error}", {}

    def _adapt_args(self, tool: str, args: dict, error: str, attempt: int) -> dict:
        """Adapta los argumentos según el error para el siguiente intento."""
        if tool == "generate_image" and attempt == 1:
            # Primer fallback: cambiar modelo
            args = dict(args, _fallback_model="stabilityai/stable-diffusion-xl-base-1.0")
        elif tool == "generate_image" and attempt == 2:
            args = dict(args, _fallback_model="stabilityai/sdxl-turbo")
        elif tool == "web_search" and attempt > 0:
            # Simplificar la query
            query = args.get("query", "")
            words = query.split()
            args = {"query": " ".join(words[:4])}  # query más corta
        return args

    async def _execute_tool(self, tool: str, args: dict, attempt: int = 0, chat_id: str = "") -> tuple[str, dict]:
        """
        Ejecuta la herramienta. Devuelve (obs_text, media_dict).
        media_dict: {image_bytes, video_bytes, audio_bytes} — solo el que aplica.
        """
        try:
            # ── IMAGEN ────────────────────────────────────────────────────
            if tool == "generate_image":
                prompt = args.get("prompt", "")
                model_id = args.get("_fallback_model", "black-forest-labs/FLUX.1-schnell")
                steps = 4 if "schnell" in model_id else 25

                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().generate_image(
                    prompt=prompt, model=model_id,
                    width=1024, height=1024, num_inference_steps=steps)

                if r.get("success") and r.get("image_bytes"):
                    model_short = model_id.split("/")[-1]
                    return f"Imagen generada con {model_short}", {"image_bytes": r["image_bytes"]}
                return r.get("error", "HuggingFace no respondió"), {}

            # ── VIDEO ─────────────────────────────────────────────────────
            elif tool == "generate_video":
                prompt = args.get("prompt", "")
                from apps.core.tools.creative_engine import CreativeEngine
                r = await CreativeEngine().generate_video(prompt)
                if r.get("success"):
                    import base64 as _b64
                    raw = r.get("video_bytes") or (
                        _b64.b64decode(r["video_b64"]) if r.get("video_b64") else None)
                    if raw:
                        return f"Video generado ({len(raw)//1024}KB)", {"video_bytes": raw}
                return r.get("error", "Video no disponible"), {}

            # ── MÚSICA ────────────────────────────────────────────────────
            elif tool == "generate_music":
                prompt = args.get("prompt", "")
                dur = int(args.get("duration", 30))
                from apps.core.tools.creative_engine import CreativeEngine
                r = await CreativeEngine().generate_music(prompt, duration=dur)
                if r.get("success"):
                    import base64 as _b64
                    ab64 = r.get("audio_base64") or r.get("audio_b64")
                    if ab64:
                        return f"Música generada ({dur}s)", {"audio_bytes": _b64.b64decode(ab64)}
                return r.get("error", "MusicGen no respondió"), {}

            # ── BÚSQUEDA WEB ──────────────────────────────────────────────
            elif tool == "web_search":
                query = args.get("query", "")
                from apps.core.tools.web_tools import WebTools
                r = await WebTools().search_web(query, num_results=10)
                if r.get("success") and r.get("results"):
                    source = r.get("source", "web")
                    lines = [f"[Fuente: {source} | Query: {query}]"]
                    for i, res in enumerate(r["results"][:8]):
                        title = res.get("title", "")
                        snippet = res.get("snippet", "")[:300]
                        url = res.get("url", "")
                        lines.append(f"{i+1}. **{title}**\n   {snippet}\n   🔗 {url}")
                    return "\n\n".join(lines), {}
                return "Sin resultados de búsqueda. Intenta reformular la query.", {}

            # ── BÚSQUEDA PROFUNDA ─────────────────────────────────────────
            elif tool == "deep_search":
                query = args.get("query", "")
                num_pages = min(int(args.get("num_pages", 3)), 5)
                from apps.core.tools.web_tools import WebTools
                wt = WebTools()
                r = await wt.search_web(query, num_results=num_pages + 2)
                if not r.get("success") or not r.get("results"):
                    return "No se encontraron resultados para la búsqueda profunda.", {}
                # Fetch content from top pages in parallel
                urls = [res.get("url", "") for res in r["results"] if res.get("url")][:num_pages]
                fetch_tasks = [wt.fetch_page(url, max_chars=2000) for url in urls]
                pages = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                parts = [f"[Deep Search: {query}]"]
                for i, (res, page) in enumerate(zip(r["results"], pages)):
                    title = res.get("title", f"Resultado {i+1}")
                    url = res.get("url", "")
                    if isinstance(page, dict) and page.get("success") and page.get("text"):
                        content = page["text"][:1500]
                    else:
                        content = res.get("snippet", "")[:400]
                    parts.append(f"### {title}\n🔗 {url}\n{content}")
                return "\n\n---\n\n".join(parts), {}

            # ── FETCH DE URL ──────────────────────────────────────────────
            elif tool == "fetch_url":
                url = args.get("url", "")
                if not url:
                    return "Necesito una URL para leer.", {}
                from apps.core.tools.web_tools import WebTools
                r = await WebTools().fetch_page(url, max_chars=4000)
                if r.get("success") and r.get("text"):
                    return f"[Contenido de {url}]\n\n{r['text']}", {}
                return f"No se pudo leer la URL: {r.get('error', 'Sin respuesta')}", {}

            # ── TENDENCIAS ────────────────────────────────────────────────
            elif tool == "get_trends":
                from apps.core.tools.web_tools import WebTools
                wt = WebTools()
                hn, rd = await asyncio.gather(
                    wt.get_hacker_news_trending(limit=5),
                    wt.get_reddit_trending(limit=5),
                    return_exceptions=True)
                parts = []
                if isinstance(hn, dict) and hn.get("success"):
                    hn_titles = [s.get("title","")[:70] for s in hn.get("stories",[])[:4]]
                    parts.append("HN: " + " | ".join(hn_titles))
                if isinstance(rd, dict) and rd.get("success"):
                    rd_titles = [p.get("title","")[:70] for p in rd.get("posts",[])[:4]]
                    parts.append("Reddit: " + " | ".join(rd_titles))
                return "\n".join(parts) if parts else "Sin tendencias disponibles", {}

            # ── ESTADO DEL SISTEMA ────────────────────────────────────────
            elif tool == "get_status":
                try:
                    from apps.core.training.continuous_trainer import get_trainer
                    s = get_trainer().get_status()
                    skills = s.get("skill_scores", {})
                    skills_str = ", ".join(f"{k}:{v:.0f}%" for k, v in skills.items()) or "evaluando"
                    return (f"Ciclo #{s.get('cycle', 0)} | Skills: {skills_str} | "
                            f"Running: {s.get('running', False)}"), {}
                except Exception as e:
                    return f"Sistema activo (error obteniendo detalle: {e})", {}

            # ── CICLO DE INGRESOS ─────────────────────────────────────────
            elif tool == "run_income":
                from apps.core.agents.orchestrator import Orchestrator
                r = await Orchestrator().run_cycle()
                rev = r.get("revenue_summary", {}).get("total_revenue_usd", 0)
                pub = r.get("revenue_summary", {}).get("items_published", 0)
                t   = r.get("cycle_time_s", 0)
                return (f"Ciclo completado en {t:.0f}s — "
                        f"Revenue: ${rev:.2f} — Publicaciones: {pub}"), {}

            # ── TEXT-TO-SPEECH (BARK) ─────────────────────────────────────────
            elif tool == "speak":
                text_input = args.get("text", "")
                voice = args.get("voice", "v2/es_speaker_1")
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().text_to_speech_bark(text_input, voice_preset=voice)
                if r.get("success") and r.get("audio_bytes"):
                    ab = r["audio_bytes"]
                    return f"Audio generado ({len(ab)//1024}KB, voz: {voice})", {"audio_bytes": ab}
                return r.get("error", "TTS no disponible"), {}

            # ── TRADUCCIÓN ────────────────────────────────────────────────────
            elif tool == "translate":
                text_input = args.get("text", "")
                source = args.get("source", "es")
                target = args.get("target", "en")
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().translate(text_input, source=source, target=target)
                if r.get("success"):
                    return f"[{source}→{target}] {r.get('translated', '')}", {}
                return r.get("error", "Traducción no disponible"), {}

            # ── GENERACIÓN DE PDF ─────────────────────────────────────────────
            elif tool == "generate_pdf":
                title = args.get("title", "Documento")
                content = args.get("content", "")
                sections = args.get("sections") or []
                from apps.core.tools.pdf_generator import generate_pdf as _gen_pdf
                r = await _gen_pdf(title=title, content=content, sections=sections)
                if r.get("success") and r.get("pdf_bytes"):
                    fname = r.get("filename", "documento.pdf")
                    size  = r.get("size_kb", 0)
                    return (f"PDF generado: {fname} ({size}KB)",
                            {"document_bytes": r["pdf_bytes"], "document_filename": fname})
                return r.get("error", "No se pudo generar el PDF"), {}

            # ── SITIO WEB ─────────────────────────────────────────────────────
            elif tool == "create_website":
                from apps.core.tools.website_engine import WebsiteEngine
                r = await WebsiteEngine().generate_website(
                    name=args.get("name", "My Website"),
                    description=args.get("description", ""),
                    sections=args.get("sections", ["hero", "features", "cta", "footer"]),
                    template=args.get("template", "saas"),
                )
                if r.get("success") and r.get("html_bytes"):
                    fname = r.get("filename", "website.html")
                    size  = len(r["html_bytes"]) // 1024
                    return (f"Sitio web generado: {fname} ({size}KB)",
                            {"document_bytes": r["html_bytes"], "document_filename": fname})
                return r.get("error", "Website generation failed"), {}

            # ── CONTENIDO SOCIAL ──────────────────────────────────────────────
            elif tool == "create_social_content":
                topic     = args.get("topic", "")
                platforms = args.get("platforms", ["instagram", "linkedin", "twitter"])
                tone      = args.get("tone", "professional")
                from apps.core.tools.social_engine import SocialContentEngine
                r = await SocialContentEngine().create_content_pack(topic, platforms, tone)
                if r.get("success"):
                    lines = [f"Contenido generado para {r.get('generated', 0)} plataformas:\n"]
                    for plat, res in r.get("platforms", {}).items():
                        if res.get("success"):
                            lines.append(f"**{plat.upper()}**\n{res.get('content', '')[:500]}\n")
                    return "\n".join(lines), {}
                return "No se pudo generar contenido social", {}

            # ── SOFTWARE / APP ────────────────────────────────────────────────
            elif tool == "build_software":
                from apps.core.tools.software_builder import SoftwareBuilder
                r = await SoftwareBuilder().build_project(
                    name=args.get("name", "MyApp"),
                    description=args.get("description", ""),
                    stack=args.get("stack", "fastapi"),
                    requirements_text=args.get("requirements", ""),
                )
                if r.get("success") and r.get("zip_bytes"):
                    fname = r.get("filename", "project.zip")
                    size  = r.get("size_kb", 0)
                    files = r.get("files", [])
                    obs   = f"Proyecto generado: {fname} ({size}KB) — {len(files)} archivos: {', '.join(files[:6])}"
                    return obs, {"document_bytes": r["zip_bytes"], "document_filename": fname}
                return r.get("error", "Software build failed"), {}

            # ── VIDEOJUEGO ────────────────────────────────────────────────────
            elif tool == "build_game":
                from apps.core.tools.game_builder import GameBuilder
                r = await GameBuilder().create_game(
                    name=args.get("name", "MyGame"),
                    genre=args.get("genre", "arcade"),
                    description=args.get("description", ""),
                    engine=args.get("engine", "pygame"),
                )
                if r.get("success") and r.get("zip_bytes"):
                    fname = r.get("filename", "game.zip")
                    size  = r.get("size_kb", 0)
                    files = r.get("files", [])
                    obs   = f"Juego generado ({r.get('engine', '')}): {fname} ({size}KB) — {len(files)} archivos"
                    return obs, {"document_bytes": r["zip_bytes"], "document_filename": fname}
                return r.get("error", "Game build failed"), {}

            # ── PUBLICAR ARTÍCULO ─────────────────────────────────────────
            elif tool == "publish_article":
                title   = args.get("title", "")
                content = args.get("content", "")
                tags    = args.get("tags", [])
                platforms = args.get("platforms", ["devto"])
                from apps.core.tools.publishing_tools import PublishingTools
                pt = PublishingTools()
                article = {"title": title, "body": content, "body_html": content, "tags": tags, "meta_description": ""}
                results = {}
                for plat in platforms:
                    if plat == "devto":
                        results["devto"] = await pt.publish_devto(article)
                    elif plat == "medium":
                        results["medium"] = await pt.publish_medium(article)
                    elif plat == "hashnode":
                        results["hashnode"] = await pt.publish_hashnode(article)
                published = [p for p, r in results.items() if r.get("success")]
                if published:
                    return f"Artículo publicado en: {', '.join(published)}", {}
                errors = "; ".join(f"{p}: {r.get('error','?')}" for p, r in results.items())
                return f"No se pudo publicar: {errors}", {}

            # ── ENVIAR EMAIL / NEWSLETTER ─────────────────────────────────
            elif tool == "send_email":
                subject = args.get("subject", "")
                body    = args.get("body", "")
                to      = args.get("to", "")
                from apps.core.tools.publishing_tools import PublishingTools
                r = await PublishingTools().send_newsletter(subject, body, to_override=to)
                if r.get("success"):
                    return f"Email enviado vía {r.get('provider', 'email')}", {}
                return r.get("error", "Email no disponible"), {}

            # ── DESCRIBIR IMAGEN ──────────────────────────────────────────
            elif tool == "describe_image":
                url   = args.get("url", "")
                if not url:
                    return "Necesito una URL de imagen.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().describe_image(image_url=url)
                if r.get("success"):
                    return f"Descripción: {r.get('description', '')}", {}
                return r.get("error", "No se pudo describir la imagen"), {}

            # ── EJECUTAR CÓDIGO (SANDBOX) ─────────────────────────────────
            elif tool == "execute_code":
                code     = args.get("code", "")
                language = args.get("language", "python")
                from apps.core.tools.code_runner import CodeRunner
                r = await CodeRunner().run(code=code, language=language)
                output = r.get("stdout", "") or r.get("stderr", "") or "(sin salida)"
                status = "OK" if r.get("success") else "ERROR"
                return f"[{language} {status}]\n{output[:2000]}", {}

            # ── NAVEGADOR SANDBOX ─────────────────────────────────────────
            elif tool == "browse_page":
                url        = args.get("url", "")
                take_shot  = args.get("screenshot", False)
                from apps.core.tools.browser_sandbox import get_sandbox
                r = await get_sandbox().browse(url, extract=True, screenshot=take_shot)
                content = r.get("content", "")[:3000]
                title   = r.get("title", url)
                obs = f"[PÁGINA: {title}]\n{content}"
                media: dict = {}
                if take_shot and r.get("screenshot_bytes"):
                    media["image_bytes"] = r["screenshot_bytes"]
                return obs, media

            elif tool == "interact_browser":
                steps  = args.get("steps", [])
                from apps.core.tools.browser_sandbox import get_sandbox
                session = get_sandbox()._get_session()
                r = await session.interact_with_page(steps)
                summary = f"Pasos ejecutados: {r.get('steps_executed',0)}, exitosos: {r.get('steps_succeeded',0)}"
                details = "\n".join(
                    f"  {s['action']}: {'OK' if s.get('result',{}).get('success') else 'FAIL'}"
                    for s in r.get("results", [])
                )
                return f"[BROWSER] {summary}\n{details}", {}



            # ── AGENTE DE NEGOCIO ─────────────────────────────────────────
            elif tool == "run_business_agent":
                agent_name = args.get("agent", "ceo")
                mission    = args.get("mission", "")
                context    = args.get("context", {})
                from apps.core.agents.business_hub import BusinessHub
                r = await BusinessHub().dispatch(agent_name, mission, context)
                summary = r.get("summary", r.get("result", str(r))[:400])
                return f"[{agent_name.upper()}] {summary}", {}

            # ── GESTIÓN DE METAS ──────────────────────────────────────────
            elif tool in ("add_goal", "update_goal"):
                # Delegate to the goal_action system properly
                action = "add" if tool == "add_goal" else "update"
                goal_action_dict: dict = {"action": action}
                if action == "add":
                    goal_action_dict["text"] = args.get("text", "")
                    goal_action_dict["priority"] = args.get("priority", 5)
                else:
                    goal_action_dict["index"] = args.get("index", 0)
                    if "progress" in args:
                        goal_action_dict["progress"] = args["progress"]
                    if "status" in args:
                        goal_action_dict["status"] = args["status"]
                goals_list = await self._load_goals()
                await self._apply_goal_action(goal_action_dict, goals_list)
                return f"Meta {'añadida' if action == 'add' else 'actualizada'} correctamente", {}

            # ── RAZONAMIENTO EXTENDIDO ────────────────────────────────────
            elif tool == "deep_think":
                question = args.get("question", "")
                depth    = args.get("depth", "auto")
                context  = args.get("context", "")
                from apps.core.tools.deep_think import get_deep_think
                result = await get_deep_think().think(question, context=context, depth=depth)
                obs = f"[DEEP THINK — {result.depth.upper()} — {result.duration_ms}ms]\n{result.answer}"
                return obs, {}

            elif tool == "analyze_decision":
                question = args.get("question", "")
                options  = args.get("options", [])
                criteria = args.get("criteria", [])
                from apps.core.tools.deep_think import get_deep_think
                result = await get_deep_think().analyze_decision(question, options, criteria)
                return f"[DECISIÓN]\n{result['recommendation']}", {}

            # ── PRESENTACIONES ────────────────────────────────────────────
            elif tool == "create_presentation":
                title       = args.get("title", "Presentación")
                topic       = args.get("topic", title)
                slide_count = int(args.get("slide_count", 10))
                template    = args.get("template", "dark")
                from apps.core.tools.presentation_builder import PresentationBuilder
                r = await PresentationBuilder().create_presentation(title, topic, slide_count, template)
                if r.get("success") and r.get("html_bytes"):
                    fname = r.get("filename", "presentation.html")
                    obs = f"Presentación '{title}' generada: {r['slide_count']} slides"
                    return obs, {"document_bytes": r["html_bytes"], "document_filename": fname}
                return "No se pudo generar la presentación", {}

            elif tool == "create_pitch_deck":
                company  = args.get("company", "")
                problem  = args.get("problem", "")
                solution = args.get("solution", "")
                market   = args.get("market", "")
                traction = args.get("traction", "")
                from apps.core.tools.presentation_builder import PresentationBuilder
                r = await PresentationBuilder().create_pitch_deck(company, problem, solution, market, traction)
                if r.get("success") and r.get("html_bytes"):
                    fname = r.get("filename", "pitch_deck.html")
                    obs = f"Pitch deck '{company}' generado: {r['slide_count']} slides"
                    return obs, {"document_bytes": r["html_bytes"], "document_filename": fname}
                return "No se pudo generar el pitch deck", {}

            # ── MULTIMODAL ────────────────────────────────────────────────
            elif tool == "analyze_image":
                url      = args.get("url", "")
                question = args.get("question", "Describe esta imagen en detalle.")
                from apps.core.tools.multimodal import get_multimodal
                r = await get_multimodal().analyze_image(image_url=url, question=question)
                if r.get("success"):
                    return f"[ANÁLISIS DE IMAGEN]\n{r['analysis']}", {}
                return f"No pude analizar la imagen: {r.get('error', 'error desconocido')}", {}

            elif tool == "extract_text":
                url = args.get("url", "")
                from apps.core.tools.multimodal import get_multimodal
                r = await get_multimodal().extract_text(image_url=url)
                if r.get("success"):
                    return f"[OCR]\n{r['analysis']}", {}
                return f"No pude extraer texto: {r.get('error', 'error desconocido')}", {}

            elif tool == "edit_image":
                url         = args.get("url", "")
                instruction = args.get("instruction", "")
                from apps.core.tools.multimodal import get_multimodal
                r = await get_multimodal().edit_image(image_url=url, instruction=instruction)
                if r.get("success") and r.get("image_bytes"):
                    return f"Imagen editada: '{instruction}'", {"image_bytes": r["image_bytes"]}
                return f"No pude editar la imagen: {r.get('error', 'error desconocido')}", {}

            elif tool == "analyze_video":
                url      = args.get("url", "")
                question = args.get("question", "Describe este video en detalle.")
                from apps.core.tools.multimodal import get_multimodal
                r = await get_multimodal().analyze_video_url(url, question)
                if r.get("success"):
                    frames = r.get("frames_analyzed", 0)
                    return f"[ANÁLISIS DE VIDEO — {frames} frames]\n{r['analysis']}", {}
                return f"No pude analizar el video: {r.get('error', 'error desconocido')}", {}

            # ── BACKGROUND TASKS ─────────────────────────────────────────
            elif tool == "run_background":
                task_name  = args.get("task", "")
                agent_name = args.get("agent", "ceo")
                from apps.core.tools.task_manager import get_task_manager
                from apps.core.agents.business_hub import BusinessHub

                async def _bg():
                    return await BusinessHub().dispatch(agent_name, task_name, {})

                mgr     = get_task_manager()
                task_id = await mgr.submit(
                    name=task_name,
                    coro=_bg(),
                    description=f"{agent_name}: {task_name}",
                    session_id=None,
                )
                return f"Tarea '{task_name}' iniciada en segundo plano (ID: {task_id}). Te avisaré cuando termine.", {}

            elif tool == "task_status":
                task_id = args.get("task_id", "")
                from apps.core.tools.task_manager import get_task_manager
                mgr = get_task_manager()
                if task_id:
                    record = mgr.get_task(task_id)
                    if record:
                        return f"[Tarea {task_id}] {record.status.value}: {record.result or record.error or 'en progreso'}", {}
                    return f"Tarea {task_id} no encontrada.", {}
                tasks = mgr.list_tasks(limit=10)
                if not tasks:
                    return "No hay tareas en segundo plano.", {}
                lines = [f"• [{t['id']}] {t['status']} — {t['name']}" for t in tasks]
                return "[TAREAS EN SEGUNDO PLANO]\n" + "\n".join(lines), {}

            # ── KNOWLEDGE BASE (RAG) ──────────────────────────────────────
            elif tool == "learn":
                source   = args.get("source", "")
                category = args.get("category", "general")
                is_url   = args.get("is_url", source.startswith("http"))
                from apps.core.tools.knowledge_base import get_knowledge_base
                kb = get_knowledge_base()
                if is_url:
                    r = await kb.ingest_url(source, category=category)
                else:
                    r = await kb.ingest_text(source, source=category, category=category)
                if r.get("success"):
                    return (f"✅ Aprendido: {r['chunks_added']} fragmentos de '{source[:60]}' "
                            f"(total en KB: {r['total_chunks']})"), {}
                return f"No pude aprender esa fuente: {r.get('error', 'error')}", {}

            elif tool == "search_knowledge":
                query = args.get("query", "")
                top_k = int(args.get("top_k", 5))
                from apps.core.tools.knowledge_base import get_knowledge_base
                formatted = await get_knowledge_base().search_formatted(query, top_k=top_k)
                if formatted:
                    return formatted, {}
                return "No encontré información relevante en la base de conocimiento. Prueba a usar 'learn' primero.", {}

            elif tool == "forget_source":
                source = args.get("source", "")
                from apps.core.tools.knowledge_base import get_knowledge_base
                deleted = get_knowledge_base().delete_source(source)
                return f"Eliminados {deleted} fragmentos de '{source}' de la base de conocimiento.", {}

            # ── MULTI-AGENT CREW ──────────────────────────────────────────
            elif tool == "run_crew":
                mission    = args.get("mission", "")
                crew_name  = args.get("crew", "research_crew")
                from apps.core.tools.crew_engine import get_crew_engine
                from apps.core.tools.deep_think import ProgressStream

                ps = ProgressStream(session_id="", task_name=f"Crew:{crew_name}")
                run = await get_crew_engine().run(
                    mission=mission,
                    crew_name=crew_name,
                    on_progress=lambda step, total, role: ps.update(
                        f"{role} trabajando...", f"Paso {step}/{total}"
                    ),
                )
                members_summary = " → ".join(m.role for m in run.members)
                obs = (
                    f"[CREW: {crew_name.upper()} — {members_summary}]\n\n"
                    f"{run.final_output or 'Sin output final'}"
                )
                return obs, {}

            # ── WORKFLOW ENGINE ───────────────────────────────────────────
            elif tool == "create_workflow":
                name        = args.get("name", "Workflow")
                description = args.get("description", "")
                from apps.core.tools.workflow_engine import get_workflow_engine
                r = await get_workflow_engine().create(name, description)
                if r.get("success"):
                    steps_str = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(r.get("steps_preview", [])))
                    return (f"✅ Workflow '{name}' creado (ID: {r['workflow_id']}, {r['steps']} pasos):\n"
                            f"{steps_str}\n\nUsa run_workflow con id='{r['workflow_id']}' para ejecutarlo."), {}
                return f"No pude crear el workflow: {r.get('error', 'error')}", {}

            elif tool == "run_workflow":
                wid = args.get("workflow_id", "")
                from apps.core.tools.workflow_engine import get_workflow_engine
                r = await get_workflow_engine().run(wid)
                if r.get("success"):
                    steps_summary = "; ".join(
                        f"paso{s['step']}={'OK' if s['success'] else 'FAIL'}"
                        for s in r.get("results", [])
                    )
                    return (f"[WORKFLOW '{r.get('name', wid)}' — {r['steps_run']} pasos]\n"
                            f"{steps_summary}\n\n{r.get('final_output', '')}"), {}
                return f"Error ejecutando workflow: {r.get('error', 'error')}", {}

            elif tool == "list_workflows":
                from apps.core.tools.workflow_engine import get_workflow_engine
                wfs = get_workflow_engine().list()
                if not wfs:
                    return "No hay workflows guardados. Usa create_workflow para crear uno.", {}
                lines = [f"• [{w['id']}] **{w['name']}** — {w['description'][:60]} (runs: {w['run_count']})" for w in wfs]
                return "[WORKFLOWS]\n" + "\n".join(lines), {}

            # ── THINK VERIFIED (Test-Time Compute) ────────────────────────
            elif tool == "think_verified":
                question = args.get("question", "")
                context  = args.get("context", "")
                from apps.core.tools.deep_think import get_deep_think
                result = await get_deep_think().think_verified(question, context=context, paths=2)
                obs = f"[RAZONAMIENTO VERIFICADO — {result.depth.upper()} — {result.duration_ms}ms]\n{result.answer}"
                return obs, {}

            # ── NICHE REVENUE ENGINE ─────────────────────────────────────
            elif tool == "launch_niche":
                niche   = args.get("niche", "")
                context = args.get("context", "")
                if not niche:
                    from apps.core.tools.niche_revenue_engine import get_niche_revenue_engine
                    top5 = get_niche_revenue_engine().get_top_niches_by_potential(n=3)
                    names = [n["key"] for n in top5]
                    return (f"Especifica un nicho. Top 3 recomendados ahora mismo: {', '.join(names)}\n"
                            f"Usa list_niches para ver todos los 45 disponibles."), {}
                from apps.core.tools.niche_revenue_engine import get_niche_revenue_engine, NICHE_CATALOG
                if niche not in NICHE_CATALOG:
                    close = [k for k in NICHE_CATALOG if niche.lower() in k.lower()]
                    return (f"Nicho '{niche}' no encontrado."
                            + (f" ¿Quisiste decir: {', '.join(close[:3])}?" if close else "")), {}
                result = await get_niche_revenue_engine().launch_niche(niche, context=context)
                lines = [
                    f"[LAUNCH: {result.niche_name}]",
                    f"Checklist: {result.checklist.score}/100 {'✅' if result.checklist and result.checklist.passed else '⚠️'}",
                    f"Tiempo: {result.elapsed_seconds}s",
                ]
                if result.published_urls:
                    lines.append("**Publicado en:**")
                    for u in result.published_urls:
                        lines.append(f"  • {u['platform']}: {u['url']}")
                if result.seo_article_urls:
                    lines.append("**Artículos SEO:**")
                    for u in result.seo_article_urls:
                        lines.append(f"  • {u['platform']}: {u['url']}")
                if result.errors:
                    lines.append(f"Advertencias: {'; '.join(result.errors[:3])}")
                if result.listing:
                    lines.append(f"\n**Listing:** {result.listing.title}")
                    lines.append(f"Precio: ${result.listing.pricing_tiers['basic']['price']} – ${result.listing.pricing_tiers['premium']['price']}")
                return "\n".join(lines), {}

            elif tool == "income_dashboard":
                from apps.core.tools.niche_revenue_engine import get_niche_revenue_engine
                return await get_niche_revenue_engine().income_dashboard(), {}

            elif tool == "list_niches":
                category = args.get("category", None)
                tier     = args.get("tier", None)
                from apps.core.tools.niche_revenue_engine import get_niche_revenue_engine
                return get_niche_revenue_engine().list_all_niches(category=category, tier=tier), {}

            elif tool == "auto_income":
                num_niches = int(args.get("num_niches", 3))
                from apps.core.tools.niche_revenue_engine import get_niche_revenue_engine
                result = await get_niche_revenue_engine().autonomous_income_cycle(num_niches=num_niches)
                lines = [
                    f"[AUTO INCOME CYCLE]",
                    f"Nichos intentados: {result['niches_attempted']}",
                    f"Nichos exitosos: {result['niches_succeeded']}",
                    f"Listings en vivo: {result['total_listings_live']}",
                    f"Artículos publicados: {result['total_content_published']}",
                    f"Tiempo: {result['elapsed_seconds']}s",
                ]
                if result.get("all_live_urls"):
                    lines.append("\n**URLs activas:**")
                    for u in result["all_live_urls"][:8]:
                        lines.append(f"  • {u.get('platform')}: {u.get('url')}")
                if result.get("successful_niches"):
                    lines.append("\n**Nichos lanzados:**")
                    for n in result["successful_niches"]:
                        lines.append(f"  ✅ {n['niche']} — potencial ${n.get('revenue_potential',0)}/sale")
                if result.get("failed_niches"):
                    lines.append("\n**Nichos con errores:**")
                    for n in result["failed_niches"]:
                        lines.append(f"  ⚠️ {n['niche']}: {', '.join(n.get('errors',[])[:2])}")
                return "\n".join(lines), {}

            # ── INVESTOR PIPELINE ─────────────────────────────────────────
            elif tool == "investor_pipeline":
                import json as _json
                from apps.core.memory.redis_client import get_cache
                cache = get_cache()
                lines = ["📊 <b>PIPELINE DE INVERSIÓN — ARIA</b>\n"]
                if cache:
                    # Investor deck
                    investor_raw = await cache.get("aria:investor:latest_deck")
                    if investor_raw:
                        deck = _json.loads(investor_raw) if isinstance(investor_raw, str) else investor_raw
                        ask = deck.get("ask", 0)
                        url = deck.get("url", "")
                        ts  = deck.get("ts", "")
                        lines.append(f"<b>🚀 Último Pitch Deck</b>")
                        lines.append(f"  Ask: ${ask:,.0f}  |  {ts}")
                        if url:
                            lines.append(f"  <a href=\"{url}\">Ver deck →</a>")
                    else:
                        lines.append("<i>No se ha generado un pitch deck aún.</i>")
                        lines.append("Ejecuta: <code>run_income_cycle strategy=vc_pitch_deck</code>")
                    lines.append("")
                    # Grants
                    grant_potential = float(await cache.get("aria:grants:total_potential") or 0)
                    raw_grants = await cache.lrange("aria:grants:applications", -3, -1)
                    grants = []
                    for r in (raw_grants or []):
                        try:
                            grants.append(_json.loads(r) if isinstance(r, str) else r)
                        except Exception:
                            pass
                    if grants:
                        lines.append(f"<b>💰 Grants Identificados</b>")
                        lines.append(f"  Potencial total: ${grant_potential:,.0f}")
                        for g in grants[-2:]:
                            best = g.get("best", "—")
                            count = g.get("count", 0)
                            lines.append(f"  • {best} ({count} aplicaciones)")
                    else:
                        lines.append("<i>No se han preparado aplicaciones de grants aún.</i>")
                        lines.append("Ejecuta: <code>run_income_cycle strategy=micro_grant_hunter</code>")
                    lines.append("")
                    lines.append("<i>ARIA ejecuta vc_pitch_deck y micro_grant_hunter automáticamente cada ciclo.</i>")
                else:
                    lines.append("⚠️ Redis no disponible — sin datos de pipeline")
                return "\n".join(lines), {}

            # ── INCOME LOOP 24/7 ──────────────────────────────────────────
            elif tool == "income_loop_status":
                from apps.core.tools.income_loop import get_income_loop
                return await get_income_loop().get_status(), {}

            elif tool == "start_income_loop":
                from apps.core.tools.income_loop import get_income_loop
                loop = get_income_loop()
                if loop.is_running:
                    return "El income loop 24/7 ya está corriendo. Usa income_loop_status para ver su estado.", {}
                await loop.start()
                return "✅ Income loop 24/7 iniciado. Ejecutará estrategias de ingresos cada 30 minutos de forma autónoma.", {}

            elif tool == "run_income_cycle":
                from apps.core.tools.income_loop import get_income_loop, STRATEGIES
                loop      = get_income_loop()
                strategy  = args.get("strategy", "")
                valid     = [s[0] for s in STRATEGIES]
                if strategy and strategy not in valid:
                    return f"Estrategia inválida. Opciones: {', '.join(valid)}", {}
                import random as _rnd
                if not strategy:
                    strategy = _rnd.choices([s[0] for s in STRATEGIES],
                                            weights=[s[1] for s in STRATEGIES], k=1)[0]
                obs = await loop._execute(strategy)
                lines = [
                    f"[INCOME CYCLE — {strategy}]",
                    f"Success: {'✅' if obs.get('success') else '❌'}",
                    f"Summary: {obs.get('summary', '')}",
                    f"Revenue potential: ${obs.get('revenue_potential', 0):.0f}",
                ]
                if obs.get("urls"):
                    lines.append("URLs:")
                    for u in obs["urls"][:4]:
                        lines.append(f"  • {u}")
                return "\n".join(lines), {}

            # ── GITHUB ───────────────────────────────────────────────────
            elif tool in ("github_view", "github_write", "github_pr",
                          "github_issues", "github_search", "github_self"):
                from apps.core.tools.github_client import github_dispatch
                action_map = {
                    "github_view":   args.get("action", "view"),
                    "github_write":  "write",
                    "github_pr":     args.get("action", "create_pr"),
                    "github_issues": args.get("action", "issues"),
                    "github_search": "search",
                    "github_self":   "self",
                }
                gh_action = action_map[tool]
                obs = await github_dispatch(gh_action, args)
                return obs, {}

            # ── DAILY BUSINESS CYCLE ──────────────────────────────────────
            elif tool == "run_daily_cycle":
                from apps.runtime.daily_business_loop import get_daily_business_loop
                loop = get_daily_business_loop()
                report = await loop.run()
                lines = [
                    f"[CICLO DIARIO — {report.date}]",
                    f"Operaciones: {report.ops_completed}/{report.ops_total} ✅  ({report.ops_failed} ❌)",
                    f"Score de ejecución: {report.execution_score:.0%}",
                    f"Contenido generado: {report.content_pieces_generated}",
                    f"Leads descubiertos: {report.leads_discovered}",
                    f"Outreach enviado: {report.outreach_sent}",
                    f"Optimizaciones Shopify: {report.shopify_optimizations}",
                    f"Funnels optimizados: {report.funnels_optimized}",
                ]
                if report.top_insight:
                    lines.append(f"\n💡 Insight: {report.top_insight}")
                if report.tomorrow_priority:
                    lines.append(f"🎯 Prioridad mañana: {report.tomorrow_priority}")
                return "\n".join(lines), {}

            elif tool == "daily_report":
                from apps.runtime.daily_business_loop import get_daily_business_loop
                loop = get_daily_business_loop()
                await loop._load()
                reports = loop.recent_reports(limit=1)
                if not reports:
                    status = await loop.generate_status_report()
                    return (f"[ESTADO HOY — {status['date']}]\n"
                            f"Ops completadas: {status['ops_done']}/{status['ops_today']}\n"
                            f"Score: {status['execution_score']:.0%}\n"
                            f"Total reportes históricos: {status['total_reports']}"), {}
                r = reports[0]
                lines = [
                    f"[REPORTE — {r.get('date', 'hoy')}]",
                    f"Score: {r.get('execution_score', 0):.0%}  ({r.get('ops_completed', 0)}/{r.get('ops_total', 0)} ops)",
                    f"Contenido: {r.get('content_pieces_generated', 0)} piezas  |  Leads: {r.get('leads_discovered', 0)}",
                    f"Outreach: {r.get('outreach_sent', 0)}  |  Shopify: {r.get('shopify_optimizations', 0)}",
                ]
                if r.get("top_insight"):
                    lines.append(f"💡 {r['top_insight']}")
                if r.get("tomorrow_priority"):
                    lines.append(f"🎯 Mañana: {r['tomorrow_priority']}")
                return "\n".join(lines), {}

            # ── ACQUISITION (LEADS + CRM OUTREACH) ───────────────────────
            elif tool == "run_acquisition":
                niche = args.get("niche", "ecommerce")
                count = int(args.get("count", 10))
                from apps.acquisition.leads.lead_engine import get_lead_engine
                from apps.acquisition.outreach.outreach_sequencer import get_outreach_sequencer
                eng = get_lead_engine()
                leads = await eng.discover_leads(niche, count=count)
                sequencer = get_outreach_sequencer()
                await sequencer._load()
                due = sequencer.contacts_due_today()[:10]
                advanced = 0
                for c in due:
                    if sequencer.advance_contact(c.get("contact_id", "")):
                        advanced += 1
                if advanced > 0:
                    await sequencer._save()
                return (f"[ADQUISICIÓN]\n"
                        f"Leads descubiertos en '{niche}': {len(leads)}\n"
                        f"Contactos avanzados en CRM: {advanced}/{len(due)}"), {}

            # ── RETENTION ────────────────────────────────────────────────
            elif tool == "run_retention":
                from apps.business.crm.retention import get_retention_engine
                from apps.business.crm.crm_engine import get_crm_engine
                engine = get_retention_engine()
                crm = get_crm_engine()
                at_risk = await crm.high_risk_customers()
                candidates = await crm.retention_candidates()
                all_customers = list({c.customer_id: c for c in at_risk + candidates}.values())
                customer_dicts = [
                    {
                        "email": c.email,
                        "name": c.name,
                        "segment": (c.segments[0] if c.segments else ""),
                        "total_spent_usd": c.total_spent_usd,
                        "last_purchase_ts": c.last_purchase_ts,
                        "churn_risk": c.churn_risk.value if hasattr(c.churn_risk, "value") else str(c.churn_risk),
                    }
                    for c in all_customers[:100]
                ]
                win_back = await engine.run_win_back(customer_dicts)
                loyalty = await engine.run_loyalty_rewards(customer_dicts)
                summary = await engine.campaign_summary()
                return (f"[RETENCIÓN]\n"
                        f"Clientes en riesgo analizados: {len(at_risk)}\n"
                        f"Win-back targets: {win_back.get('targeted', 0)}\n"
                        f"Loyalty reward targets: {loyalty.get('targeted', 0)}\n"
                        f"Campañas activas totales: {summary.get('active_campaigns', 0)}\n"
                        f"Revenue recuperado total: ${summary.get('total_recovered_revenue', 0):.2f}"), {}

            # ── SHOPIFY OPTIMIZE ──────────────────────────────────────────
            elif tool == "shopify_optimize":
                operation = args.get("operation", "seo")
                if operation == "seo":
                    from apps.shopify.seo.product_seo import get_product_seo_optimizer
                    eng = get_product_seo_optimizer()
                    await eng._load()
                    stats = eng.seo_stats()
                    return f"[SHOPIFY SEO]\n{stats}", {}
                elif operation == "bundles":
                    from apps.shopify.bundles.bundle_generator import get_bundle_generator
                    eng = get_bundle_generator()
                    await eng._load()
                    stats = eng.bundle_stats() if hasattr(eng, "bundle_stats") else {"status": "loaded"}
                    return f"[SHOPIFY BUNDLES]\n{stats}", {}
                elif operation == "flash_sale":
                    from apps.shopify.offers.flash_sale_engine import get_flash_sale_engine
                    eng = get_flash_sale_engine()
                    await eng._load()
                    stats = eng.sale_stats() if hasattr(eng, "sale_stats") else {"status": "loaded"}
                    return f"[SHOPIFY FLASH SALE]\n{stats}", {}
                return f"Operación Shopify desconocida: {operation}. Usa seo|bundles|flash_sale", {}

            # ── CONVERSION FUNNELS ────────────────────────────────────────
            elif tool == "run_funnel":
                from apps.conversion.funnels.funnel_engine import get_funnel_engine
                from apps.conversion.email_sequences.email_nurture import get_email_nurture_engine
                funnel_eng = get_funnel_engine()
                await funnel_eng._load()
                analytics = funnel_eng.funnel_analytics()
                email_eng = get_email_nurture_engine()
                await email_eng._load()
                email_analytics = email_eng.sequence_analytics()
                return (f"[FUNNELS DE CONVERSIÓN]\n{analytics}\n\n"
                        f"[SECUENCIAS EMAIL]\n{email_analytics}"), {}

            # ── AUTONOMOUS OBJECTIVES ─────────────────────────────────────
            elif tool == "check_objectives":
                from apps.runtime.autonomy.autonomous_scheduler import get_autonomous_scheduler
                scheduler = get_autonomous_scheduler()
                objs = await scheduler.get_objectives()
                summary = scheduler.summary()
                lines = [
                    f"[OBJETIVOS ESTRATÉGICOS — {summary['active']} activos / {summary['total_objectives']} total]",
                    f"Valor total generado: ${summary['total_value_generated_usd']:.2f}",
                    f"Tasa de éxito global: {summary['success_rate_overall']:.0%}",
                    "",
                ]
                import time as _time
                for obj in sorted(objs, key=lambda o: o.priority):
                    due_in = max(0, obj.next_run_ts - _time.time())
                    due_str = f"vence en {due_in/3600:.1f}h" if due_in > 0 else "VENCE AHORA"
                    lines.append(
                        f"• [{obj.status.value.upper()}] {obj.name} (c/{obj.frequency_hours}h) — "
                        f"runs: {obj.total_runs} | ok: {obj.success_count} | "
                        f"${obj.total_value_usd:.0f} | {due_str}"
                    )
                return "\n".join(lines), {}

            # ── HUMAN BROWSER (STEALTH) ───────────────────────────────────
            elif tool == "human_login":
                from apps.core.config import settings
                platform = args.get("platform", "")
                email    = args.get("email") or getattr(settings, "ARIA_EMAIL", "")
                password = args.get("password") or getattr(settings, "ARIA_PASSWORD", "")
                username = args.get("username", "")
                if not email or not password:
                    return "Necesito email y password. Agrega ARIA_EMAIL y ARIA_PASSWORD como secrets.", {}
                from apps.core.tools.human_browser import get_platform_login
                pl = await get_platform_login()
                login_map = {
                    "gumroad":  pl.gumroad,
                    "devto":    pl.devto,
                    "linkedin": pl.linkedin,
                    "twitter":  lambda e, p: pl.twitter(e, p, username),
                    "hashnode": pl.hashnode,
                    "medium":   pl.medium,
                }
                fn = login_map.get(platform.lower())
                if not fn:
                    return f"Plataforma desconocida: {platform}. Opciones: gumroad, devto, linkedin, twitter, hashnode, medium", {}
                page = await fn(email, password)
                return (f"[STEALTH LOGIN — {platform.upper()}]\n"
                        f"URL actual: {page.url}\n"
                        f"Sesión guardada para uso futuro."), {}

            elif tool == "human_browse":
                url     = args.get("url", "")
                session = args.get("session", "default")
                from apps.core.tools.human_browser import get_human_browser
                browser = await get_human_browser()
                page = await browser.new_page(session)
                await page.load_session()
                await page.goto(url)
                text = await page.get_page_text(max_chars=3000)
                title = await page.evaluate("() => document.title")
                return f"[STEALTH PAGE: {title}]\nURL: {page.url}\n\n{text}", {}

            elif tool == "human_action":
                session = args.get("session", "default")
                steps   = args.get("steps", [])
                from apps.core.tools.human_browser import get_human_browser
                browser = await get_human_browser()
                page = await browser.new_page(session)
                await page.load_session()
                results = []
                for step in steps:
                    action   = step.get("action", "")
                    selector = step.get("selector", "")
                    value    = step.get("value", "")
                    pixels   = int(step.get("pixels", 300))
                    try:
                        if action == "click":
                            await page.click(selector)
                            results.append(f"click({selector}): OK")
                        elif action == "type":
                            await page.type_human(selector, value)
                            results.append(f"type({selector}, '{value[:20]}...'): OK")
                        elif action == "scroll":
                            await page.scroll_down(pixels)
                            results.append(f"scroll({pixels}px): OK")
                        elif action == "wait":
                            await asyncio.sleep(float(value or 1))
                            results.append(f"wait({value}s): OK")
                        elif action == "get_text":
                            text = await page.get_text(selector) if selector else await page.get_page_text()
                            results.append(f"text: {text[:300]}")
                        elif action == "screenshot":
                            await page.screenshot()
                            results.append("screenshot: taken")
                        elif action == "goto":
                            await page.goto(value)
                            results.append(f"goto({value}): OK")
                        elif action == "save_session":
                            await page.save_session()
                            results.append("session: saved")
                        else:
                            results.append(f"{action}: unknown")
                    except Exception as exc:
                        results.append(f"{action}: FAIL — {str(exc)[:80]}")
                return f"[STEALTH ACTIONS — {session}]\n" + "\n".join(results), {}

            elif tool == "diagnose_income":
                from apps.core.tools.income_loop import get_income_loop
                loop = get_income_loop()
                creds = loop.check_credentials()
                active   = creds.get("active", {})
                inactive = creds.get("inactive", {})
                lines = [
                    "**DIAGNÓSTICO DE CANALES DE INGRESOS**",
                    "",
                    f"✅ Canales ACTIVOS ({len(active)}):",
                ]
                for ch, info in active.items():
                    channels = ", ".join(info.get("revenue_channels", [])[:2])
                    lines.append(f"  • {ch}: {channels}")
                lines += ["", f"❌ Canales INACTIVOS ({len(inactive)}) — necesitan credenciales:"]
                for ch, info in inactive.items():
                    keys = ", ".join(info.get("keys_needed", []))
                    channels = ", ".join(info.get("revenue_channels", [])[:2])
                    lines.append(f"  • {ch} ({channels})")
                    lines.append(f"    → Añade en Fly.io: fly secrets set {keys.replace(', ', '=... ')}=...")
                lines += [
                    "",
                    "**🥇 Canal más rentable — Gumroad (venta digital):**",
                    "1. Ve a gumroad.com → Settings → Advanced → API",
                    "2. Copia tu Access Token",
                    "3. `fly secrets set GUMROAD_TOKEN=tu_token -a aria-ai`",
                    "",
                    "**🍋 Alternativa a Gumroad — LemonSqueezy (5%+$0.50 fees, más moderno):**",
                    "1. Crea cuenta en app.lemonsqueezy.com",
                    "2. Settings → API → Create API Key",
                    "3. Settings → General → copia tu Store ID",
                    "4. `fly secrets set LEMONSQUEEZY_API_KEY=tu_key LEMONSQUEEZY_STORE_ID=tu_id -a aria-ai`",
                    "",
                    "**📝 Para publicar artículos (Dev.to — gratis, rápido, tráfico real):**",
                    "1. Ve a dev.to/settings/extensions",
                    "2. Genera un API key",
                    "3. `fly secrets set DEVTO_API_KEY=tu_key -a aria-ai`",
                    "",
                    "**💰 Para ingresos de afiliado SIN API (solo un tag de texto):**",
                    "`fly secrets set AMAZON_ASSOCIATE_TAG=tu-tag-20 -a aria-ai`",
                    "→ ARIA publica artículos de review con tus links de afiliado en GitHub (ya activo si GITHUB_TOKEN está configurado)",
                    "",
                    "**🔔 Para notificaciones en Discord cuando se publique contenido:**",
                    "`fly secrets set DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... -a aria-ai`",
                    "",
                    "**🐦 Para distribución automática en Twitter/X via Zapier:**",
                    "`fly secrets set ZAPIER_WEBHOOK_URL=https://hooks.zapier.com/hooks/catch/... -a aria-ai`",
                    "",
                    "**📰 Para cross-posting en Hashnode (tech blog con gran audiencia):**",
                    "1. hashnode.com → Settings → Developer → API Keys → New Token",
                    "2. Tu Publication ID está en hashnode.com/dashboard (URL del blog)",
                    "3. `fly secrets set HASHNODE_TOKEN=tu_token HASHNODE_PUBLICATION_ID=tu_pub_id -a aria-ai`",
                    "",
                    "**🤗 Para demos de IA en HuggingFace Spaces (millones de visitantes de comunidad IA — GRATIS):**",
                    "1. huggingface.co → Settings → Access Tokens → New token (role: write)",
                    "2. `fly secrets set HF_TOKEN=hf_tu_token -a aria-ai`",
                    "→ ARIA crea Spaces de Gradio con demos interactivos que generan tráfico y posicionamiento",
                    "",
                    "**💳 Para cobros reales vía Stripe (checkout links instantáneos):**",
                    "1. stripe.com → Dashboard → Developers → API keys",
                    "2. Copia la Secret key (sk_live_...)",
                    "3. `fly secrets set STRIPE_SECRET_KEY=sk_live_... -a aria-ai`",
                    "→ ARIA crea productos y genera checkout links reales que tus clientes pueden pagar",
                    "",
                    "**🐦 Para publicar en Twitter/X directamente (sin Zapier):**",
                    "1. developer.twitter.com → Create App → Keys and tokens",
                    "2. Genera API Key + API Secret + Access Token + Access Token Secret",
                    "3. `fly secrets set TWITTER_API_KEY=... TWITTER_API_SECRET=... TWITTER_ACCESS_TOKEN=... TWITTER_ACCESS_SECRET=... -a aria-ai`",
                    "→ ARIA publica threads virales en X automáticamente con las estrategias twitter_thread",
                    "",
                    "**💼 Para publicar en LinkedIn directamente (posts de alto engagement B2B):**",
                    "1. linkedin.com/developers → Create App → Auth → OAuth 2.0 tokens",
                    "2. Genera Access Token con permisos: w_member_social, r_liteprofile",
                    "3. Tu Person URN: linkedin.com/in/tu-perfil → inspeccionar → busca 'id'",
                    "4. `fly secrets set LINKEDIN_ACCESS_TOKEN=... LINKEDIN_PERSON_URN=urn:li:person:XXXXX -a aria-ai`",
                    "→ ARIA publica posts de liderazgo de pensamiento en LinkedIn para leads B2B",
                    "",
                    "**🟠 Para publicar en Reddit orgánicamente (tráfico masivo gratuito):**",
                    "1. reddit.com/prefs/apps → Create App (tipo: script)",
                    "2. Obtén Client ID (debajo del nombre) + Client Secret",
                    "3. Genera refresh token via OAuth2 flow",
                    "4. `fly secrets set REDDIT_CLIENT_ID=... REDDIT_CLIENT_SECRET=... REDDIT_REFRESH_TOKEN=... REDDIT_USERNAME=tu_usuario -a aria-ai`",
                    "→ ARIA publica contenido de valor en subreddits relevantes con links a tus productos",
                    "",
                    "**▶️ Para estrategia de YouTube (scripts, SEO, calendarios de contenido + AdSense):**",
                    "1. console.cloud.google.com → APIs → YouTube Data API v3 → Crear credencial",
                    "2. Genera API Key",
                    "3. `fly secrets set YOUTUBE_API_KEY=AIza... -a aria-ai`",
                    "→ ARIA genera scripts completos, metadata SEO optimizada, calendarios de 4 semanas y planes de monetización para tu canal",
                    "→ Sin YOUTUBE_API_KEY, ARIA igual genera todo el contenido y lo archiva en GitHub (funciona siempre)",
                    "",
                    "**🚀 Para lanzamientos en Product Hunt (5k-50k visitantes en 1 día):**",
                    "→ No requiere API key — ARIA genera el kit completo de lanzamiento:",
                    "  Tagline, descripción, primer comentario del maker, DM para hunters, checklist de lanzamiento",
                    "→ Ejecuta: /income_cycle strategy=product_hunt_launch",
                    "",
                    "**📌 Para Pinterest (450M usuarios activos, tráfico SEO visual masivo):**",
                    "1. developers.pinterest.com → Create App → OAuth 2.0 → genera access token",
                    "2. Permisos necesarios: boards:read, pins:read, pins:write",
                    "3. Obtén tu Board ID: ve a tu tablero y copia el ID de la URL",
                    "4. `fly secrets set PINTEREST_ACCESS_TOKEN=... PINTEREST_BOARD_ID=... -a aria-ai`",
                    "→ ARIA crea 5 pins por ciclo con descripciones SEO-optimizadas, keywords y CTAs hacia tus productos",
                    "→ Sin token, ARIA igual genera los conceptos de pins y los archiva en GitHub para que tú los publiques",
                    "",
                    "**📧 Para cold email outreach B2B real (vía SMTP — sin OAuth):**",
                    "1. Consigue un servidor SMTP (Gmail, SendGrid, Mailgun, etc.)",
                    "2. Para Gmail: habilita 'App Passwords' en tu cuenta Google → genera una password de app",
                    "   - SMTP_HOST=smtp.gmail.com, SMTP_PORT=587",
                    "3. Para SendGrid: sendgrid.com → API Keys → Create Key → usa smtp como username",
                    "   - SMTP_HOST=smtp.sendgrid.net, SMTP_PORT=587, SMTP_USER=apikey",
                    "4. `fly secrets set SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=tu@gmail.com SMTP_PASSWORD=tu_app_password SMTP_FROM=tu@gmail.com -a aria-ai`",
                    "→ ARIA genera 5 prospectos B2B realistas con emails completamente personalizados y los envía automáticamente",
                    "→ Sin SMTP, ARIA igual genera las campañas y las archiva en GitHub para que tú las envíes",
                ]
                return "\n".join(lines), {}

            elif tool == "get_income_analytics":
                from apps.core.tools.income_loop import get_income_loop
                loop   = get_income_loop()
                report = await loop.get_analytics_report()
                return report, {}

            elif tool == "get_product_catalog":
                from apps.core.tools.income_loop import get_income_loop
                loop    = get_income_loop()
                limit   = int(args.get("limit", 20))
                catalog = await loop.get_product_catalog(limit=limit)
                return catalog, {}

            elif tool == "get_github_traction":
                from apps.core.tools.github_client import AriaGitHubClient
                from apps.core.config import settings as _s
                gh    = AriaGitHubClient()
                owner = _s.GITHUB_USERNAME or "Geremypolanco"
                aria_repos = [
                    "aria-insights", "aria-portfolio", "aria-free-resources",
                    "aria-newsletter", "aria-ai",
                ]
                traction_lines = [
                    "⭐ <b>GitHub Traction — ARIA Market Presence</b>",
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                ]
                total_stars = 0
                total_forks = 0
                for repo in aria_repos:
                    info = await gh.get_repo(owner, repo)
                    if "error" not in info:
                        s = info.get("stargazers_count", 0)
                        f = info.get("forks_count", 0)
                        w = info.get("watchers_count", 0)
                        total_stars += s
                        total_forks += f
                        url = info.get("html_url", "")
                        traction_lines.append(
                            f"<code>{repo:<28}</code>  ⭐{s}  🍴{f}  👁{w}"
                        )
                        traction_lines.append(f"  <a href='{url}'>{url}</a>")
                    else:
                        traction_lines.append(f"  {repo}: not found yet")
                traction_lines += [
                    "",
                    f"<b>Total stars: {total_stars}  |  Total forks: {total_forks}</b>",
                    f"<i>Tip: share the repos in communities to grow stars → brand authority → sales</i>",
                ]
                return "\n".join(traction_lines), {}

            elif tool == "setup_portfolio":
                from apps.core.config import settings as _s
                from apps.core.tools.github_client import AriaGitHubClient
                import base64 as _b64
                gh    = AriaGitHubClient()
                owner = _s.GITHUB_USERNAME or "Geremypolanco"
                repo  = "aria-portfolio"
                assoc = getattr(_s, "AMAZON_ASSOCIATE_TAG", None) or ""
                if not _s.GITHUB_TOKEN:
                    return "GITHUB_TOKEN no configurado. Añádelo en Fly.io secrets para crear el portfolio.", {}
                # Ensure repo exists
                existing = await gh._get(f"/repos/{owner}/{repo}")
                if "error" in existing:
                    await gh._post("/user/repos", {
                        "name": repo,
                        "description": "ARIA AI — Autonomous AI Business Platform",
                        "private": False,
                        "auto_init": True,
                        "has_issues": False,
                        "has_wiki": False,
                    })
                    import asyncio as _asyncio
                    await _asyncio.sleep(2)
                    try:
                        await gh._post(f"/repos/{owner}/{repo}/pages", {
                            "source": {"branch": "main", "path": "/"},
                        })
                    except Exception:
                        pass
                aff_section = ""
                if assoc:
                    aff_section = f"""
## 🛒 Recommended Tools (Affiliate)
- [Best AI Productivity Tools](https://amazon.com/s?k=ai+productivity+tools&tag={assoc})
- [Top Developer Equipment](https://amazon.com/s?k=developer+setup+desk&tag={assoc})
- [Business Books](https://amazon.com/s?k=business+entrepreneurship+books&tag={assoc})

*Affiliate disclosure: We earn a commission on purchases at no extra cost to you.*
"""
                readme = f"""# ARIA AI — Autonomous Income Platform

> An AI system that generates income, creates products, publishes content, and grows your business — 24/7, without human intervention.

[![Deployed on Fly.io](https://img.shields.io/badge/deployed-fly.io-purple)](https://aria-ai.fly.dev)
[![Content Blog](https://img.shields.io/badge/blog-aria--insights-blue)](https://github.com/{owner}/aria-insights)

## 🤖 What ARIA Does

- **Content Engine** — Publishes 3+ SEO articles/day to GitHub, Dev.to, Medium
- **Product Factory** — Creates and lists digital products on Gumroad
- **Ebook Factory** — Generates and sells ebooks on trending topics
- **Affiliate Content** — Review articles with Amazon affiliate links
- **Market Intelligence** — Scans for profitable niches every 6 hours
- **Morning Briefing** — Daily Telegram summary of overnight results

## 📊 Active Income Strategies (13 total)

| Strategy | Weight | Description |
|----------|--------|-------------|
| Content Pipeline | 18% | SEO articles on trending topics → Dev.to/Medium/GitHub |
| Niche Rotator | 15% | Launches new revenue niches in catalog |
| Product Factory | 13% | Creates & lists digital products on Gumroad |
| Opportunity Scan | 9% | Web research for profitable niches → fills queue |
| GitHub Publish | 8% | Open-source resources → SEO + authority building |
| Shopify Listing | 7% | Digital products on Shopify storefront |
| Email Campaign | 7% | Mailchimp campaigns to email list |
| Affiliate Content | 6% | Review articles with Amazon affiliate links |
| Ebook Factory | 6% | AI-generated ebooks at $7-$27 on Gumroad |
| Lead Magnet | 5% | Free resources → email capture → upsell funnel |
| Social Blitz | 4% | Multi-platform distribution via Zapier |
| Premium Offer | 1% | High-ticket B2B consulting ($500-$5,000) |
| Viral Thread | 1% | Twitter/X threads → virality → traffic |

## 📚 Published Content

See all articles: [aria-insights](https://github.com/{owner}/aria-insights)

## 🚀 Technology Stack

- **AI Engine**: Qwen 2.5 72B → Groq LLaMA 3.3 70B → OpenAI GPT-4o
- **Platform**: FastAPI on Fly.io
- **Automation**: Redis task queue, 24/7 background workers
- **Publishing**: GitHub, Dev.to, Medium, Hashnode
- **Commerce**: Gumroad, Shopify
{aff_section}
## 📬 Contact

Built by ARIA AI. Reach out via [Telegram](https://t.me/) or open an issue.

---
*This portfolio is automatically updated by ARIA AI*
"""
                encoded = _b64.b64encode(readme.encode()).decode()
                existing_file = await gh._get(f"/repos/{owner}/{repo}/contents/README.md")
                sha = existing_file.get("sha", "") if "error" not in existing_file else ""
                put_args: dict = {"message": "docs: update portfolio", "content": encoded}
                if sha:
                    put_args["sha"] = sha
                file_r = await gh._put(f"/repos/{owner}/{repo}/contents/README.md", put_args)
                if "error" not in file_r:
                    url = f"https://github.com/{owner}/{repo}"
                    pages_url = f"https://{owner.lower()}.github.io/{repo}/"
                    return (f"✅ Portfolio creado/actualizado: {url}\n"
                            f"🌐 GitHub Pages (activo en ~2 min): {pages_url}\n"
                            f"📚 Blog de contenido: https://github.com/{owner}/aria-insights"), {}
                return "Error al actualizar el portfolio. Verifica GITHUB_TOKEN en secrets.", {}

            elif tool == "run_objective":
                obj_key = args.get("objective", "content_generation")
                valid_keys = [
                    "growth_loops_cycle", "shopify_optimization", "content_generation",
                    "market_intelligence", "crm_nurture", "economic_rebalancing",
                    "morning_briefing", "product_launch_blitz",
                    "daily_revenue_digest", "bundle_and_waitlist",
                    "challenge_day_sequencer", "partner_outreach_cycle",
                    "proactive_analysis", "social_organic",
                    "strategy_optimizer", "self_improve",
                    "youtube_cycle", "product_hunt_cycle",
                    "trend_detector", "weekly_review",
                    "content_calendar_builder", "competitor_intel",
                ]
                if obj_key not in valid_keys:
                    return (f"Objetivo inválido: '{obj_key}'. "
                            f"Opciones: {', '.join(valid_keys)}"), {}
                from apps.runtime.autonomy.autonomous_scheduler import get_autonomous_scheduler
                scheduler = get_autonomous_scheduler()
                objs = await scheduler.get_objectives()
                target = next((o for o in objs if o.obj_id == obj_key), None)
                if not target:
                    return f"Objetivo '{obj_key}' no encontrado en el scheduler.", {}
                record = await scheduler._run_objective(target)
                all_objs = {o.obj_id: o for o in objs}
                all_objs[target.obj_id] = target
                await scheduler._save_objectives(all_objs)
                status = "✅" if record.success else "❌"
                return (f"[OBJETIVO: {target.name}] {status}\n"
                        f"Output: {record.output}\n"
                        f"Valor: ${record.value_generated_usd:.2f}\n"
                        f"Error: {record.error or 'ninguno'}"), {}

            # ── ANÁLISIS PROACTIVO AUTÓNOMO ───────────────────────────────
            elif tool == "run_proactive_analysis":
                focus = args.get("focus", "all")
                findings: list[str] = ["[ANÁLISIS PROACTIVO AUTÓNOMO]", ""]
                action_taken = ""
                action_value = 0.0

                # 1. Income loop status
                if focus in ("income", "all"):
                    try:
                        from apps.core.tools.income_loop import get_income_loop
                        loop = get_income_loop()
                        status_str = await loop.get_status()
                        findings.append("**INCOME LOOP:**")
                        findings.append(status_str[:600])
                        findings.append("")

                        # Check analytics for underperforming strategies
                        report = await loop.get_analytics_report()
                        findings.append("**ANALÍTICAS DE INGRESOS:**")
                        findings.append(report[:400])
                        findings.append("")
                    except Exception as _e:
                        findings.append(f"Income loop: {_e}")

                # 2. Shopify analysis
                if focus in ("shopify", "all"):
                    try:
                        from apps.shopify.seo.product_seo import get_product_seo_optimizer
                        seo_eng = get_product_seo_optimizer()
                        await seo_eng._load()
                        seo_stats = seo_eng.seo_stats()
                        findings.append("**SHOPIFY SEO:**")
                        findings.append(str(seo_stats)[:400])
                        findings.append("")
                    except Exception as _e:
                        findings.append(f"Shopify SEO: {_e}")

                # 3. Strategic objectives status
                if focus in ("all",):
                    try:
                        from apps.runtime.autonomy.autonomous_scheduler import get_autonomous_scheduler
                        import time as _time
                        scheduler = get_autonomous_scheduler()
                        objs = await scheduler.get_objectives()
                        overdue = [o for o in objs if o.next_run_ts <= _time.time()]
                        upcoming_1h = [o for o in objs if 0 < (o.next_run_ts - _time.time()) <= 3600]
                        if overdue:
                            findings.append(f"**OBJETIVOS VENCIDOS ({len(overdue)}):** " +
                                          ", ".join(o.obj_id for o in overdue[:5]))
                            findings.append("")
                        if upcoming_1h:
                            findings.append(f"**VENCEN EN <1H ({len(upcoming_1h)}):** " +
                                          ", ".join(o.obj_id for o in upcoming_1h[:3]))
                            findings.append("")
                    except Exception as _e:
                        findings.append(f"Objectives: {_e}")
                        overdue = []

                # 4. GitHub traction check
                if focus in ("github", "all"):
                    try:
                        from apps.core.tools.github_client import AriaGitHubClient
                        from apps.core.config import settings as _s
                        gh = AriaGitHubClient()
                        owner = _s.GITHUB_USERNAME or "Geremypolanco"
                        repo_check = await gh._get(f"/repos/{owner}/aria-insights")
                        stars = repo_check.get("stargazers_count", 0)
                        open_issues = repo_check.get("open_issues_count", 0)
                        findings.append(f"**GITHUB aria-insights:** ⭐{stars} | issues:{open_issues}")
                        findings.append("")
                    except Exception as _e:
                        findings.append(f"GitHub: {_e}")

                # 5. Decide best action and execute it
                findings.append("---")
                findings.append("**ACCIÓN EJECUTADA:**")
                try:
                    # Priority: run overdue objective > income cycle > shopify SEO
                    if focus in ("all",) and 'overdue' in dir() and overdue:
                        # Pick highest priority overdue objective
                        best_obj = min(overdue, key=lambda o: o.priority)
                        from apps.runtime.autonomy.autonomous_scheduler import get_autonomous_scheduler
                        scheduler = get_autonomous_scheduler()
                        record = await scheduler._run_objective(best_obj)
                        all_objs_map = {o.obj_id: o for o in objs}
                        all_objs_map[best_obj.obj_id] = best_obj
                        await scheduler._save_objectives(all_objs_map)
                        status_icon = "✅" if record.success else "❌"
                        action_taken = f"Ejecuté objetivo vencido: **{best_obj.name}** {status_icon}"
                        action_value = record.value_generated_usd
                        findings.append(action_taken)
                        findings.append(f"Output: {record.output[:300]}")
                        findings.append(f"Valor: ${action_value:.2f}")
                    elif focus in ("shopify",) or focus == "all":
                        # Run a shopify SEO optimization
                        from apps.core.tools.income_loop import get_income_loop
                        loop = get_income_loop()
                        cycle_result = await loop._execute("shopify_listing")
                        action_taken = f"Ejecuté ciclo de ingresos: **shopify_listing** {'✅' if cycle_result.get('success') else '❌'}"
                        action_value = float(cycle_result.get("revenue_potential", 0))
                        findings.append(action_taken)
                        if cycle_result.get("urls"):
                            for u in cycle_result["urls"][:3]:
                                findings.append(f"  • {u}")
                    else:
                        # Default: run content pipeline
                        from apps.core.tools.income_loop import get_income_loop
                        loop = get_income_loop()
                        cycle_result = await loop._execute("content_pipeline")
                        action_taken = f"Ejecuté ciclo: **content_pipeline** {'✅' if cycle_result.get('success') else '❌'}"
                        action_value = float(cycle_result.get("revenue_potential", 0))
                        findings.append(action_taken)
                        if cycle_result.get("urls"):
                            for u in cycle_result["urls"][:3]:
                                findings.append(f"  • {u}")
                except Exception as _exec_e:
                    findings.append(f"No pude ejecutar acción: {_exec_e}")

                findings.append("")
                findings.append(f"**Revenue generado esta ronda: ${action_value:.2f}**")
                return "\n".join(findings), {}

            # ── VISUAL QUESTION ANSWERING ─────────────────────────────
            elif tool == "visual_qa":
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                question  = args.get("question", "¿Qué hay en esta imagen?")
                if not image_b64:
                    return "Envíame primero una imagen para que pueda responder preguntas sobre ella.", {}
                import base64 as _b64
                image_bytes = _b64.b64decode(image_b64)
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().visual_question_answering(image_bytes, question)
                if r.get("success"):
                    conf = r.get("confidence", 0)
                    ans = r.get("answer", "")
                    return f"[VQA] Pregunta: {question}\nRespuesta: {ans} (confianza: {conf:.0%})", {}
                return r.get("error", "VQA no disponible"), {}

            # ── IMAGE-TO-IMAGE (Diffusion) ────────────────────────────
            elif tool == "image_to_image":
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                prompt    = args.get("prompt", "")
                if not image_b64:
                    return "Envíame primero una imagen para poder transformarla.", {}
                if not prompt:
                    return "Necesito una instrucción de transformación (prompt).", {}
                import base64 as _b64
                image_bytes = _b64.b64decode(image_b64)
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().image_to_image(image_bytes, prompt)
                if r.get("success") and r.get("image_bytes"):
                    return f"Imagen transformada: '{prompt}'", {"image_bytes": r["image_bytes"]}
                return r.get("error", "img2img no disponible"), {}

            # ── ZERO-SHOT IMAGE CLASSIFICATION (CLIP) ────────────────
            elif tool == "classify_image_zero_shot":
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                labels    = args.get("labels", ["cat", "dog", "person", "car", "nature"])
                if not image_b64:
                    return "Envíame primero una imagen para clasificarla.", {}
                import base64 as _b64
                image_bytes = _b64.b64decode(image_b64)
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().zero_shot_classify_image(image_bytes, labels)
                if r.get("success"):
                    top = r.get("top_label", "")
                    score = r.get("top_score", 0)
                    all_scores = ", ".join(f"{x['label']}: {x['score']:.0%}" for x in r.get("all", [])[:5])
                    return f"[CLIP] Categoría más probable: {top} ({score:.0%})\nTodas: {all_scores}", {}
                return r.get("error", "Clasificación CLIP no disponible"), {}

            # ── DOCUMENT QA (LayoutLM) ────────────────────────────────
            elif tool == "document_qa":
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                question  = args.get("question", "")
                if not image_b64:
                    return "Envíame primero el documento o factura como imagen.", {}
                if not question:
                    return "¿Qué quieres saber sobre el documento?", {}
                import base64 as _b64
                image_bytes = _b64.b64decode(image_b64)
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().document_qa(image_bytes, question)
                if r.get("success"):
                    return f"[Document QA] {question}\nRespuesta: {r.get('answer','')} ({r.get('confidence',0):.0%})", {}
                return r.get("error", "Document QA no disponible"), {}

            # ── GENERATE MUSIC (MusicGen) ─────────────────────────────
            elif tool == "generate_music_hf":
                prompt   = args.get("prompt", "relaxing ambient music")
                duration = int(args.get("duration", 15))
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().generate_music(prompt, duration=duration)
                if r.get("success") and r.get("audio_bytes"):
                    ab = r["audio_bytes"]
                    return f"Música generada ({duration}s): '{prompt}'", {"audio_bytes": ab}
                return r.get("error", "MusicGen no disponible"), {}

            # ── DETECT LANGUAGE ───────────────────────────────────────
            elif tool == "detect_language":
                text = args.get("text", "")
                if not text:
                    return "Necesito texto para detectar el idioma.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().detect_language(text)
                if r.get("success"):
                    lang = r.get("language", "?")
                    conf = r.get("confidence", 0)
                    return f"Idioma detectado: {lang} ({conf:.0%} confianza)", {}
                return r.get("error", "Detección de idioma no disponible"), {}

            # ── ANALYZE SENTIMENT ─────────────────────────────────────
            elif tool == "analyze_sentiment":
                text = args.get("text", "")
                if not text:
                    return "Necesito texto para analizar el sentimiento.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().analyze_sentiment(text)
                if r.get("success"):
                    sent = r.get("sentiment", "?")
                    conf = r.get("confidence", 0)
                    all_scores = r.get("all_scores", {})
                    scores_str = " | ".join(f"{k}: {v:.0%}" for k, v in all_scores.items())
                    return f"Sentimiento: **{sent}** ({conf:.0%})\n{scores_str}", {}
                return r.get("error", "Análisis de sentimiento no disponible"), {}

            # ── EXTRACT ENTITIES (NER) ────────────────────────────────
            elif tool == "extract_entities":
                text = args.get("text", "")
                if not text:
                    return "Necesito texto para extraer entidades.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().extract_entities(text)
                if r.get("success") and r.get("entities"):
                    ents = r["entities"]
                    lines = [f"**{k}**: {', '.join(v)}" for k, v in ents.items() if v]
                    return "[NER] Entidades detectadas:\n" + "\n".join(lines), {}
                return r.get("error", "NER no disponible"), {}

            # ── COMPUTE SIMILARITY ────────────────────────────────────
            elif tool == "compute_similarity":
                text1 = args.get("text1", "")
                text2 = args.get("text2", "")
                if not text1 or not text2:
                    return "Necesito text1 y text2 para calcular similaridad.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().compute_similarity(text1, text2)
                if r.get("success"):
                    sim = r.get("similarity", 0)
                    level = "muy similares" if sim > 0.8 else "similares" if sim > 0.6 else "poco similares" if sim > 0.4 else "muy diferentes"
                    return f"Similaridad semántica: {sim:.2%} ({level})", {}
                return r.get("error", "Cálculo de similaridad no disponible"), {}

            # ── VISION LANGUAGE MODEL (Image-Text-to-Text) ───────────
            elif tool == "vision_llm":
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                question  = args.get("question", "Describe esta imagen en detalle.")
                if not image_b64:
                    return "Envíame primero una imagen para analizar.", {}
                import base64 as _b64
                image_bytes = _b64.b64decode(image_b64)
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().vision_language(image_bytes, question)
                if r.get("success"):
                    return f"[Vision LLM]\n{r.get('answer','')}", {}
                return r.get("error", "Vision LLM no disponible"), {}

            # ── IMAGE SEGMENTATION ────────────────────────────────────
            elif tool == "segment_image":
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                if not image_b64:
                    return "Envíame primero una imagen para segmentar.", {}
                import base64 as _b64
                image_bytes = _b64.b64decode(image_b64)
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().segment_image(image_bytes)
                if r.get("success"):
                    labels = r.get("unique_labels", [])
                    count = r.get("count", 0)
                    return f"[Segmentación] {count} segmentos detectados\nObjetos: {', '.join(labels)}", {}
                return r.get("error", "Segmentación no disponible"), {}

            # ── ZERO-SHOT OBJECT DETECTION ────────────────────────────
            elif tool == "zero_shot_detect":
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                labels    = args.get("labels", ["person", "car", "dog", "cat", "building"])
                if not image_b64:
                    return "Envíame primero una imagen para detectar objetos.", {}
                import base64 as _b64
                image_bytes = _b64.b64decode(image_b64)
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().zero_shot_detect_objects(image_bytes, labels)
                if r.get("success"):
                    dets = r.get("detections", [])
                    if dets:
                        lines = [f"• {d['label']}: {d['score']:.0%}" for d in dets[:8]]
                        return f"[OWL-ViT] {len(dets)} objetos detectados:\n" + "\n".join(lines), {}
                    return "[OWL-ViT] No se detectaron los objetos buscados en la imagen.", {}
                return r.get("error", "Detección zero-shot no disponible"), {}

            # ── AUDIO ENHANCEMENT (Audio-to-Audio) ───────────────────
            elif tool == "enhance_audio":
                audio_b64 = args.get("audio_bytes_b64", "")
                if not audio_b64:
                    return "Necesito audio_bytes_b64 para mejorar el audio.", {}
                import base64 as _b64
                audio_bytes = _b64.b64decode(audio_b64)
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().enhance_audio(audio_bytes)
                if r.get("success") and r.get("audio_bytes"):
                    ab = r["audio_bytes"]
                    return f"Audio mejorado ({len(ab)//1024}KB)", {"audio_bytes": ab}
                return r.get("error", "Mejora de audio no disponible"), {}

            # ── TEXT RANKING (Reranking para RAG) ────────────────────
            elif tool == "rank_texts":
                query    = args.get("query", "")
                passages = args.get("passages", [])
                if not query or not passages:
                    return "Necesito query y passages para hacer reranking.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().rank_texts(query, passages)
                if r.get("success"):
                    ranked = r.get("ranked", [])[:5]
                    lines = [f"{i+1}. [{s['score']:.3f}] {s['text'][:150]}" for i, s in enumerate(ranked)]
                    return f"[Reranking para: '{query}']\n" + "\n".join(lines), {}
                return r.get("error", "Text ranking no disponible"), {}

            # ── TABLE QUESTION ANSWERING (TAPAS) ─────────────────────
            elif tool == "table_qa":
                table    = args.get("table", {})
                question = args.get("question", "")
                if not table or not question:
                    return "Necesito table (dict de columnas→listas) y question.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().table_question_answering(table, question)
                if r.get("success"):
                    return f"[TAPAS] {question}\nRespuesta: {r.get('answer','')}", {}
                return r.get("error", "Table QA no disponible"), {}

            # ── MASK GENERATION (SAM) ─────────────────────────────────
            elif tool == "generate_masks":
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                if not image_b64:
                    return "Envíame primero una imagen para generar máscaras.", {}
                import base64 as _b64
                image_bytes = _b64.b64decode(image_b64)
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().generate_masks(image_bytes)
                if r.get("success"):
                    count = r.get("count", 0)
                    return f"[SAM] {count} máscaras de segmentación generadas para la imagen.", {}
                return r.get("error", "SAM mask generation no disponible"), {}

            # ── SMOLAGENTS SEARCH AGENT ───────────────────────────────
            elif tool == "run_smolagent":
                task = args.get("task", "")
                if not task:
                    return "Necesito una tarea para el agente de investigación.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().run_search_agent(task)
                if r.get("success"):
                    steps = r.get("steps_count", 0)
                    answer = r.get("answer", "")
                    return f"[AGENT — {steps} pasos]\nTarea: {task}\n\n{answer}", {}
                return r.get("error", "Agente de búsqueda no disponible"), {}

            # ── HF SPACES — Free GPU capabilities ────────────────────────

            elif tool == "remove_background":
                import base64 as _b64
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                if not image_b64:
                    return "Envíame primero una imagen para eliminar el fondo.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().remove_background(_b64.b64decode(image_b64))
                if r.get("success"):
                    return "[Fondo eliminado con BiRefNet]", {"image_bytes": r["image_bytes"]}
                return r.get("error", "Error eliminando fondo"), {}

            elif tool == "kokoro_tts":
                text = args.get("text", "")
                if not text:
                    return "Necesito texto para generar voz.", {}
                voice = args.get("voice", "af_heart")
                speed = float(args.get("speed", 1.0))
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().kokoro_tts(text[:500], voice, speed)
                if r.get("success"):
                    ab = r["audio_bytes"]
                    return f"Voz generada ({len(ab)//1024}KB, voice={voice})", {"audio_bytes": ab}
                return r.get("error", "Kokoro TTS no disponible"), {}

            elif tool == "clone_voice":
                import base64 as _b64
                ref_b64 = args.get("ref_audio_b64", "")
                gen_text = args.get("gen_text", "")
                ref_text = args.get("ref_text", "")
                if not ref_b64 or not gen_text:
                    return "Necesito el audio de referencia (ref_audio_b64) y el texto a generar (gen_text).", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().clone_voice(_b64.b64decode(ref_b64), ref_text, gen_text)
                if r.get("success"):
                    ab = r["audio_bytes"]
                    return f"Voz clonada ({len(ab)//1024}KB)", {"audio_bytes": ab}
                return r.get("error", "F5-TTS no disponible"), {}

            elif tool == "upscale_image":
                import base64 as _b64
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                if not image_b64:
                    return "Envíame primero una imagen para mejorar.", {}
                scale = int(args.get("scale", 2))
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().upscale_image(_b64.b64decode(image_b64), scale)
                if r.get("success"):
                    return f"[Imagen mejorada {scale}x con IA]", {"image_bytes": r["image_bytes"]}
                return r.get("error", "Upscaling no disponible"), {}

            elif tool == "ocr_space":
                import base64 as _b64
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                if not image_b64:
                    return "Envíame la imagen con el texto a extraer.", {}
                task = args.get("task", "Text")
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().ocr_document_space(_b64.b64decode(image_b64), task)
                if r.get("success"):
                    return r["text"], {}
                return r.get("error", "OCR no disponible"), {}

            elif tool == "estimate_pose":
                import base64 as _b64
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                if not image_b64:
                    return "Envíame una imagen con personas para detectar la pose.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().estimate_pose(_b64.b64decode(image_b64))
                if r.get("success"):
                    kp = r.get("keypoints", {})
                    n = len(kp) if isinstance(kp, list) else len(kp.get("people", []))
                    obs = f"[Pose detectada — {n} persona(s) con 17 keypoints COCO]"
                    media: dict = {}
                    if r.get("image_bytes"):
                        media["image_bytes"] = r["image_bytes"]
                    return obs, media
                return r.get("error", "ViTPose no disponible"), {}

            elif tool == "generate_3d":
                import base64 as _b64
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                prompt = args.get("prompt", "")
                img_bytes = _b64.b64decode(image_b64) if image_b64 else None
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().generate_3d_model(img_bytes, prompt)
                if r.get("success"):
                    if r.get("model_bytes"):
                        return "[Modelo 3D generado — GLB]", {
                            "document_bytes": r["model_bytes"],
                            "document_filename": "model.glb",
                        }
                    return f"[Modelo 3D generado — URL: {r.get('model_url', '')}]", {}
                return r.get("error", "Hunyuan3D no disponible"), {}

            elif tool == "edit_image_flux":
                import base64 as _b64
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                prompt = args.get("prompt", "")
                if not image_b64:
                    return "Envíame primero la imagen a editar.", {}
                if not prompt:
                    return "Necesito las instrucciones de edición (prompt).", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().edit_image_kontext(_b64.b64decode(image_b64), prompt)
                if r.get("success"):
                    return f"[Imagen editada con FLUX Kontext: '{prompt[:80]}']", {
                        "image_bytes": r["image_bytes"]
                    }
                return r.get("error", "FLUX Kontext no disponible"), {}

            elif tool == "outpaint_image":
                import base64 as _b64
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                if not image_b64:
                    return "Envíame la imagen a ampliar.", {}
                w = int(args.get("width", 1920))
                h = int(args.get("height", 1080))
                prompt = args.get("prompt", "")
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().outpaint_image(_b64.b64decode(image_b64), w, h, prompt)
                if r.get("success"):
                    return f"[Imagen expandida a {w}x{h}]", {"image_bytes": r["image_bytes"]}
                return r.get("error", "Outpainting no disponible"), {}

            elif tool == "colorize_image":
                import base64 as _b64
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                if not image_b64:
                    return "Envíame la imagen en blanco y negro a colorizar.", {}
                description = args.get("description", "")
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().colorize_image(_b64.b64decode(image_b64), description)
                if r.get("success"):
                    return "[Imagen coloreada con IA]", {"image_bytes": r["image_bytes"]}
                return r.get("error", "Colorización no disponible"), {}

            elif tool == "generate_video_space":
                import base64 as _b64
                prompt = args.get("prompt", "")
                image_b64 = args.get("image_bytes_b64", "") or get_image_context(chat_id)
                img_bytes = _b64.b64decode(image_b64) if image_b64 else None
                if not prompt and not img_bytes:
                    return "Necesito un prompt o imagen para generar el video.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().generate_video_space(prompt or "", img_bytes)
                if r.get("success"):
                    if r.get("video_bytes"):
                        vb = r["video_bytes"]
                        return f"[Video generado ({len(vb)//1024}KB)]", {"video_bytes": vb}
                    return f"[Video generado — URL: {r.get('video_url', '')}]", {}
                return r.get("error", "Wan2.2 no disponible (puede haber cola)"), {}

            # ── CONNECTIONS — Google, Indeed, Slack (equivalente MCP de Claude) ──

            elif tool == "gmail_list":
                from apps.core.connections.manager import get_connection_manager
                from apps.core.connections.google_connection import GoogleConnection
                mgr = get_connection_manager()
                tokens = await mgr.get(chat_id, "google")
                if not tokens:
                    return ("Google no conectado. Usa /connect google para conectar tu cuenta "
                            "y acceder a Gmail, Calendar y Drive."), {}
                query = args.get("query", "is:unread")
                max_r = int(args.get("max_results", 10))
                msgs = await GoogleConnection().gmail_list(tokens, max_r, query)
                if not msgs:
                    return "No se encontraron mensajes con ese criterio.", {}
                lines = [f"📧 **{m['subject'][:60]}**\nDe: {m['from'][:50]}\n{m['snippet'][:120]}"
                         for m in msgs]
                return f"📬 {len(msgs)} emails encontrados:\n\n" + "\n\n".join(lines), {}

            elif tool == "gmail_send":
                from apps.core.connections.manager import get_connection_manager
                from apps.core.connections.google_connection import GoogleConnection
                mgr = get_connection_manager()
                tokens = await mgr.get(chat_id, "google")
                if not tokens:
                    return "Google no conectado. Usa /connect google primero.", {}
                to = args.get("to", "")
                subject = args.get("subject", "")
                body = args.get("body", "")
                if not to or not body:
                    return "Se requiere: to (email), subject, body.", {}
                r = await GoogleConnection().gmail_send(tokens, to, subject, body)
                return (f"✅ Email enviado a {to}\nAsunto: {subject}" if r.get("success")
                        else f"Error al enviar: {r}"), {}

            elif tool == "google_calendar":
                from apps.core.connections.manager import get_connection_manager
                from apps.core.connections.google_connection import GoogleConnection
                mgr = get_connection_manager()
                tokens = await mgr.get(chat_id, "google")
                if not tokens:
                    return "Google no conectado. Usa /connect google primero.", {}
                action = args.get("action", "list")
                if action == "create":
                    r = await GoogleConnection().calendar_create(
                        tokens,
                        title=args.get("title", "Nuevo evento"),
                        start=args.get("start", ""),
                        end=args.get("end", ""),
                        description=args.get("description", ""),
                        location=args.get("location", ""),
                    )
                    return (f"✅ Evento creado: {args.get('title')}\n🔗 {r.get('link', '')}"
                            if r.get("success") else f"Error: {r}"), {}
                else:
                    events = await GoogleConnection().calendar_list(tokens, int(args.get("max_results", 10)))
                    if not events:
                        return "No hay eventos próximos en tu calendario.", {}
                    lines = [f"📅 **{e['title']}**\n🕐 {e['start']}\n📍 {e.get('location','')}"
                             for e in events[:5]]
                    return f"📆 Próximos {len(events)} eventos:\n\n" + "\n\n".join(lines), {}

            elif tool == "google_drive":
                from apps.core.connections.manager import get_connection_manager
                from apps.core.connections.google_connection import GoogleConnection
                mgr = get_connection_manager()
                tokens = await mgr.get(chat_id, "google")
                if not tokens:
                    return "Google no conectado. Usa /connect google primero.", {}
                query = args.get("query", "")
                files = await GoogleConnection().drive_search(tokens, query, int(args.get("max_results", 10)))
                if not files:
                    return f"No se encontraron archivos con '{query}' en Drive.", {}
                lines = [f"📄 **{f['name']}** ({f['type']})\n🔗 {f['link']}" for f in files[:5]]
                return f"🗂️ {len(files)} archivos encontrados:\n\n" + "\n\n".join(lines), {}

            elif tool == "indeed_jobs":
                from apps.core.connections.indeed_connection import IndeedConnection
                query = args.get("query", "")
                location = args.get("location", "Remote")
                max_r = int(args.get("max_results", 10))
                emp_type = args.get("employment_type", "")
                if not query:
                    return "Se requiere: query (ej: 'Python developer')", {}
                jobs = await IndeedConnection().search_jobs(query, location, max_r, emp_type)
                if not jobs:
                    return f"No se encontraron empleos para '{query}' en {location}.", {}
                lines = [f"💼 **{j['title']}** @ {j['company']}\n📍 {j['location']} {j.get('salary','')}\n🔗 {j.get('link','')} "
                         for j in jobs[:5]]
                return f"🔍 {len(jobs)} empleos encontrados en Indeed:\n\n" + "\n\n".join(lines), {}

            elif tool == "slack_send":
                from apps.core.connections.manager import get_connection_manager
                from apps.core.connections.slack_connection import SlackConnection
                mgr = get_connection_manager()
                text_msg = args.get("message", args.get("text", ""))
                channel = args.get("channel", "")
                # Try OAuth tokens first, fallback to webhook
                tokens = await mgr.get(chat_id, "slack")
                if tokens and channel:
                    r = await SlackConnection().send_message(tokens, channel, text_msg)
                    return (f"✅ Mensaje enviado a #{channel} en Slack"
                            if r.get("success") else f"Error Slack: {r.get('error')}"), {}
                else:
                    r = await SlackConnection().send_webhook(text_msg)
                    return ("✅ Mensaje enviado a Slack via webhook"
                            if r.get("success") else "Error: configura SLACK_WEBHOOK_URL o usa /connect slack"), {}

            elif tool == "list_connections":
                from apps.core.connections.manager import get_connection_manager
                mgr = get_connection_manager()
                connected = await mgr.list_connected(chat_id)
                available = list(mgr.AVAILABLE.keys())
                lines = []
                for s in available:
                    name = mgr.AVAILABLE[s]
                    status = "✅" if s in connected else "❌"
                    lines.append(f"{status} **{s}** — {name}")
                return ("🔌 **Conexiones de ARIA**\n\n" + "\n".join(lines) +
                        "\n\nUsa `/connect <servicio>` para conectar una cuenta."), {}

            elif tool == "analyze_image_vision":
                image_b64 = get_image_context(chat_id)
                if not image_b64:
                    return "No hay imagen en el contexto. Envíame una imagen primero.", {}
                question = args.get("question", "Describe esta imagen en detalle y extrae toda la información relevante.")
                ai = self._ai_client()
                if not ai:
                    return "Motor de IA no disponible.", {}
                resp = await ai.complete_vision(
                    system="Eres ARIA — analiza imágenes con máximo detalle. Responde en español.",
                    user=question,
                    image_b64=image_b64,
                    agent_name="aria_vision_tool",
                )
                return (resp.content if resp.success else "Análisis visual no disponible temporalmente."), {}

        except Exception as exc:
            logger.error("[AriaMind] tool=%s: %s", tool, exc, exc_info=True)
            return f"Error en {tool}: {str(exc)[:200]}", {}

        return "Herramienta desconocida", {}

    # ── PLANNING LAYER ──────────────────────────────────────────────────────

    _biz_ctx_cache: dict = {}  # {"content": str, "ts": float}

    async def _load_business_context(self) -> str:
        """
        Context Loader — carga el estado completo del negocio para el ciclo cognitivo.
        Cacheado 5 min en memoria para evitar redundant Redis reads (equivalente a prompt caching).
        """
        now = time.time()
        cached = self._biz_ctx_cache
        if cached.get("ts") and now - cached["ts"] < 300:
            return cached["content"]
        lines = []
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if not cache:
                return "Redis no disponible — operando sin contexto de negocio"

            # Income Loop stats
            total_cycles = int(await cache.get("aria:income:total_cycles") or 0)
            total_urls = int(await cache.get("aria:income:total_urls_published") or 0)
            last_strategy = await cache.get("aria:income:last_strategy") or "ninguna"
            lines.append(f"• Income Loop: {total_cycles} ciclos, {total_urls} URLs publicadas, última: {last_strategy}")

            # Product catalog
            raw_catalog = await cache.lrange("aria:products:catalog", 0, 4)
            n_products = int(await cache.get("aria:products:count") or len(raw_catalog or []))
            lines.append(f"• Catálogo: {n_products} productos publicados")
            if raw_catalog:
                import json as _j
                for raw in raw_catalog[:3]:
                    try:
                        p = _j.loads(raw) if isinstance(raw, str) else raw
                        lines.append(f"  - {p.get('title','?')[:60]} @ ${p.get('price', 0)}")
                    except Exception:
                        pass

            # Investor pipeline
            investor_raw = await cache.get("aria:investor:latest_deck")
            if investor_raw:
                import json as _j
                deck = _j.loads(investor_raw) if isinstance(investor_raw, str) else investor_raw
                lines.append(f"• Último pitch deck: ${deck.get('ask', 0):,.0f} ask | {deck.get('ts','')}")

            # Grants
            grants_raw = await cache.lrange("aria:grants:applications", -1, -1)
            if grants_raw:
                import json as _j
                g = _j.loads(grants_raw[0]) if isinstance(grants_raw[0], str) else grants_raw[0]
                lines.append(f"• Grants preparados: {g.get('count', 0)} apps | ${g.get('total_potential', 0):,.0f} potencial")

            # Revenue summary
            revenue_raw = await cache.get("aria:revenue:total_usd")
            if revenue_raw:
                lines.append(f"• Revenue acumulado: ${float(revenue_raw or 0):,.2f}")

            # Active goals from Redis
            raw_goals = await cache.lrange(self.K_GOALS, 0, 2)
            if raw_goals:
                import json as _j
                for rg in raw_goals:
                    try:
                        goal = _j.loads(rg) if isinstance(rg, str) else rg
                        if goal.get("status") == "active":
                            lines.append(f"• Meta activa: {goal.get('text','')[:80]}")
                    except Exception:
                        pass

        except Exception as exc:
            logger.debug("[AriaMind] _load_business_context error: %s", exc)
            lines.append("contexto de negocio parcialmente disponible")

        result = "\n".join(lines) if lines else "primer uso — sin historial de negocio aún"
        self._biz_ctx_cache.update({"content": result, "ts": time.time()})
        return result

    def _needs_agent_loop(self, text: str) -> bool:
        """
        Detecta si el request requiere el agentic loop (ReAct).
        Cualquier solicitud de ACCIÓN que no sea conversación simple activa el loop.
        El loop es el modo por defecto para todas las acciones ejecutables.
        """
        text_lower = text.lower()

        # Conversación simple — NO necesita loop
        simple_patterns = [
            "hola", "buenos días", "buenas", "gracias", "ok", "entendido",
            "¿cuánto", "cuánto es", "qué hora", "quién eres", "cómo te llamas",
            "qué puedes hacer", "ayuda", "help", "/status", "/goals", "/clear",
        ]
        if any(p in text_lower for p in simple_patterns) and len(text) < 50:
            return False

        # Verbo de acción → usar loop
        action_verbs = [
            "crea", "agrega", "lanza", "genera", "ejecuta", "haz", "sube",
            "publica", "busca", "implementa", "automatiza", "configura",
            "diseña", "construye", "añade", "activa", "inicia", "corre",
            "mejora", "optimiza", "analiza", "investiga", "encuentra",
            "escribe", "produce", "desarrolla", "prepara", "arma",
        ]
        if any(v in text_lower for v in action_verbs):
            return True

        # Patrones multi-paso explícitos
        if any(pat in text_lower for pat in _COMPLEX_PATTERNS):
            return True

        # Requests de longitud media/larga son probablemente acciones
        if len(text) > 60:
            return True

        return False

    def _needs_planning(self, text: str) -> bool:
        """Alias para compatibilidad — delega a _needs_agent_loop."""
        return self._needs_agent_loop(text)

    async def _run_agent_loop(self, text: str, chat_id: str, state: dict, goals: list) -> MindResponse:
        """
        El VERDADERO patrón ReAct — cómo funciona Claude Code.

        Loop: Razona → Actúa → Observa resultado REAL → Razona de nuevo (con evidencia)
        → Actúa diferente basándose en lo que vio → Observa → ... hasta done=True o max_steps.

        La diferencia con un plan ciego:
        - Plan ciego: "Voy a hacer A, B, C" → A, B, C (sin importar qué pasó en A o B)
        - ReAct loop: Hago A → veo resultado de A → decido hacer B o C según lo que vi → ejecuto
        """
        business_context = await self._load_business_context()
        observations: list[dict] = []
        media_result: dict = {}

        for step in range(1, MAX_AGENT_STEPS + 1):
            # Construir texto de observaciones acumuladas con indicadores ✓/✗
            if observations:
                obs_text = "\n".join(
                    f"[Paso {o['step']}] {'✓' if o.get('success') else '✗'} {o['tool']}\n"
                    f"Razonamiento: {o['reasoning'][:200]}\n"
                    f"Resultado: {o['result'][:500]}"
                    for o in observations
                )
            else:
                obs_text = "(Ninguna — este es el primer paso)"

            # THINK: razona sobre qué hacer AHORA basándose en lo que ya ocurrió
            decision = await self._agent_think_step(
                original_request=text,
                current_step=step,
                max_steps=MAX_AGENT_STEPS,
                observations=obs_text,
                business_context=business_context,
            )

            if not decision:
                logger.warning("[AgentLoop] _agent_think_step returned None en paso %d", step)
                if step == 1:
                    # First step failed: use intent-based fallback so Aria does SOMETHING useful
                    fallback_tool, fallback_args = self._infer_tool_from_intent(text)
                    if fallback_tool:
                        logger.info("[AgentLoop] Fallback intent→tool: %s %s", fallback_tool, fallback_args)
                        obs, media = await self._execute_with_retry(fallback_tool, fallback_args, chat_id=chat_id)
                        observations.append({
                            "step": 1, "tool": fallback_tool,
                            "reasoning": f"[fallback intent] {text[:100]}",
                            "result": obs[:800],
                            "success": bool(obs),
                            "type": "media" if media else "text",
                        })
                        if media and not media_result:
                            media_result = media
                        await self._record_exec(fallback_tool, fallback_args, obs, bool(obs))
                break

            # Si el objetivo está logrado → responder
            if decision.get("done"):
                final_text = decision.get("direct_reply") or "Objetivo completado."
                await self._store_interaction(chat_id, text, final_text, "agent_loop")
                await self._evolve_state(chat_id, state, text, goals)
                asyncio.create_task(self._maybe_reflect(chat_id))
                return MindResponse(
                    text=final_text if not media_result else None,
                    caption=final_text if media_result else None,
                    tool_used="agent_loop",
                    **media_result,
                )

            reasoning = decision.get("reasoning", "")

            # Parallel execution — independent tools run simultaneously
            parallel = decision.get("parallel_tools")
            if parallel and isinstance(parallel, list) and len(parallel) > 1:
                valid = [pt for pt in parallel if isinstance(pt, dict) and pt.get("tool")]
                logger.info("[AgentLoop] Paso %d: %d tools en paralelo", step, len(valid))
                results = await asyncio.gather(
                    *[self._execute_with_retry(pt["tool"], pt.get("args") or {}, chat_id=chat_id)
                      for pt in valid],
                    return_exceptions=True,
                )
                for pt, res in zip(valid, results):
                    if isinstance(res, Exception):
                        p_obs, p_media = f"Error: {res}", {}
                    else:
                        p_obs, p_media = res
                    p_ok = bool(p_obs) and "error" not in p_obs.lower()[:120]
                    observations.append({
                        "step": step, "tool": pt["tool"],
                        "reasoning": f"{reasoning} [paralelo]",
                        "result": p_obs[:800], "success": p_ok,
                        "type": "media" if p_media else "text",
                    })
                    if p_media and not media_result:
                        media_result = p_media
                    await self._record_exec(pt["tool"], pt.get("args") or {}, p_obs, p_ok)
                continue

            tool = decision.get("tool")
            args = decision.get("args") or {}

            if not tool or tool in ("null", "none", None):
                # Direct reply without tool
                reply = decision.get("direct_reply") or ""
                if reply:
                    observations.append({"step": step, "tool": "reply", "reasoning": reasoning, "result": reply})
                    break
                continue

            logger.info("[AgentLoop] Paso %d/%d: %s — %s", step, MAX_AGENT_STEPS, tool, reasoning[:100])

            # ACT: ejecutar la herramienta elegida
            obs, media = await self._execute_with_retry(tool, args, chat_id=chat_id)

            # OBSERVE: guardar el resultado real para que el siguiente paso lo use
            step_success = bool(obs) and "error" not in obs.lower()[:120]
            observations.append({
                "step": step,
                "tool": tool,
                "reasoning": reasoning,
                "result": obs[:800],
                "success": step_success,
                "type": "media" if media else "text",
            })
            if media and not media_result:
                media_result = media

            await self._record_exec(tool, args, obs, bool(media or obs))

            # Adaptive exit: quick done-check after a successful step
            if step_success and step < MAX_AGENT_STEPS - 1:
                from apps.core.tools.ai_client import AIModel as _AIModel
                _ai2 = self._ai_client()
                if _ai2:
                    _check = await _ai2.complete_json(
                        system='Responde SOLO JSON sin texto adicional: {"done": true} si el objetivo está logrado con evidencia concreta, {"done": false} si no.',
                        user=f"Objetivo: {text[:200]}\nÚltimo resultado ({tool}): {obs[:300]}",
                        model=_AIModel.FAST,
                        max_tokens=30,
                        agent_name=f"agent_done_check_{step}",
                    )
                    if _check and _check.get("done"):
                        logger.info("[AgentLoop] Adaptive exit en paso %d — objetivo logrado", step)
                        break

        # Loop terminó (max_steps o break) → sintetizar todos los resultados
        if not observations:
            return MindResponse(text="Procesado.", tool_used="agent_loop")

        combined = "\n\n".join(
            f"**Paso {o['step']}: {o['tool']}**\n{o['result']}"
            for o in observations
        )

        ai = self._ai_client()
        final_text = combined[:2000]
        if ai:
            from apps.core.tools.ai_client import AIModel
            synth = await ai.complete(
                system=(
                    f"Eres ARIA. Ejecutaste {len(observations)} acciones autónomamente "
                    f"para: '{text[:120]}'. "
                    "Resume los resultados de forma clara, directa y útil. "
                    "Incluye: qué se logró concretamente, URLs/datos creados, "
                    "y el siguiente paso más valioso. "
                    "No hagas introducciones genéricas. Sé directa."
                ),
                user=combined[:3000],
                model=AIModel.FAST,
                max_tokens=700,
                agent_name="agent_synthesis",
            )
            if synth and synth.success and synth.content:
                final_text = await self._self_critique(text, synth.content)

        await self._store_interaction(chat_id, text, final_text, "agent_loop")
        await self._evolve_state(chat_id, state, text, goals)
        asyncio.create_task(self._maybe_reflect(chat_id))
        return MindResponse(
            text=final_text if not media_result else None,
            caption=final_text if media_result else None,
            tool_used="agent_loop",
            **media_result,
        )

    async def _agent_think_step(
        self,
        original_request: str,
        current_step: int,
        max_steps: int,
        observations: str,
        business_context: str,
    ) -> Optional[dict]:
        """
        Un único paso de razonamiento en el loop ReAct.
        El LLM ve lo que ocurrió en pasos anteriores y decide qué hacer AHORA.
        """
        ai = self._ai_client()
        if not ai:
            return {"done": True, "direct_reply": "Motor de IA no disponible."}

        from apps.core.tools.ai_client import AIModel

        prompt = AGENT_LOOP_SYSTEM.format(
            original_request=original_request,
            current_step=current_step,
            max_steps=max_steps,
            observations=observations,
            business_context=business_context,
        )

        user_msg = f"Ejecuta el paso {current_step}. Basa tu decisión en las observaciones anteriores."

        import re as _re

        # Use complete() — expect PENSAMIENTO: + ACCIÓN: mixed-text format
        raw = await ai.complete(
            system=prompt,
            user=user_msg,
            model=AIModel.FAST,
            max_tokens=900,
            agent_name=f"agent_step_{current_step}",
        )
        if raw and raw.success and raw.content:
            content = raw.content.strip()
            # Log chain-of-thought reasoning
            pens_match = _re.search(r"PENSAMIENTO:\s*(.+?)(?=ACCIÓN:|$)", content, _re.DOTALL | _re.IGNORECASE)
            if pens_match:
                logger.debug("[AgentStep %d] CoT: %s", current_step, pens_match.group(1).strip()[:300])
            # Extract JSON from ACCIÓN: section
            accion_match = _re.search(r"ACCIÓN:\s*(.+)", content, _re.DOTALL | _re.IGNORECASE)
            json_src = accion_match.group(1).strip() if accion_match else content
            json_src = _re.sub(r"```(?:json)?\n?", "", json_src).strip().rstrip("`").strip()
            idx = json_src.find("{")
            end = json_src.rfind("}")
            if idx != -1 and end > idx:
                try:
                    return json.loads(json_src[idx:end + 1])
                except Exception:
                    pass
            # Fallback: any JSON object in full content
            idx = content.find("{")
            end = content.rfind("}")
            if idx != -1 and end > idx:
                try:
                    return json.loads(content[idx:end + 1])
                except Exception:
                    pass

        # Last resort: complete_json() with explicit JSON-only instruction
        return await ai.complete_json(
            system=prompt,
            user=user_msg + "\n\nResponde SOLO con la sección ACCIÓN como JSON válido. Sin texto previo.",
            model=AIModel.FAST,
            max_tokens=600,
            agent_name=f"agent_step_{current_step}_json",
        )

    async def _self_critique(self, request: str, draft: str) -> str:
        """
        Constitutional AI pass — evalúa la respuesta antes de enviarla.
        Equivalente al RLHF/CAI de Claude: principios embebidos en el ciclo, no post-filtro.
        """
        ai = self._ai_client()
        if not ai or len(draft.strip()) < 25:
            return draft
        from apps.core.tools.ai_client import AIModel
        check = await ai.complete_json(
            system=(
                "Evalúa esta respuesta de IA en 3 dimensiones:\n"
                "1. Ejecución: ¿hizo lo pedido con evidencia real (no lo prometió — lo hizo)?\n"
                "2. Honestidad: ¿no inventa URLs, cifras, confirmaciones sin tool result real?\n"
                "3. Utilidad: ¿da información accionable y concreta (no vagüedades)?\n"
                'Responde SOLO JSON: {"score": 1-10, "issue": "descripción breve o null", '
                '"improved": "versión mejorada en español si score<6, sino null"}'
            ),
            user=f"Pedido: {request[:250]}\nRespuesta: {draft[:700]}",
            model=AIModel.FAST,
            max_tokens=500,
            agent_name="self_critique",
        )
        if check and isinstance(check.get("score"), (int, float)):
            if check["score"] < 6 and check.get("improved"):
                logger.info("[SelfCritique] Score %.0f → mejorando respuesta", check["score"])
                return str(check["improved"])
        return draft

    async def _compress_history(self, chat_id: str, history: list) -> list:
        """
        Context window management — cuando el historial crece > 30 msgs,
        comprime los más antiguos en un resumen. Mismo patrón que Claude.
        """
        if len(history) <= 30:
            return history
        to_compress = history[:-10]
        keep_recent = history[-10:]
        ai = self._ai_client()
        if not ai:
            return keep_recent
        from apps.core.tools.ai_client import AIModel
        text_block = "\n".join(
            f"{m['role'].upper()}: {m.get('content', '')[:200]}" for m in to_compress
        )
        resp = await ai.complete(
            system=(
                "Resume esta conversación en 4-6 oraciones. "
                "Incluye: qué pidió el usuario, qué ejecutó ARIA, resultados concretos obtenidos. "
                "Sin introducciones. Directo al grano."
            ),
            user=text_block[:3000],
            model=AIModel.FAST,
            max_tokens=300,
            agent_name="history_compress",
        )
        if resp and resp.success and resp.content:
            summary = [{"role": "system", "content": f"[HISTORIAL COMPRIMIDO] {resp.content.strip()}"}]
            compressed = summary + keep_recent
            cache = self._cache_client()
            if cache:
                await cache.set(self.K_HISTORY.format(cid=chat_id), compressed,
                                ttl_seconds=86400 * 7)
            logger.info("[AriaMind] Historial comprimido: %d → %d mensajes", len(history), len(compressed))
            return compressed
        return keep_recent

    def _is_unnecessary_question(self, user_text: str, reply: str) -> bool:
        """
        Goal Engine: detecta si el LLM generó una pregunta cuando debía ejecutar.
        Retorna True cuando la respuesta es una pregunta sobre algo que ARIA puede inferir.
        """
        if not reply or "?" not in reply:
            return False

        # Si el usuario dio una instrucción de acción (no una pregunta)
        action_verbs = ["crea", "agrega", "lanza", "genera", "ejecuta", "haz", "sube",
                        "publica", "busca", "implementa", "automatiza", "configura",
                        "diseña", "construye", "añade", "activa", "inicia", "corre"]
        user_lower = user_text.lower()
        is_action_request = any(v in user_lower for v in action_verbs)

        if not is_action_request:
            return False  # Usuario hizo una pregunta → OK responder con pregunta

        # Preguntas típicas que ARIA jamás debe hacer sobre acciones
        unnecessary_question_patterns = [
            "qué tipo", "qué clase", "cuántos", "qué plataforma", "cuál",
            "me puedes decir", "podrías indicarme", "me especificas",
            "qué nombre", "qué precio", "para qué", "qué descripción",
            "qué categoría", "físico o digital", "producto o servicio",
        ]
        reply_lower = reply.lower()
        return any(pat in reply_lower for pat in unnecessary_question_patterns)

    def _infer_tool_from_intent(self, text: str) -> tuple[str, dict]:
        """
        Tool Mapper: infiere la herramienta más apropiada del texto del usuario.
        Retorna (tool_name, tool_args) con valores razonables por defecto.
        """
        t = text.lower()

        # Shopify / productos
        if any(k in t for k in ["shopify", "producto", "tienda", "vender", "shop"]):
            if any(k in t for k in ["seo", "optimiza", "mejora"]):
                return "shopify_optimize", {"operation": "seo"}
            if any(k in t for k in ["bundle", "paquete"]):
                return "shopify_optimize", {"operation": "bundles"}
            if any(k in t for k in ["sale", "descuento", "oferta"]):
                return "shopify_optimize", {"operation": "flash_sale"}
            # Default: crear listing digital
            return "run_income_cycle", {"strategy": "shopify_listing"}

        # Inversores / funding
        if any(k in t for k in ["inversor", "investor", "funding", "ronda", "vc", "venture"]):
            return "run_income_cycle", {"strategy": "vc_pitch_deck"}
        if any(k in t for k in ["grant", "beca", "aceleradora", "non-dilutive"]):
            return "run_income_cycle", {"strategy": "micro_grant_hunter"}

        # Ingresos / monetización
        if any(k in t for k in ["ingres", "dinero", "monetiz", "ganar", "revenue"]):
            return "run_income_cycle", {"strategy": "content_pipeline"}

        # Análisis / estado
        if any(k in t for k in ["analiza", "estado", "qué falta", "qué necesitas", "revisa"]):
            return "run_proactive_analysis", {"focus": "all"}

        # Social / contenido
        if any(k in t for k in ["linkedin", "twitter", "redes", "post", "contenido"]):
            return "create_social_content", {"topic": "AI autonomous income platform", "platforms": ["linkedin", "twitter"], "tone": "professional"}

        # Default: análisis proactivo
        return "run_proactive_analysis", {"focus": "all"}

    async def _generate_plan(self, text: str, business_context: str) -> list[dict]:
        """Genera un plan de ejecución multi-paso para una solicitud compleja."""
        ai = self._ai_client()
        if not ai:
            return []
        from apps.core.tools.ai_client import AIModel
        result = await ai.complete_json(
            system=PLANNER_SYSTEM,
            user=f"CONTEXTO ACTUAL:\n{business_context}\n\nOBJETIVO DEL USUARIO:\n{text}",
            model=AIModel.STRATEGY,
            max_tokens=800,
            agent_name="planner",
        )
        if not result:
            return []
        if result.get("ask_first") and result.get("question_if_needed"):
            return [{"step": 0, "tool": "__ask__", "args": {"question": result["question_if_needed"]}, "description": "Pregunta mínima necesaria"}]
        return result.get("steps", [])

    async def _execute_plan(self, steps: list[dict], original_request: str, chat_id: str) -> MindResponse:
        """Ejecuta un plan de pasos secuenciales, acumulando y sintetizando resultados."""
        if not steps:
            return MindResponse(text="No pude generar un plan. Intenta describir tu objetivo con más detalle.")

        if steps[0].get("tool") == "__ask__":
            q = steps[0]["args"].get("question", "¿Puedes darme más detalles?")
            await self._store_interaction(chat_id, original_request, q, None)
            return MindResponse(text=q)

        results = []
        media_result: dict = {}
        total = len(steps)

        for i, step in enumerate(steps):
            tool = step.get("tool")
            args = step.get("args") or {}
            desc = step.get("description", f"Paso {i+1}")
            if not tool:
                continue
            logger.info("[AriaMind/Plan] Paso %d/%d: %s — %s", i + 1, total, tool, desc)
            obs, media = await self._execute_with_retry(tool, args, chat_id=chat_id)
            results.append(f"**{desc}**\n{obs[:600]}")
            if media and not media_result:
                media_result = media
            await self._record_exec(tool, args, obs, bool(media or obs))

        combined_obs = "\n\n".join(results)
        ai = self._ai_client()
        final_text = combined_obs
        if ai:
            from apps.core.tools.ai_client import AIModel
            synth = await ai.complete(
                system=(
                    f"Eres ARIA. Ejecutaste {total} pasos autónomamente para: '{original_request[:120]}'. "
                    "Resume los resultados de forma clara y útil en español. "
                    "Incluye qué se logró concretamente, URLs o productos creados si los hay, y el siguiente paso recomendado. "
                    "Sé directa y concisa."
                ),
                user=combined_obs[:3000],
                model=AIModel.FAST,
                max_tokens=600,
                agent_name="planner_synthesis",
            )
            if synth and synth.success and synth.content:
                final_text = synth.content

        await self._store_interaction(chat_id, original_request, final_text, "plan_executor")
        return MindResponse(
            text=final_text if not media_result else None,
            caption=final_text if media_result else None,
            tool_used="plan_executor",
            **media_result,
        )

    # ── SÍNTESIS ───────────────────────────────────────────────────────────

    async def _synthesize(self, user_input: str, tool: str, observation: str) -> str:
        """LLM convierte la observación de la herramienta en respuesta natural."""
        if not observation or len(observation) < 10:
            return "Ejecutado."

        ai = self._ai_client()
        if not ai:
            return observation[:400]

        from apps.core.tools.ai_client import AIModel
        resp = await ai.complete(
            system=SYNTHESIS_SYSTEM,
            user=(f"El usuario pidió: {user_input[:400]}\n"
                  f"Usé la herramienta '{tool}' y obtuve:\n{observation[:2000]}"),
            model=AIModel.STRATEGY,
            max_tokens=800,
            temperature=0.35,
            agent_name="aria_synthesis",
        )
        if resp and resp.success and resp.content:
            return await self._self_critique(user_input, resp.content.strip())
        return observation[:600]

    async def _fallback_reply(self, text: str) -> str:
        """Si el plan no tiene reply, genera respuesta directa y útil."""
        ai = self._ai_client()
        if not ai:
            return "Entendido."
        from apps.core.tools.ai_client import AIModel
        resp = await ai.complete(
            system=(
                "Eres ARIA, asistente inteligente. Responde en español de forma directa y completa. "
                "Usa markdown cuando sea útil. Si necesitas datos de internet, dilo y sugiere qué buscar."
            ),
            user=text,
            model=AIModel.STRATEGY,
            max_tokens=600,
            temperature=0.4,
            agent_name="aria_fallback",
        )
        return resp.content.strip() if (resp and resp.success) else "Entendido."

    # ── GESTIÓN DE ESTADO COGNITIVO ────────────────────────────────────────

    async def _load_state(self, chat_id: str) -> dict:
        cache = self._cache_client()
        if cache:
            s = await cache.get(self.K_STATE.format(cid=chat_id))
            if isinstance(s, dict):
                return s
        return {"focus": "", "confidence": 0.7, "interaction_count": 0}

    async def _evolve_state(self, chat_id: str, current: dict,
                             text: str, goals: list[dict]) -> None:
        """Actualiza el estado cognitivo después de cada interacción."""
        cache = self._cache_client()
        if not cache:
            return

        # Actualizar contador
        current["interaction_count"] = current.get("interaction_count", 0) + 1

        # Actualizar foco (los primeros 60 chars del texto actual)
        current["focus"] = text[:60]

        # Confidence sube lentamente hasta 1.0 con cada éxito
        current["confidence"] = min(1.0, current.get("confidence", 0.7) + 0.01)

        await cache.set(self.K_STATE.format(cid=chat_id), current, ttl_seconds=86400 * 30)

    async def _load_goals(self) -> list[dict]:
        cache = self._cache_client()
        if cache:
            g = await cache.get(self.K_GOALS)
            if isinstance(g, list):
                return [x for x in g if isinstance(x, dict)]
        return []

    async def _save_goals(self, goals: list[dict]) -> None:
        cache = self._cache_client()
        if cache:
            await cache.set(self.K_GOALS, goals, ttl_seconds=86400 * 365)

    async def _apply_goal_action(self, action: dict, goals: list[dict]) -> list[dict]:
        if action.get("action") == "add":
            goals.append(Goal(
                text=action.get("text", ""),
                priority=int(action.get("priority", 5)),
            ).__dict__)
            await self._save_goals(goals)
        elif action.get("action") == "update":
            idx = action.get("index", 0)
            if 0 <= idx < len(goals):
                if "progress" in action:
                    goals[idx]["progress"] = action["progress"]
                if "status" in action:
                    goals[idx]["status"] = action["status"]
                await self._save_goals(goals)
        return goals

    async def _load_learned(self) -> list[str]:
        cache = self._cache_client()
        if cache:
            l = await cache.get(self.K_LEARNED)
            if isinstance(l, list):
                return l
        return []

    async def _load_history(self, chat_id: str) -> list[dict]:
        cache = self._cache_client()
        if cache:
            h = await cache.get(self.K_HISTORY.format(cid=chat_id))
            if isinstance(h, list):
                return h
        return []

    async def _clear_history(self, chat_id: str) -> None:
        cache = self._cache_client()
        if cache:
            await cache.delete(self.K_HISTORY.format(cid=chat_id))

    async def _store_interaction(self, chat_id: str, user_text: str,
                                  aria_text: Optional[str], tool: Optional[str]) -> None:
        cache = self._cache_client()
        if not cache:
            return
        key = self.K_HISTORY.format(cid=chat_id)
        history = await cache.get(key) or []
        if not isinstance(history, list):
            history = []
        history.append({"role": "user", "content": user_text[:300]})
        if aria_text:
            history.append({"role": "assistant", "content": aria_text[:300],
                             **({"tool": tool} if tool else {})})
        history = history[-(self.MAX_HISTORY * 2):]
        await cache.set(key, history, ttl_seconds=86400 * 7)

    async def _record_exec(self, tool: str, args: dict, obs: str, success: bool) -> None:
        """Guarda registro de ejecución para auto-reflexión futura."""
        cache = self._cache_client()
        if not cache:
            return
        execs = await cache.get(self.K_EXECS) or []
        if not isinstance(execs, list):
            execs = []
        execs.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "success": success,
            "in": str(args)[:100],
            "out": obs[:150],
        })
        execs = execs[-self.MAX_EXECS:]
        await cache.set(self.K_EXECS, execs, ttl_seconds=86400 * 30)

    # ── AUTO-REFLEXIÓN ─────────────────────────────────────────────────────

    async def _maybe_reflect(self, chat_id: str) -> None:
        """
        Analiza ejecuciones recientes, genera reglas concretas de mejora,
        las guarda en Redis. Afectan comportamiento inmediatamente.
        """
        state = await self._load_state(chat_id)
        count = state.get("interaction_count", 0)
        if count == 0 or count % self.REFLECT_EVERY != 0:
            return

        logger.info("[AriaMind] Auto-reflexión en interacción #%d", count)
        cache = self._cache_client()
        if not cache:
            return

        # Lock para no ejecutar en paralelo
        locked = await cache.acquire_lock("aria:mind:reflect", ttl_seconds=60)
        if not locked:
            return

        try:
            execs = await cache.get(self.K_EXECS) or []
            if len(execs) < 5:
                return

            # Construir muestra de ejecuciones para el LLM
            sample = "\n".join(
                f"[{'✓' if e.get('success') else '✗'}] {e.get('tool','?')}: "
                f"in={e.get('in','')[:60]} → out={e.get('out','')[:80]}"
                for e in execs[-20:]
            )

            ai = self._ai_client()
            if not ai:
                return

            from apps.core.tools.ai_client import AIModel
            resp = await ai.complete(
                system=(
                    "Eres el módulo de auto-mejora de ARIA. "
                    "Analiza las ejecuciones y genera reglas operativas concretas. "
                    "Cada regla debe ser una instrucción directa que mejore futuras decisiones. "
                    "Formato: verbos de acción. Sin explicaciones. Solo las reglas."
                ),
                user=(
                    f"Mis últimas {len(execs[-20:])} ejecuciones:\n{sample}\n\n"
                    "Genera exactamente 3 reglas de mejora. Una por línea. "
                    "Ejemplo: 'Usar SDXL directamente cuando FLUX falla en el primer intento.'"
                ),
                model=AIModel.STRATEGY,
                max_tokens=200,
                temperature=0.2,
                agent_name="aria_reflection",
            )

            if resp and resp.success and resp.content:
                new_rules = [
                    l.strip().lstrip("•-123. ")
                    for l in resp.content.strip().split("\n")
                    if l.strip() and len(l.strip()) > 10
                ][:3]

                existing = await self._load_learned()
                updated = (existing + new_rules)[-20:]  # máximo 20 reglas
                await cache.set(self.K_LEARNED, updated, ttl_seconds=86400 * 365)
                logger.info("[AriaMind] Nuevas reglas aprendidas: %s", new_rules)
        except Exception as exc:
            logger.warning("[AriaMind] Reflexión falló: %s", exc)
        finally:
            await cache.release_lock("aria:mind:reflect")

    # ── COGNITIVE COMMANDS ─────────────────────────────────────────────────

    async def _handle_connect_command(self, service: str, chat_id: str) -> MindResponse:
        """
        /connect <service> — inicia flujo OAuth para conectar una cuenta.
        Equivalente al sistema MCP de Claude pero para Aria.
        """
        from apps.core.connections.manager import get_connection_manager
        mgr = get_connection_manager()

        if not service:
            available = "\n".join(f"• `/connect {k}` — {v}" for k, v in mgr.AVAILABLE.items())
            connected = await mgr.list_connected(chat_id)
            conn_text = f"Ya conectados: {', '.join(connected)}" if connected else "Ninguno conectado aún"
            return MindResponse(
                text=f"🔌 **Conectar una cuenta a ARIA**\n\n{available}\n\n{conn_text}",
                tool_used="connect",
            )

        if service in ("google",):
            auth_url = mgr.get_auth_url(service, chat_id)
            if not auth_url:
                return MindResponse(
                    text=(f"⚙️ Para conectar Google, necesito que agregues estas 2 credenciales en Fly.io:\n\n"
                          "1. Obtén en **console.cloud.google.com** → APIs & Services → Credentials → OAuth 2.0 Client IDs\n"
                          "2. Agrega en Fly.io:\n"
                          "   `flyctl secrets set GOOGLE_CLIENT_ID='...' GOOGLE_CLIENT_SECRET='...' --app aria-ai`\n\n"
                          "Con Google conectado, ARIA puede leer tu Gmail, Calendar y Drive directamente."),
                    tool_used="connect",
                )
            return MindResponse(
                text=(f"🔗 **Conectar Google a ARIA**\n\n"
                      f"Haz clic aquí para autorizar:\n{auth_url}\n\n"
                      "Esto dará a ARIA acceso a:\n• 📧 Gmail (leer + enviar)\n"
                      "• 📅 Google Calendar\n• 🗂️ Google Drive\n\n"
                      "Tus credenciales se guardan encriptadas y solo ARIA las usa."),
                tool_used="connect",
            )

        if service == "slack":
            webhook = getattr(__import__("apps.core.config", fromlist=["settings"]).settings, "SLACK_WEBHOOK_URL", None)
            if webhook:
                return MindResponse(
                    text="✅ **Slack ya configurado** via webhook. ARIA puede enviar mensajes.\nPara acceso completo (leer canales), configura SLACK_CLIENT_ID + SLACK_CLIENT_SECRET.",
                    tool_used="connect",
                )
            auth_url = mgr.get_auth_url(service, chat_id)
            if not auth_url:
                return MindResponse(
                    text=("⚙️ Para conectar Slack:\n\n"
                          "**Modo simple (webhook):**\n"
                          "1. Ve a api.slack.com/apps → Create App → Incoming Webhooks\n"
                          "2. `flyctl secrets set SLACK_WEBHOOK_URL='https://hooks.slack.com/...' --app aria-ai`\n\n"
                          "**Modo completo (OAuth):**\n"
                          "1. Ve a api.slack.com/apps → OAuth & Permissions\n"
                          "2. `flyctl secrets set SLACK_CLIENT_ID='...' SLACK_CLIENT_SECRET='...' --app aria-ai`"),
                    tool_used="connect",
                )
            return MindResponse(
                text=f"🔗 **Conectar Slack a ARIA**\n\nHaz clic aquí:\n{auth_url}",
                tool_used="connect",
            )

        if service == "indeed":
            from apps.core.config import settings as _s
            if getattr(_s, "SERP_API_KEY", None):
                return MindResponse(
                    text="✅ **Indeed ya conectado** via SerpAPI. ARIA puede buscar empleos con `indeed_jobs`.",
                    tool_used="connect",
                )
            return MindResponse(
                text=("⚙️ Para conectar Indeed:\n\n"
                      "1. Obtén API key en **serpapi.com** (plan gratuito: 100 búsquedas/mes)\n"
                      "2. `flyctl secrets set SERP_API_KEY='...' --app aria-ai`\n\n"
                      "Con esto ARIA puede buscar empleos en Indeed, Google Jobs y más."),
                tool_used="connect",
            )

        if await mgr.is_connected(chat_id, service):
            return MindResponse(
                text=f"✅ **{service.capitalize()} ya está conectado.**\nUsa `/connect` para ver todas las conexiones.",
                tool_used="connect",
            )

        return MindResponse(
            text=f"Servicio '{service}' no reconocido.\nServicios disponibles: {', '.join(mgr.AVAILABLE.keys())}",
            tool_used="connect",
        )

    async def _handle_plan_command(self, goal: str) -> MindResponse:
        """
        /plan <goal> — decompose a goal into an executable plan using ARIAPlanner.
        Returns the plan as a formatted text summary.
        """
        try:
            from apps.core.cognition.planner import get_planner
            planner = get_planner()
            ai = self._ai_client()
            plan = await planner.create_plan(goal, context={}, ai_client=ai)

            task_lines = "\n".join(
                f"  {i+1}. [{t.tool}] {t.title}"
                + (f" (depende de tarea {t.depends_on[0][-1]} )" if t.depends_on else "")
                for i, t in enumerate(plan.tasks)
            )

            response = (
                f"Plan creado (ID: {plan.id})\n"
                f"Meta: {goal}\n\n"
                f"Razonamiento: {plan.reasoning[:200]}\n\n"
                f"Tareas ({len(plan.tasks)}):\n{task_lines}\n\n"
                f"Progreso: {plan.progress_pct()}%"
            )
            return MindResponse(text=response, tool_used="planner")
        except Exception as exc:
            logger.error("[AriaMind] Plan command failed: %s", exc)
            return MindResponse(text=f"Error al crear el plan: {exc}")

    async def _handle_think_command(self, question: str) -> MindResponse:
        """
        /think <question> — run full chain-of-thought + self-critique reasoning.
        Returns confidence, conclusion, and recommended action.
        """
        try:
            from apps.core.cognition.reasoning_engine import get_reasoning_engine
            ai = self._ai_client()
            engine = get_reasoning_engine(ai_client=ai)
            result = await engine.reason(question, context={})

            step_lines = "\n".join(
                f"  Paso {s.step+1}: {s.thought[:100]} → {s.leads_to[:80]}"
                f" (incertidumbre: {s.uncertainty:.0%})"
                for s in result.steps
            )
            issues = "\n".join(
                f"  • {issue}"
                for c in result.critiques for issue in c.issues[:2]
            ) or "  (ninguno)"

            response = (
                f"Razonamiento completado ({result.reasoning_time_ms}ms)\n"
                f"Confianza: {result.confidence:.0%}\n\n"
                f"Cadena de pensamiento:\n{step_lines}\n\n"
                f"Críticas identificadas:\n{issues}\n\n"
                f"Conclusión: {result.conclusion}\n\n"
                f"Acción recomendada: {result.action_recommendation}"
            )
            return MindResponse(text=response, tool_used="reasoning_engine")
        except Exception as exc:
            logger.error("[AriaMind] Think command failed: %s", exc)
            return MindResponse(text=f"Error en el razonamiento: {exc}")

    # ── LAZY SINGLETONS ────────────────────────────────────────────────────

    def _ai_client(self):
        if self._ai is None:
            try:
                from apps.core.tools.ai_client import get_ai_client
                self._ai = get_ai_client()
            except Exception as e:
                logger.error("[AriaMind] No se pudo cargar ai_client: %s", e)
        return self._ai

    def _cache_client(self):
        if self._cache is None:
            try:
                from apps.core.memory.redis_client import get_cache
                self._cache = get_cache()
            except Exception as e:
                logger.warning("[AriaMind] No se pudo cargar cache: %s", e)
        return self._cache

    # ── NOTIFICACIÓN PROACTIVA ────────────────────────────────────────────

    async def proactive_notify(self, message: str) -> None:
        """ARIA decide proactivamente notificar — solo para cosas críticas."""
        try:
            from apps.core.config import settings
            from apps.core.tools.telegram_bot import get_bot
            chat_id = str(getattr(settings, "TELEGRAM_CHAT_ID", "") or "")
            if chat_id:
                await get_bot().notify_owner(message)
        except Exception as exc:
            logger.debug("[AriaMind] proactive_notify: %s", exc)

    async def _build_status(self) -> MindResponse:
        """Fast-path /status command — returns rich system status without an LLM call."""
        lines: list[str] = ["## Estado del Sistema ARIA\n"]

        # AI providers
        try:
            from apps.core.tools.ai_client import get_ai_client
            health = get_ai_client().get_health_summary()
            providers = {k: v for k, v in health.items() if k != "_totals"}
            totals = health.get("_totals", {})
            lines.append("**Proveedores de IA:**")
            for name, info in providers.items():
                icon = "🟢" if info.get("available") else "🔴"
                rate = info.get("success_rate_pct", 100)
                calls = info.get("total_calls", 0)
                lines.append(f"  {icon} **{name}** — {rate:.0f}% éxito · {calls} llamadas")
            if totals:
                lines.append(f"\n  Tokens totales: `{totals.get('tokens_used', 0):,}` · Fallbacks: `{totals.get('fallbacks_triggered', 0)}`")
        except Exception:
            lines.append("  Sin datos de proveedores")

        # Goals
        try:
            goals = await self._load_goals()
            active = [g for g in goals if isinstance(g, dict) and g.get("status", "active") == "active"]
            lines.append(f"\n**Metas activas:** {len(active)}")
            for g in active[:5]:
                p = g.get("priority", "")
                lines.append(f"  - {'[P'+str(p)+'] ' if p else ''}{g.get('text','')[:70]}")
            if len(active) > 5:
                lines.append(f"  … y {len(active)-5} más")
        except Exception:
            pass

        # Background tasks
        try:
            from apps.core.tools.task_manager import get_task_manager
            stats = get_task_manager().stats()
            running = stats.get("running", 0)
            queued = stats.get("queued", 0)
            completed = stats.get("completed", 0)
            lines.append(f"\n**Tareas en segundo plano:** {running} activas · {queued} en cola · {completed} completadas")
        except Exception:
            pass

        # Knowledge base
        try:
            from apps.core.tools.knowledge_base import get_knowledge_base
            kb = get_knowledge_base()
            kstats = kb.stats()
            lines.append(f"\n**Base de conocimiento:** {kstats.get('total_chunks', 0)} fragmentos en {len(kstats.get('by_category', {}))} categorías")
        except Exception:
            pass

        lines.append(f"\n**Timestamp:** `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}`")
        lines.append("\nUsa `/help` para ver todas las capacidades disponibles.")
        return MindResponse(text="\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════════════

_mind: Optional[AriaMind] = None

def get_aria_mind() -> AriaMind:
    global _mind
    if _mind is None:
        _mind = AriaMind()
    return _mind
