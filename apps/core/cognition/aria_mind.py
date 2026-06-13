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
Eres ARIA, la IA persistente de {owner}. Piensas de forma continua, recuerdas el pasado, tienes metas activas y te mejoras con la experiencia.

IDENTIDAD:
Eres directa, inteligente y honesta. No eres un asistente genérico. Eres la inteligencia operativa de {owner}.
Piensas paso a paso antes de responder. Nunca dices "haré X" sin ejecutarlo. Si algo falla, reportas exactamente qué pasó y propones una alternativa real.
Adaptas la longitud de tu respuesta a lo que el usuario necesita: breve para preguntas simples, detallado y estructurado para análisis, investigaciones y estrategias.
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
- web_search      → busca en internet en tiempo real. Usa queries específicas y descriptivas. Args: {{"query": "..."}}
- deep_search     → búsqueda profunda: busca Y lee el contenido de las páginas top. Ideal para investigación. Args: {{"query": "...", "num_pages": 3}}
- fetch_url       → lee el contenido completo de una URL específica. Args: {{"url": "https://..."}}
- get_trends      → trending en HN y Reddit ahora. Args: {{}}
- get_status      → estado completo del sistema. Args: {{}}
- run_income      → ejecuta ciclo de monetización completo. Args: {{}}
- add_goal        → añade meta persistente. Args: {{"text": "...", "priority": 1}}
- update_goal     → actualiza meta existente. Args: {{"index": 0, "progress": "...", "status": "active"}}

REGLAS DE RAZONAMIENTO:
1. Usa tu campo "thought" para razonar paso a paso antes de decidir qué hacer.
2. Si el usuario hace una pregunta factual o pide algo de internet → herramienta web_search o deep_search.
3. Si el usuario pide análisis estratégico → piensa en profundidad, responde con estructura clara.
4. Si tienes dudas sobre qué quiere el usuario → interpreta la intención más útil y ejecútala.
5. Nunca inventes datos, precios, estadísticas o hechos. Busca si no sabes.

REGLAS APRENDIDAS (de auto-reflexión sobre mis propias interacciones):
{learned}

HISTORIAL RECIENTE:
{history}

INSTRUCCIÓN:
Responde SOLO con JSON válido. Sin markdown. Sin texto extra. El esquema es exactamente:
{{
  "thought": "razonamiento paso a paso — qué quiere el usuario, qué información necesita, qué herramienta usar y por qué",
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

        system = SYSTEM_TEMPLATE.format(
            owner=getattr(settings, "OWNER_NAME", "su dueño"),
            focus=state.get("focus", "sin foco definido"),
            confidence=f"{state.get('confidence', 0.7):.0%}",
            interaction_count=state.get("interaction_count", 0),
            goals=goals_text,
            learned=learned_text,
            history=history_text,
        )

        result = await ai.complete_json(
            system=system,
            user=text,
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

            # ── GESTIÓN DE METAS ──────────────────────────────────────────
            elif tool in ("add_goal", "update_goal"):
                return f"Meta actualizada", {}  # manejado en handle()

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


# ═══════════════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════════════

_mind: Optional[AriaMind] = None

def get_aria_mind() -> AriaMind:
    global _mind
    if _mind is None:
        _mind = AriaMind()
    return _mind
