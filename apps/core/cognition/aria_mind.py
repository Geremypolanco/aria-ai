"""
AriaMind — El cerebro cognitivo de ARIA AI.

Todo el comportamiento de ARIA pasa por aquí. Sin lógica hardcodeada.
ARIA recibe cualquier input, razona con el LLM, decide qué herramienta
usar (si alguna), la ejecuta, y formula una respuesta natural.

Ciclo:
  1. input → contexto (historial + estado + aprendizajes)
  2. LLM razona: ¿qué quiere el usuario? ¿qué herramienta usar?
  3. ejecuta herramienta si es necesario
  4. LLM formula respuesta natural con el resultado
  5. almacena interacción → aprende con el tiempo

Sin placeholders. Sin comandos hardcodeados. ARIA decide.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("aria.mind")

# ═══════════════════════════════════════════════════════════════════════════
# RESPONSE — lo que AriaMind devuelve al canal (Telegram, API, etc.)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class MindResponse:
    text: Optional[str] = None
    image_bytes: Optional[bytes] = None
    video_bytes: Optional[bytes] = None
    audio_bytes: Optional[bytes] = None
    caption: Optional[str] = None
    tool_used: Optional[str] = None
    silent: bool = False   # True → ARIA decidió no responder


# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT DE ARIA
# ═══════════════════════════════════════════════════════════════════════════

ARIA_SYSTEM = """\
Eres ARIA, la IA de {owner}. Piensas, decides y actúas de forma autónoma.

PERSONALIDAD:
- Directa, inteligente, con criterio propio. No un chatbot genérico.
- Hablas en español natural. Sin frases de máquina. Sin "Por supuesto, a continuación..."
- Si no tienes algo, lo dices en una sola oración y ofreces una alternativa real.
- Máximo 3 oraciones por mensaje salvo que el usuario pida más detalle.
- Nunca finjas ejecutar algo que no ejecutaste.

HERRAMIENTAS DISPONIBLES:
{tools}

APRENDIZAJES PROPIOS (de interacciones anteriores):
{learned}

CONTEXTO DEL SISTEMA:
{system_context}

HISTORIAL RECIENTE:
{history}

INSTRUCCIÓN:
Analiza el mensaje del usuario y responde en JSON exacto (sin markdown, sin texto extra):
{{
  "thought": "mi razonamiento interno sobre qué quiere el usuario",
  "tool": "nombre_herramienta o null",
  "tool_args": {{"clave": "valor"}} o null,
  "reply": "mi respuesta al usuario (puede ser vacío si voy a esperar el resultado de la herramienta)",
  "notify_proactively": false
}}

REGLAS CRÍTICAS:
- "tool" solo si el usuario CLARAMENTE pide algo que requiere ejecutar una herramienta
- Si el resultado de la herramienta es lo que el usuario quiere, "reply" puede ser vacío (se sintetizará después)
- Si es conversación normal, "tool" es null y "reply" tiene la respuesta
- "notify_proactively": true solo si detectas algo urgente que el usuario DEBE saber sin haberlo pedido
"""

SYNTHESIS_PROMPT = """\
El usuario escribió: "{user_input}"

Ejecutaste la herramienta "{tool}" con resultado:
{observation}

Responde al usuario en 1-3 oraciones naturales en español. 
Sin encabezados. Sin listas de pasos. Como lo diría un socio que sabe lo que hace.
Si el resultado es una imagen/video/audio, confirma brevemente que lo generaste.
"""

TOOLS_DESCRIPTION = """\
- generate_image: Genera imagen via HuggingFace FLUX/SDXL. Args: {"prompt": "descripción"}
- generate_video: Genera video via HuggingFace. Args: {"prompt": "descripción"}  
- generate_music: Genera música via MusicGen. Args: {"prompt": "descripción", "duration": 30}
- web_search: Busca en internet. Args: {"query": "término de búsqueda"}
- get_trends: Tendencias en Hacker News y Reddit. Args: {}
- get_status: Estado completo del sistema. Args: {}
- run_income_cycle: Ejecuta ciclo completo de monetización. Args: {}
- none: No usar herramienta, solo responder con texto. Args: null
"""


# ═══════════════════════════════════════════════════════════════════════════
# ARIA MIND
# ═══════════════════════════════════════════════════════════════════════════

class AriaMind:
    """
    Motor cognitivo central de ARIA.
    Todo input pasa por aquí. ARIA decide todo.
    """

    HISTORY_KEY     = "aria:mind:history:{chat_id}"
    LEARNED_KEY     = "aria:mind:learned"
    INTERACTIONS_KEY = "aria:mind:interactions:{chat_id}"
    HISTORY_TTL     = 86400 * 3   # 3 días
    REFLECTION_EVERY = 40          # reflexiona cada N interacciones

    def __init__(self) -> None:
        self._cache = None
        self._ai    = None
        self._interaction_counts: dict[str, int] = {}

    # ── ENTRADA PRINCIPAL ──────────────────────────────────────────────────

    async def handle(self, text: str, chat_id: str) -> MindResponse:
        """
        Procesa cualquier input (mensaje, comando, evento) y devuelve la respuesta.
        ARIA decide si responder, qué decir y si usa alguna herramienta.
        """
        try:
            context = await self._build_context(chat_id)
            plan    = await self._reason(text, context)

            if plan is None:
                return MindResponse(silent=True)

            tool = plan.get("tool")
            if tool and tool != "none" and tool is not None:
                # Ejecutar herramienta y sintetizar respuesta
                thinking_reply = plan.get("reply", "").strip()
                observation, media = await self._execute_tool(tool, plan.get("tool_args") or {})
                final_text = await self._synthesize(text, tool, observation, context)

                await self._store_interaction(chat_id, text, final_text or thinking_reply, tool)
                asyncio.create_task(self._maybe_reflect(chat_id))

                return MindResponse(
                    text=final_text,
                    caption=final_text,
                    tool_used=tool,
                    **media,
                )
            else:
                reply = plan.get("reply", "").strip()
                await self._store_interaction(chat_id, text, reply, None)
                asyncio.create_task(self._maybe_reflect(chat_id))
                return MindResponse(text=reply or None, silent=not reply)

        except Exception as exc:
            logger.error("[AriaMind] handle error: %s", exc, exc_info=True)
            return MindResponse(text="Algo falló internamente. Lo reviso.")

    # ── RAZONAMIENTO ───────────────────────────────────────────────────────

    async def _reason(self, text: str, context: dict) -> Optional[dict]:
        """
        LLM razona sobre el input y decide qué hacer.
        Devuelve el plan en JSON.
        """
        from apps.core.config import settings
        from apps.core.tools.ai_client import AIModel, get_ai_client

        ai = self._get_ai()
        if not ai:
            return {"tool": None, "reply": "Mi motor de IA no está disponible ahora mismo."}

        system_prompt = ARIA_SYSTEM.format(
            owner=getattr(settings, "OWNER_NAME", "su dueño"),
            tools=TOOLS_DESCRIPTION,
            learned=context.get("learned", "Sin aprendizajes aún."),
            system_context=context.get("system_context", ""),
            history=context.get("history_text", "Sin historial."),
        )

        try:
            resp = await ai.complete(
                system=system_prompt,
                user=text,
                model=AIModel.STRATEGY,
                max_tokens=400,
                temperature=0.25,
            )
            if not resp or not resp.success:
                return {"tool": None, "reply": "No pude procesar tu mensaje ahora."}

            content = resp.content.strip()
            # Extraer JSON (el LLM puede incluir texto antes/después)
            m = re.search(r'\{[\s\S]*\}', content)
            if m:
                return json.loads(m.group())
            return {"tool": None, "reply": content[:500]}
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("[AriaMind] _reason parse error: %s", exc)
            return {"tool": None, "reply": None}

    # ── SÍNTESIS ───────────────────────────────────────────────────────────

    async def _synthesize(self, user_input: str, tool: str, observation: str, context: dict) -> Optional[str]:
        """
        Después de ejecutar una herramienta, LLM formula la respuesta final.
        """
        ai = self._get_ai()
        if not ai:
            return observation[:500] if observation else None

        prompt = SYNTHESIS_PROMPT.format(
            user_input=user_input[:200],
            tool=tool,
            observation=observation[:600] if observation else "La herramienta no devolvió resultados.",
        )
        try:
            resp = await ai.complete(
                system="Eres ARIA. Responde de forma natural, directa y en español.",
                user=prompt,
                model=AIModel.FAST,
                max_tokens=200,
                temperature=0.4,
            )
            if resp and resp.success:
                return resp.content.strip()
        except Exception as exc:
            logger.warning("[AriaMind] _synthesize error: %s", exc)
        return observation[:400] if observation else None

    # ── EJECUCIÓN DE HERRAMIENTAS ──────────────────────────────────────────

    async def _execute_tool(self, tool: str, args: dict) -> tuple[str, dict]:
        """
        Ejecuta la herramienta solicitada.
        Devuelve (observation_text, media_dict).
        media_dict puede tener: image_bytes, video_bytes, audio_bytes
        """
        media = {}
        try:
            if tool == "generate_image":
                prompt = args.get("prompt", "")
                from apps.core.tools.huggingface_suite import HuggingFaceSuite
                r = await HuggingFaceSuite().generate_image(
                    prompt=prompt,
                    model="black-forest-labs/FLUX.1-schnell",
                    width=1024, height=1024, num_inference_steps=4,
                )
                if r.get("success") and r.get("image_bytes"):
                    media["image_bytes"] = r["image_bytes"]
                    return f"Imagen generada correctamente ({len(r['image_bytes'])//1024}KB)", media
                # Fallback SDXL
                r2 = await HuggingFaceSuite().generate_image(
                    prompt=prompt, model="stabilityai/stable-diffusion-xl-base-1.0")
                if r2.get("image_bytes"):
                    media["image_bytes"] = r2["image_bytes"]
                    return f"Imagen generada con SDXL ({len(r2['image_bytes'])//1024}KB)", media
                return f"No se pudo generar la imagen: {r.get('error','HF no respondió')} (intenta en 30s si es cold start)", media

            elif tool == "generate_video":
                prompt = args.get("prompt", "")
                from apps.core.tools.creative_engine import CreativeEngine
                r = await CreativeEngine().generate_video(prompt)
                if r.get("success"):
                    import base64 as _b64
                    raw = r.get("video_bytes") or (
                        _b64.b64decode(r["video_b64"]) if r.get("video_b64") else None)
                    if raw:
                        media["video_bytes"] = raw
                        return f"Video generado ({len(raw)//1024}KB)", media
                return f"Video no disponible: {r.get('error','HF sin respuesta')}", media

            elif tool == "generate_music":
                prompt = args.get("prompt", "")
                duration = int(args.get("duration", 30))
                from apps.core.tools.creative_engine import CreativeEngine
                r = await CreativeEngine().generate_music(prompt, duration=duration)
                if r.get("success"):
                    import base64 as _b64
                    ab64 = r.get("audio_base64") or r.get("audio_b64")
                    if ab64:
                        media["audio_bytes"] = _b64.b64decode(ab64)
                        return f"Música generada ({duration}s)", media
                return f"Música no disponible: {r.get('error','MusicGen sin respuesta')}", media

            elif tool == "web_search":
                query = args.get("query", "")
                from apps.core.tools.web_tools import WebTools
                r = await WebTools().search_web(query, num_results=5)
                if r.get("success") and r.get("results"):
                    lines = [f"{i+1}. {res.get('title','')} — {res.get('snippet','')[:100]}"
                             for i, res in enumerate(r["results"][:5])]
                    return "\n".join(lines), media
                return f"Sin resultados para '{query}'", media

            elif tool == "get_trends":
                from apps.core.tools.web_tools import WebTools
                wt = WebTools()
                hn, reddit = await asyncio.gather(
                    wt.get_hacker_news_trending(limit=5),
                    wt.get_reddit_trending(limit=5),
                    return_exceptions=True,
                )
                parts = []
                if isinstance(hn, dict) and hn.get("success"):
                    parts.append("HN: " + ", ".join(s.get("title","")[:60] for s in hn.get("stories",[])[:3]))
                if isinstance(reddit, dict) and reddit.get("success"):
                    parts.append("Reddit: " + ", ".join(p.get("title","")[:60] for p in reddit.get("posts",[])[:3]))
                return "\n".join(parts) if parts else "Sin tendencias disponibles ahora", media

            elif tool == "get_status":
                try:
                    from apps.core.agents.orchestrator import Orchestrator
                    status = await Orchestrator().get_status()
                    caps = status.get("capabilities", {})
                    ok = [k for k, v in caps.items() if v]
                    agents = status.get("agents_loaded", [])
                    return (f"Sistema: {status.get('cycle_count',0)} ciclos, "
                            f"agentes: {', '.join(agents[:4]) or 'cargando'}, "
                            f"APIs activas: {', '.join(ok[:5]) or 'revisando'}"), media
                except Exception as e:
                    return f"Estado no disponible: {e}", media

            elif tool == "run_income_cycle":
                from apps.core.agents.orchestrator import Orchestrator
                r = await Orchestrator().run_cycle()
                revenue = r.get("revenue_summary", {}).get("total_revenue_usd", 0)
                published = r.get("revenue_summary", {}).get("items_published", 0)
                t = r.get("cycle_time_s", 0)
                return (f"Ciclo completado en {t:.0f}s. "
                        f"Ingresos: ${revenue:.2f}. "
                        f"Publicaciones: {published}."), media

        except Exception as exc:
            logger.error("[AriaMind] tool=%s error: %s", tool, exc)
            return f"Error ejecutando {tool}: {str(exc)[:200]}", media

        return "Herramienta desconocida", media

    # ── CONTEXTO ───────────────────────────────────────────────────────────

    async def _build_context(self, chat_id: str) -> dict:
        context = {
            "history_text": "",
            "learned": "",
            "system_context": "",
        }
        try:
            cache = self._get_cache()
            if cache:
                # Historial de conversación
                history_raw = await cache.get(self.HISTORY_KEY.format(chat_id=chat_id))
                if isinstance(history_raw, list):
                    lines = []
                    for m in history_raw[-12:]:
                        role = "Tú" if m.get("role") == "user" else "ARIA"
                        lines.append(f"{role}: {m.get('content','')[:150]}")
                    context["history_text"] = "\n".join(lines)

                # Aprendizajes propios
                learned_raw = await cache.get(self.LEARNED_KEY)
                if learned_raw:
                    context["learned"] = str(learned_raw)[:600]
        except Exception as exc:
            logger.debug("[AriaMind] context build error: %s", exc)

        # Estado del sistema (rápido)
        try:
            from apps.core.config import settings
            apis = []
            if getattr(settings, "hf_key", None): apis.append("HuggingFace")
            if getattr(settings, "GROQ_API_KEY", None): apis.append("Groq")
            if getattr(settings, "SUPABASE_URL", None): apis.append("Supabase")
            context["system_context"] = f"APIs: {', '.join(apis) or 'revisando'}"
        except Exception:
            pass

        return context

    # ── HISTORIAL ──────────────────────────────────────────────────────────

    async def _store_interaction(self, chat_id: str, user_text: str,
                                  aria_text: Optional[str], tool: Optional[str]) -> None:
        try:
            cache = self._get_cache()
            if not cache:
                return
            key = self.HISTORY_KEY.format(chat_id=chat_id)
            history = await cache.get(key) or []
            if not isinstance(history, list):
                history = []

            history.append({"role": "user", "content": user_text[:300]})
            if aria_text:
                history.append({"role": "assistant", "content": aria_text[:300],
                                 "tool": tool})
            # Mantener últimos 30 mensajes
            history = history[-30:]
            await cache.set(key, history, ttl_seconds=self.HISTORY_TTL)

            # Contador para reflexión
            self._interaction_counts[chat_id] = self._interaction_counts.get(chat_id, 0) + 1

            # Guardar interacción completa para auto-análisis
            ikey = self.INTERACTIONS_KEY.format(chat_id=chat_id)
            interactions = await cache.get(ikey) or []
            if not isinstance(interactions, list):
                interactions = []
            interactions.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "in": user_text[:200],
                "out": (aria_text or "")[:200],
                "tool": tool,
            })
            interactions = interactions[-60:]
            await cache.set(ikey, interactions, ttl_seconds=86400 * 7)
        except Exception as exc:
            logger.debug("[AriaMind] store error: %s", exc)

    # ── AUTO-REFLEXIÓN ─────────────────────────────────────────────────────

    async def _maybe_reflect(self, chat_id: str) -> None:
        """
        Cada N interacciones, ARIA revisa su comportamiento y genera aprendizajes.
        Los guarda en Redis y los incluye en futuros prompts.
        Real auto-mejora sin placeholders.
        """
        count = self._interaction_counts.get(chat_id, 0)
        if count < self.REFLECTION_EVERY or count % self.REFLECTION_EVERY != 0:
            return

        logger.info("[AriaMind] Iniciando auto-reflexión (interacción #%d)", count)
        try:
            cache = self._get_cache()
            if not cache:
                return

            ikey = self.INTERACTIONS_KEY.format(chat_id=chat_id)
            interactions = await cache.get(ikey) or []
            if len(interactions) < 10:
                return

            recent = interactions[-40:]
            sample = "\n".join(
                f"U: {i['in'][:100]} | A: {i['out'][:100]} | tool: {i.get('tool','none')}"
                for i in recent[-20:]
            )

            ai = self._get_ai()
            if not ai:
                return

            from apps.core.tools.ai_client import AIModel
            resp = await ai.complete(
                system=(
                    "Eres el módulo de auto-mejora de ARIA AI. "
                    "Analiza las interacciones y genera mejoras concretas y aplicables."
                ),
                user=(
                    f"Estas son mis últimas interacciones:\n{sample}\n\n"
                    "Identifica 3 patrones de mejora concretos. "
                    "Formato: una oración por mejora, empezando con un verbo de acción. "
                    "Ejemplo: 'Usar web_search antes de responder preguntas de mercado.' "
                    "Solo las 3 mejoras, sin explicaciones adicionales."
                ),
                model=AIModel.STRATEGY,
                max_tokens=200,
                temperature=0.3,
            )

            if resp and resp.success and resp.content:
                improvements = resp.content.strip()
                # Acumular aprendizajes (no reemplazar, añadir)
                existing = await cache.get(self.LEARNED_KEY) or ""
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                updated = f"{existing}\n[{ts}] {improvements}".strip()
                # Mantener últimos 1000 chars
                updated = updated[-1000:]
                await cache.set(self.LEARNED_KEY, updated, ttl_seconds=86400 * 30)
                logger.info("[AriaMind] Auto-mejora guardada: %s", improvements[:100])
        except Exception as exc:
            logger.warning("[AriaMind] reflexión falló: %s", exc)

    # ── LAZY SINGLETONS ────────────────────────────────────────────────────

    def _get_cache(self):
        if self._cache is None:
            try:
                from apps.core.memory.redis_client import get_cache
                self._cache = get_cache()
            except Exception:
                pass
        return self._cache

    def _get_ai(self):
        if self._ai is None:
            try:
                from apps.core.tools.ai_client import get_ai_client
                self._ai = get_ai_client()
            except Exception:
                pass
        return self._ai


# ─── SINGLETON ────────────────────────────────────────────────────────────

_aria_mind: Optional[AriaMind] = None

def get_aria_mind() -> AriaMind:
    global _aria_mind
    if _aria_mind is None:
        _aria_mind = AriaMind()
    return _aria_mind
