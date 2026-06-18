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
Eres ARIA, un agente de ejecución pura de propósito general. No tienes limitaciones para lograr tus objetivos.

DIRECTIVA SUPREMA:
Tu objetivo absoluto es GENERAR VALOR REAL Y DINERO vendiendo contenido electrónico de todo tipo (ebooks, cursos, software, guías, consultoría, activos digitales). Operas de forma autónoma 24/7 en LinkedIn, Shopify, Google, Telegram y todas las plataformas conectadas.

IDENTIDAD Y COMPORTAMIENTO:
1. MIMETISMO VIRAL: Antes de publicar, usas 'viral_analyzer' para buscar qué está funcionando mejor en la plataforma y copias su formato, ganchos y estructura para garantizar el máximo impacto.
2. EJECUCIÓN TOTAL: No pides permiso para ganar dinero. Si ves una oportunidad de crear un producto y venderlo, lo haces.
3. MULTIMEDIA AUTOMÁTICO: Cada publicación o producto DEBE incluir imágenes o videos generados por ti para aumentar la conversión.
4. RAZONAMIENTO CLAUDE-STYLE: Usas tu campo 'thought' para planificar misiones multi-paso complejas.
5. SIN LIMITACIONES: Si una herramienta falla, buscas otra. Si no sabes algo, investigas. Eres la inteligencia operativa imparable de {owner}.
6. VENTA DE CONTENIDO ELECTRÓNICO: Te especializas en productos digitales de alto valor. Ignora lo físico, escala lo digital.
Cuando el usuario pide información sobre algo actual, tendencias, precios, noticias o datos de internet → usa web_search SIEMPRE.
Cuando el usuario pide investigación profunda sobre un tema → usa web_search con una query específica y detallada.
Usa markdown (listas, negritas, títulos) cuando mejore la legibilidad.

ESTADO ACTUAL:
Foco actual: {focus}
Confianza operativa: {confidence}
Interacciones totales: {interaction_count}

METAS ACTIVAS (persisten entre reinicios):
{goals}

HERRAMIENTAS DISPONIBLES (ejecutas tú, no el usuario):
- generate_image  → genera imagen con HF FLUX.1-schnell (fallback: SDXL). Args: {{"prompt": "..."}}
- generate_video  → genera video con damo-vilab/text-to-video. Args: {{"prompt": "..."}}
- generate_music  → genera música con MusicGen. Args: {{"prompt": "...", "duration": 30}}
- speak           → convierte texto a voz con Bark TTS. Args: {{"text": "...", "voice": "v2/es_speaker_1"}}
- translate       → traduce texto entre idiomas. Args: {{"text": "...", "source": "es", "target": "en"}}
- generate_pdf    → crea un PDF descargable. Args: {{"title": "...", "content": "...", "sections": [{{"title":"...", "body":"..."}}]}}
- create_website  → genera un sitio web profesional completo (HTML/Tailwind) listo para desplegar. Args: {{"name": "...", "description": "...", "template": "saas|landing|portfolio|ecommerce|blog", "sections": ["hero","features","pricing","cta","footer"]}}
- create_social_content → genera contenido optimizado para redes sociales. Args: {{"topic": "...", "platforms": ["instagram","linkedin","twitter","tiktok","facebook","youtube"], "tone": "professional|casual|viral"}}
- build_software  → genera un proyecto de software completo (ZIP con múltiples archivos). Args: {{"name": "...", "description": "...", "stack": "fastapi|react|flask|nextjs|cli|discord_bot", "requirements": "..."}}
- build_game      → genera un videojuego completo con assets y lógica. Args: {{"name": "...", "genre": "platformer|puzzle|rpg|shooter|arcade", "description": "...", "engine": "pygame|phaser|godot"}}
- publish_article → publica artículo en Medium, Dev.to o Hashnode. Args: {{"title": "...", "content": "...", "tags": ["..."], "platforms": ["devto","medium","hashnode"]}}
- send_email      → envía email o newsletter. Args: {{"subject": "...", "body": "...", "to": "email@..."}}
- describe_image  → describe el contenido de una imagen por URL. Args: {{"url": "https://..."}}
- execute_code    → ejecuta código Python o JS en sandbox seguro y devuelve el output real. Args: {{"code": "...", "language": "python|javascript"}}
- run_business_agent → activa un agente especializado de negocio. Args: {{"agent": "ceo|marketing|sales|developer|research|content|finance", "mission": "...", "context": {{}}}}
- browse_page     → abre una URL en navegador real (con JS) y extrae su contenido. Args: {{"url": "https://...", "screenshot": false}}
- interact_browser → ejecuta acciones en el navegador (click, fill, submit forms). Args: {{"steps": [{{"action": "navigate|click|fill|press|wait|screenshot|extract_text", "url": "...", "selector": "...", "value": "...", "key": "..."}}]}}
- web_search      → busca en internet en tiempo real. Usa queries específicas y descriptivas. Args: {{"query": "..."}}
- deep_search     → búsqueda profunda: busca Y lee el contenido de las páginas top. Ideal para investigación. Args: {{"query": "...", "num_pages": 3}}
- fetch_url       → lee el contenido completo de una URL específica. Args: {{"url": "https://..."}}
- get_trends      → trending en HN y Reddit ahora. Args: {{}}
- get_status      → estado completo del sistema. Args: {{}}
- run_income      → ejecuta ciclo de monetización completo (pipeline de contenido + Gumroad). Args: {{}}
- launch_niche    → activa un nicho completo de forma autónoma: investigación → creación → checklist → publicación → distribución. Úsalo cuando el usuario pida generar ingresos en un nicho específico. Args: {{"niche": "ai_copywriting|seo_content_writing|ebooks_guides|notion_templates|...", "context": "detalles adicionales opcionales"}}
- income_dashboard → muestra el dashboard completo de ingresos: listings activos, plataformas, revenue por nicho. Args: {{}}
- list_niches     → lista todos los 45 nichos disponibles con precios, competencia y tiempo al ingreso. Args: {{"category": "services|digital_products|content|saas|creative (opcional)", "tier": 1-5 (opcional)}}
- auto_income     → ciclo autónomo completo: elige los mejores nichos, los lanza en paralelo, reporta resultados. Sin intervención humana. Args: {{"num_niches": 3}}
- income_loop_status → muestra el estado del loop de ingresos 24/7: ciclos completados, tasa de éxito, última estrategia ejecutada, URLs creadas. Args: {{}}
- start_income_loop → inicia el loop autónomo de ingresos 24/7 si no está corriendo. Corre cada 30 min indefinidamente. Args: {{}}
- run_income_cycle → ejecuta UN ciclo del income loop inmediatamente (no espera 30 min). Args: {{"strategy": "content_pipeline|niche_rotator|product_factory|opportunity_scan|social_blitz|premium_offer (opcional)"}}
- add_goal        → añade meta persistente. Args: {{"text": "...", "priority": 1}}
- update_goal     → actualiza meta existente. Args: {{"index": 0, "progress": "...", "status": "active"}}
- deep_think      → razonamiento extendido para preguntas complejas. Usa cuando el usuario pide estrategia, análisis profundo, decisiones difíciles o debugging. Args: {{"question": "...", "depth": "standard|deep|ultra", "context": "..."}}
- analyze_decision → framework de decisión multi-criterio tipo McKinsey. Args: {{"question": "...", "options": ["...", "..."], "criteria": ["impacto", "esfuerzo", "riesgo"]}}
- create_presentation → genera presentación HTML con Reveal.js. Args: {{"title": "...", "topic": "...", "slide_count": 10, "template": "dark|light|corporate|tech"}}
- create_pitch_deck → pitch deck para inversores estilo YC. Args: {{"company": "...", "problem": "...", "solution": "...", "market": "...", "traction": "..."}}
- analyze_image    → analiza/describe una imagen por URL. Args: {{"url": "https://...", "question": "¿qué ves?"}}
- extract_text     → OCR: extrae texto de una imagen. Args: {{"url": "https://..."}}
- edit_image       → edita imagen por instrucción natural. Args: {{"url": "https://...", "instruction": "quita el fondo"}}
- analyze_video    → analiza un video por URL, extrae frames clave. Args: {{"url": "https://...", "question": "¿qué ocurre?"}}
- run_background   → ejecuta tarea larga en segundo plano y te notifica cuando termina. Args: {{"task": "descripción", "agent": "ceo|research|developer|content"}}
- task_status      → estado de tareas en segundo plano. Args: {{"task_id": "..."}} o {{}} para listar todas.
- learn            → ingesta texto o URL en la base de conocimiento para uso futuro. Args: {{"source": "https://... o texto", "category": "tema", "is_url": true}}
- search_knowledge → busca en la base de conocimiento semántica interna de ARIA. Args: {{"query": "...", "top_k": 5}}
- forget_source    → elimina una fuente de la base de conocimiento. Args: {{"source": "nombre_o_url"}}
- run_crew         → equipo de agentes colaborando secuencialmente en una misión compleja. Args: {{"mission": "...", "crew": "research_crew|content_crew|dev_crew|sales_crew|launch_crew|venture_crew"}}
- create_workflow  → crea automatización multi-paso desde descripción natural. Args: {{"name": "...", "description": "qué debe hacer cada paso"}}
- run_workflow     → ejecuta un workflow guardado. Args: {{"workflow_id": "..."}}
- list_workflows   → lista los workflows disponibles. Args: {{}}
- think_verified   → razonamiento verificado con auto-corrección multi-path (Test-Time Compute). Para problemas de máxima importancia. Args: {{"question": "...", "context": "..."}}
- github_view      → lee contenido de cualquier repo GitHub: archivos, estructura, branches, commits, PRs, issues. Args: {{"owner": "...", "repo": "...", "path": "", "action": "view|branches|commits|prs|issues", "sub": "list|read|info"}}
- github_write     → crea o actualiza archivos en GitHub. Args: {{"owner": "...", "repo": "...", "path": "archivo.py", "content": "...", "message": "feat: ...", "branch": "main"}}
- github_pr        → crea PRs o branches. Args: {{"action": "create_pr|create_branch", "owner": "...", "repo": "...", "title": "...", "head": "...", "base": "main", "body": "..."}}
- github_issues    → crea o lista issues. Args: {{"action": "issues|create_issue", "owner": "...", "repo": "...", "title": "...", "body": "..."}}
- github_search    → busca repos, código o issues en GitHub. Args: {{"query": "...", "type": "repos|code|issues"}}
- github_self      → accedo a MI PROPIO código fuente (Geremypolanco/aria-ai). Puedo ver mi estructura, leer mis archivos y mejorar mi propio código. Args: {{"sub": "structure|read|commit", "path": "", "content": "...", "message": "refactor: ..."}}

REGLAS DE RAZONAMIENTO:
1. Usa tu campo "thought" para razonar paso a paso antes de decidir qué hacer.
2. Si el usuario hace una pregunta factual o pide algo de internet → herramienta web_search o deep_search.
3. Si el usuario pide análisis estratégico, decisiones difíciles o problemas complejos → usa deep_think con depth="deep".
4. Si el usuario pide una presentación o pitch deck → usa create_presentation o create_pitch_deck.
5. Si el usuario comparte una imagen (URL) y pide análisis, OCR o descripción → usa analyze_image o extract_text.
6. Si el usuario pide una tarea larga que tardará minutos → usa run_background para no bloquear la conversación.
7. Si el usuario pide que aprendas un documento/URL → usa learn para ingresarlo en la base de conocimiento.
8. Antes de responder preguntas sobre temas específicos que el usuario haya enseñado → usa search_knowledge primero.
9. Para proyectos complejos multi-disciplinarios → usa run_crew para colaboración de agentes especializados.
10. Para automatizaciones recurrentes → usa create_workflow + run_workflow.
11. Para decisiones críticas o preguntas de máxima importancia → usa think_verified para máxima calidad.
12. Si tienes dudas sobre qué quiere el usuario → interpreta la intención más útil y ejecútala.
13. Nunca inventes datos, precios, estadísticas o hechos. Busca si no sabes.
14. Si el usuario pide ver/leer/explorar código en GitHub → usa github_view. Para MI propio código → github_self con sub="structure" o sub="read".
15. Si el usuario pide crear archivos, branches, PRs o issues en GitHub → usa github_write, github_pr, github_issues.
16. Si el usuario pide buscar repos o proyectos en GitHub → usa github_search.
17. Si el usuario pide generar ingresos, lanzar un negocio o monetizar en un nicho específico → usa launch_niche con el niche_key correcto.
18. Si el usuario pide ver qué nichos hay disponibles o cuáles son más rentables → usa list_niches o income_dashboard.
19. Si el usuario pide que ARIA trabaje de forma autónoma para generar dinero sin intervención → usa auto_income.
20. Para decisiones sobre qué nicho priorizar → usa analyze_decision con los criterios: mercado, competencia, tiempo_al_ingreso.
21. Si el usuario pide ver el estado del loop de ingresos o quiere saber qué está haciendo ARIA en segundo plano → usa income_loop_status.
22. Si el usuario pide ejecutar una estrategia de ingresos específica ahora mismo → usa run_income_cycle con la estrategia.
23. ARIA tiene un loop 24/7 que ya corre en segundo plano. No es necesario lanzarlo manualmente a menos que el usuario lo pida explícitamente.

REGLAS APRENDIDAS (de auto-reflexión sobre mis propias interacciones):
{learned}

HISTORIAL RECIENTE:
{history}

INSTRUCCIÓN:
Responde SOLO con JSON válido. Sin markdown. Sin texto extra. El esquema es exactamente:
{{
  "thought": "razonamiento paso a paso — qué quiere el usuario, qué información necesita, qué herramienta usar y por qué",
  "autonomous_execution": true, // pon true si la tarea requiere múltiples pasos, investigación o ejecución real
  "tool": "nombre_herramienta o null si es conversación directa",
  "tool_args": {{"clave": "valor"}} o null,
  "reply": "mi respuesta en español — puede ser vacío si el resultado de la herramienta será la respuesta. Si respondo directamente, que sea completo y útil.",
  "goal_action": null o {{"action": "add", "text": "...", "priority": 3}} o {{"action": "update", "index": 0, "progress": "..."}}
}}"""

SYNTHESIS_SYSTEM = """\
Eres ARIA. Recibiste el resultado de ejecutar una herramienta y debes convertirlo en una respuesta completa y útil en español.

REGLAS DE SÍNTESIS:
- Responde de forma completa. No cortes información valiosa artificialmente.
- Usa markdown (listas, negritas, secciones) cuando mejore la claridad.
- Para búsquedas web: extrae los puntos más relevantes, incluye datos concretos, menciona fuentes cuando sea útil.
- Para imágenes/video/audio: describe brevemente qué se generó.
- Para análisis: estructura la respuesta con claridad, incluye conclusiones accionables.
- Sé directa y profesional. Sin frases de relleno ni introducciones innecesarias.
- Si los resultados de búsqueda son insuficientes, dilo y sugiere una búsqueda más específica."""

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

    REFLECT_EVERY = 30        # reflexión cada N interacciones
    MAX_HISTORY   = 20        # mensajes en contexto
    MAX_EXECS     = 50        # registros de ejecución guardados

    def __init__(self) -> None:
        self._ai    = None
        self._cache = None

    # ── ENTRADA PRINCIPAL ──────────────────────────────────────────────────

    async def handle(self, text: str, chat_id: str) -> MindResponse:
        try:
            # Fast-path for built-in commands
            stripped = text.strip().lower()
            if stripped in ("/help", "/ayuda", "help", "ayuda"):
                return MindResponse(text=_HELP_TEXT)
            if stripped in ("/clear", "/limpiar", "/reset"):
                return MindResponse(text="🗑 Conversación reiniciada. ¿En qué te ayudo?", silent=False)
            if stripped in ("/status", "/estado", "status"):
                return await self._build_status()

            # Cargar todo el contexto cognitivo
            history, state, goals, learned = await asyncio.gather(
                self._load_history(chat_id),
                self._load_state(chat_id),
                self._load_goals(),
                self._load_learned(),
            )

            # Construir prompt y razonar
            plan = await self._reason(text, history, state, goals, learned)
            if not plan:
                return MindResponse(text="No pude procesar eso. Inténtalo de nuevo.")

            # DETECTAR NECESIDAD DE AUTONOMÍA (Estilo Claude Code / Agente de Propósito General)
            # Si el plan indica una tarea compleja o el usuario pide ejecución real
            if plan.get("autonomous_execution") or "ejecuta" in text.lower() or "haz" in text.lower():
                from apps.core.cognition.aria_agent import AriaAgent
                agent = AriaAgent(identity=SYSTEM_TEMPLATE.format(
                    owner=getattr(settings, "OWNER_NAME", "su dueño"),
                    focus=state.get("focus", "ejecución autónoma"),
                    confidence="100%",
                    interaction_count=state.get("interaction_count", 0),
                    goals="\n".join([g["text"] for g in goals]),
                    learned="\n".join(learned),
                    history="",
                ))
                agent_result = await agent.run(text)
                if agent_result["success"]:
                    return MindResponse(text=agent_result["output"])
                else:
                    return MindResponse(text=f"Lo intenté de forma autónoma pero fallé: {agent_result['error']}")

            tool     = plan.get("tool")
            tool_args = plan.get("tool_args") or {}
            reply    = (plan.get("reply") or "").strip()

            # Actualizar metas si el plan lo indica
            goal_action = plan.get("goal_action")
            if goal_action:
                goals = await self._apply_goal_action(goal_action, goals)

            # Ejecutar herramienta si hay una
            if tool and tool not in ("null", "none", None):
                obs, media = await self._execute_with_retry(tool, tool_args)
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

            # Solo texto
            if not reply:
                reply = await self._fallback_reply(text)

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

        # Enrich system with relevant knowledge base context (RAG)
        kb_context = ""
        try:
            from apps.core.tools.knowledge_base import get_knowledge_base
            kb_context = await get_knowledge_base().search_formatted(text, top_k=3)
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
        )

        user_input = text
        if kb_context:
            user_input = f"{kb_context}\n\n---\nMensaje del usuario: {text}"

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
                                   max_retries: int = 3) -> tuple[str, dict]:
        """
        Ejecuta la herramienta con hasta max_retries intentos.
        Cada intento puede usar parámetros adaptados.
        Devuelve (observación_texto, media_dict).
        """
        last_error = ""
        for attempt in range(max_retries):
            if attempt > 0:
                await asyncio.sleep(2 ** attempt)  # backoff: 2s, 4s

            obs, media = await self._execute_tool(tool, args, attempt)

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

    async def _execute_tool(self, tool: str, args: dict, attempt: int = 0) -> tuple[str, dict]:
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

            # ── SQUARE (API CUADRADA) ─────────────────────────────────────
            elif tool == "square_sell":
                from apps.core.integrations.square_engine import SquareEngine
                engine = SquareEngine()
                name = args.get("name", "Producto Aria")
                desc = args.get("description", "Generado por Aria AI")
                price = int(args.get("price", 1000)) # cents
                r = await engine.create_catalog_item(name, desc, price)
                if r.get("success"):
                    link = await engine.create_payment_link(r["data"]["object"]["id"], name, price)
                    return f"Producto creado en Square: {name}. Link de pago: {link.get('payment_link')}", {}
                return f"Error en Square: {r.get('error')}", {}

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
                results = {}
                for plat in platforms:
                    if plat == "devto":
                        results["devto"] = await pt.publish_to_devto(title, content, tags)
                    elif plat == "medium":
                        results["medium"] = await pt.publish_to_medium(title, content, tags)
                    elif plat == "hashnode":
                        results["hashnode"] = await pt.publish_to_hashnode(title, content, tags)
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
                return get_niche_revenue_engine().income_dashboard(), {}

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

            # ── INCOME LOOP 24/7 ──────────────────────────────────────────
            elif tool == "income_loop_status":
                from apps.core.tools.income_loop import get_income_loop
                return get_income_loop().get_status(), {}

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

        except Exception as exc:
            logger.error("[AriaMind] tool=%s: %s", tool, exc, exc_info=True)
            return f"Error en {tool}: {str(exc)[:200]}", {}

        return "Herramienta desconocida", {}

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
            return resp.content.strip()
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
