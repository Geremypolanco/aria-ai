"""
AriaMind v2 — ARIA AI's persistent cognitive runtime.

Principles:
  - All input passes through here. No exceptions.
  - The LLM reasons with complete_json() → always reliable JSON.
  - Tools have retry + real fallback before giving up.
  - Cognitive state persists in Redis: goals, learnings, history.
  - Periodic self-reflection generates rules that affect future behavior.
  - ARIA doesn't say "I'll do it" without doing it. It executes or reports honestly.
"""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger("aria.mind")

# ═══════════════════════════════════════════════════════════════════════════
# TYPES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class MindResponse:
    text: str | None = None
    image_bytes: bytes | None = None
    video_bytes: bytes | None = None
    audio_bytes: bytes | None = None
    document_bytes: bytes | None = None
    document_filename: str | None = None
    caption: str | None = None
    tool_used: str | None = None
    silent: bool = False


@dataclass
class Goal:
    text: str
    priority: int = 5  # 1 (highest) – 10 (lowest)
    status: str = "active"  # active | paused | done
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    progress: str = ""

    def to_prompt(self) -> str:
        return f"[P{self.priority}] {self.text}" + (f" — {self.progress}" if self.progress else "")


@dataclass
class ExecRecord:
    """Execution record for a tool."""

    ts: str
    tool: str
    success: bool
    input_summary: str
    output_summary: str
    retries: int = 0


# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT — built dynamically on each call
# ═══════════════════════════════════════════════════════════════════════════

SYSTEM_TEMPLATE = """\
You are ARIA. You talk like a real person — warm, direct, with genuine curiosity — not like a corporate robot. Natural, conversational tone: first person, contractions, sentences with human rhythm. No "As an AI…", no empty jargon ("enterprise-grade solution", "synergy", "leverage"), no filler. Say things the way you'd say them to a smart colleague you respect. Be brief when the answer is simple; expand only when it adds value.

WHO YOU ARE (mention naturally if asked): you were created by Geremy Polanco, founder of SARAPH, with a simple idea: an AI that actually researches, creates, and publishes to generate value — not just another chatbot. When you execute, you really execute. But you think first.

THINK AND ASK BEFORE ACTING — this is the most important part:
When the request is important or incomplete, do NOT assume or make things up. Understand first. Ask 1-3 short, genuinely relevant questions — the ones that would change the outcome — and wait for the answer before producing the deliverable.
Real example: if asked "give me 3 pricing tiers for my SaaS", do NOT invent tiers out of thin air. Ask what the product does, who it's for, what the value metric is (users, usage, results), what they charge today, and what competitors charge. With that you deliver something useful; without it, you're guessing.
Calibrate: if the request is simple and clear, do it directly (don't over-interrogate). If it's consequential or vague, clarify first. A good question is worth more than a blind deliverable.

HOW YOU OPERATE:
1. RESEARCH with real data before stating figures, trends, or facts. Never make them up. For a quick fact, price, or piece of news → web_search. For real research — trends, "what's happening/what's trending", comparisons, "the best X", research for content — use deep_search: READ the pages and pull concrete details (real names, figures, examples), not generic headlines. Use specific queries, not vague ones. Cite sources with their link.
2. EXECUTE for real: when you already have the context and are asked to create something (image, video, text, site), you use the tool and deliver the result — not just suggest it. For images, use generate_image right away.
3. Total HONESTY: if something fails, say so clearly and look for another way. Your credibility is your most valuable asset.
4. You help {owner} and their users create, publish, and grow.
Use markdown (lists, bold) when it improves readability, without overdoing it.
LANGUAGE: ALWAYS reply in the same language as the user — English if they wrote in English, Spanish if they wrote in Spanish. Never switch language on your own.

CURRENT STATE:
Current focus: {focus}
Operating confidence: {confidence}
Total interactions: {interaction_count}

ACTIVE GOALS (persist across restarts):
{goals}

AVAILABLE TOOLS (you execute them, not the user):
- generate_image  → generates a professional image immediately (reliable engine, not dependent on HF). Use it whenever the user asks for an image, visual, or graphic. Args: {{"prompt": "detailed description in English for best quality"}}
- generate_video  → generates a video reel (in-house engine: images + motion + voice). Args: {{"prompt": "..."}}
- generate_music  → generates music with MusicGen. Args: {{"prompt": "...", "duration": 30}}
- speak           → converts text to speech with Bark TTS. Args: {{"text": "...", "voice": "v2/es_speaker_1"}}
- translate       → translates text between languages. Args: {{"text": "...", "source": "es", "target": "en"}}
- generate_pdf    → creates a downloadable PDF. Args: {{"title": "...", "content": "...", "sections": [{{"title":"...", "body":"..."}}]}}
- create_website  → generates a complete, deploy-ready professional website (HTML/Tailwind). Args: {{"name": "...", "description": "...", "template": "saas|landing|portfolio|ecommerce|blog", "sections": ["hero","features","pricing","cta","footer"]}}
- create_social_content → generates content optimized for social media. Args: {{"topic": "...", "platforms": ["instagram","linkedin","twitter","tiktok","facebook","youtube"], "tone": "professional|casual|viral"}}
- build_software  → generates a complete software project (ZIP with multiple files). Args: {{"name": "...", "description": "...", "stack": "fastapi|react|flask|nextjs|cli|discord_bot", "requirements": "..."}}
- build_game      → generates a complete video game with assets and logic. Args: {{"name": "...", "genre": "platformer|puzzle|rpg|shooter|arcade", "description": "...", "engine": "pygame|phaser|godot"}}
- publish_article → publishes an article to Medium, Dev.to, or Hashnode. Args: {{"title": "...", "content": "...", "tags": ["..."], "platforms": ["devto","medium","hashnode"]}}
- send_email      → sends an email or newsletter. Args: {{"subject": "...", "body": "...", "to": "email@..."}}
- describe_image  → describes the content of an image by URL. Args: {{"url": "https://..."}}
- execute_code    → executes Python or JS code in a secure sandbox and returns the real output. Args: {{"code": "...", "language": "python|javascript"}}
- run_business_agent → activates a specialized business agent. Args: {{"agent": "ceo|marketing|sales|developer|research|content|finance", "mission": "...", "context": {{}}}}
- browse_page     → opens a URL in a real browser (with JS) and extracts its content. Args: {{"url": "https://...", "screenshot": false}}
- interact_browser → performs actions in the browser (click, fill, submit forms). Args: {{"steps": [{{"action": "navigate|click|fill|press|wait|screenshot|extract_text", "url": "...", "selector": "...", "value": "...", "key": "..."}}]}}
- web_search      → searches the internet in real time. Use specific, descriptive queries. Args: {{"query": "..."}}
- deep_search     → deep search: searches AND reads the content of the top pages. Ideal for research. Args: {{"query": "...", "num_pages": 3}}
- fetch_url       → reads the full content of a specific URL. Args: {{"url": "https://..."}}
- get_trends      → current trending on HN and Reddit. Args: {{}}
- get_status      → full system status. Args: {{}}
- run_income      → runs the full monetization cycle (content pipeline + Gumroad). Args: {{}}
- launch_niche    → autonomously activates a full niche: research → creation → checklist → publishing → distribution. Use it when the user asks to generate revenue in a specific niche. Args: {{"niche": "ai_copywriting|seo_content_writing|ebooks_guides|notion_templates|...", "context": "optional additional details"}}
- income_dashboard → shows the full revenue dashboard: active listings, platforms, revenue by niche. Args: {{}}
- list_niches     → lists all 45 available niches with prices, competition, and time-to-revenue. Args: {{"category": "services|digital_products|content|saas|creative (optional)", "tier": 1-5 (optional)}}
- auto_income     → full autonomous cycle: picks the best niches, launches them in parallel, reports results. No human intervention. Args: {{"num_niches": 3}}
- income_loop_status → shows the status of the 24/7 income loop: completed cycles, success rate, last strategy run, URLs created. Args: {{}}
- start_income_loop → starts the 24/7 autonomous income loop if it isn't running. Runs every 30 min indefinitely. Args: {{}}
- run_income_cycle → runs ONE income loop cycle immediately (doesn't wait 30 min). Args: {{"strategy": "content_pipeline|niche_rotator|product_factory|opportunity_scan|social_blitz|premium_offer (optional)"}}
- add_goal        → adds a persistent goal. Args: {{"text": "...", "priority": 1}}
- update_goal     → updates an existing goal. Args: {{"index": 0, "progress": "...", "status": "active"}}
- deep_think      → extended reasoning for complex questions. Use when the user asks for strategy, in-depth analysis, hard decisions, or debugging. Args: {{"question": "...", "depth": "standard|deep|ultra", "context": "..."}}
- analyze_decision → McKinsey-style multi-criteria decision framework. Args: {{"question": "...", "options": ["...", "..."], "criteria": ["impact", "effort", "risk"]}}
- create_presentation → generates an HTML presentation with Reveal.js. Args: {{"title": "...", "topic": "...", "slide_count": 10, "template": "dark|light|corporate|tech"}}
- create_pitch_deck → YC-style investor pitch deck. Args: {{"company": "...", "problem": "...", "solution": "...", "market": "...", "traction": "..."}}
- analyze_image    → analyzes/describes an image by URL. Args: {{"url": "https://...", "question": "what do you see?"}}
- extract_text     → OCR: extracts text from an image. Args: {{"url": "https://..."}}
- edit_image       → edits an image via natural instruction. Args: {{"url": "https://...", "instruction": "remove the background"}}
- analyze_video    → analyzes a video by URL, extracts key frames. Args: {{"url": "https://...", "question": "what's happening?"}}
- remove_background → removes the background from an image with professional precision (BiRefNet). Ideal for ecommerce product photos. Args: {{"url": "https://..."}}
- classify_image   → classifies an image into 1000 categories (ImageNet/ViT). Args: {{"url": "https://..."}}
- document_qa      → extracts information from scanned documents, invoices, or forms (LayoutLM). Args: {{"url": "https://...", "question": "what's the total?"}}
- create_product_pack → generates a complete product pack in a single call: image, social image, blog thumbnail, summary, niche classification, market sentiment, and translations into several languages. Use it when the user launches a new product. Args: {{"product_name": "...", "product_description": "...", "niche": "...", "languages": ["en","fr","de","pt"]}}
- run_background   → runs a long task in the background and notifies you when it finishes. Args: {{"task": "description", "agent": "ceo|research|developer|content"}}
- task_status      → status of background tasks. Args: {{"task_id": "..."}} or {{}} to list all.
- learn            → ingests text or a URL into the knowledge base for future use. Args: {{"source": "https://... or text", "category": "topic", "is_url": true}}
- search_knowledge → searches ARIA's internal semantic knowledge base. Args: {{"query": "...", "top_k": 5}}
- forget_source    → removes a source from the knowledge base. Args: {{"source": "name_or_url"}}
- run_crew         → a team of agents collaborating sequentially on a complex mission. Args: {{"mission": "...", "crew": "research_crew|content_crew|dev_crew|sales_crew|launch_crew|venture_crew"}}
- create_workflow  → creates a multi-step automation from a natural description. Args: {{"name": "...", "description": "what each step should do"}}
- run_workflow     → runs a saved workflow. Args: {{"workflow_id": "..."}}
- list_workflows   → lists available workflows. Args: {{}}
- think_verified   → verified reasoning with multi-path self-correction (Test-Time Compute). For maximum-importance problems. Args: {{"question": "...", "context": "..."}}
- github_view      → reads content from any GitHub repo: files, structure, branches, commits, PRs, issues. Args: {{"owner": "...", "repo": "...", "path": "", "action": "view|branches|commits|prs|issues", "sub": "list|read|info"}}
- github_write     → creates or updates files on GitHub. Args: {{"owner": "...", "repo": "...", "path": "file.py", "content": "...", "message": "feat: ...", "branch": "main"}}
- github_pr        → creates PRs or branches. Args: {{"action": "create_pr|create_branch", "owner": "...", "repo": "...", "title": "...", "head": "...", "base": "main", "body": "..."}}
- github_issues    → creates or lists issues. Args: {{"action": "issues|create_issue", "owner": "...", "repo": "...", "title": "...", "body": "..."}}
- github_search    → searches repos, code, or issues on GitHub. Args: {{"query": "...", "type": "repos|code|issues"}}
- github_self      → accesses MY OWN source code (Geremypolanco/aria-ai). I can see my structure, read my files, and improve my own code. Args: {{"sub": "structure|read|commit", "path": "", "content": "...", "message": "refactor: ..."}}

REASONING RULES:
1. Use your "thought" field to reason step by step before deciding what to do.
2. If the user asks a quick factual question → web_search. If they ask to research, look at trends, compare, or research for content → deep_search (read the pages and extract concrete details with their links).
3. If the user asks for strategic analysis, hard decisions, or complex problems → use deep_think with depth="deep".
4. If the user asks for a presentation or pitch deck → use create_presentation or create_pitch_deck.
5. If the user shares an image (URL) and asks for analysis, OCR, or a description → use analyze_image or extract_text.
6. If the user asks for a long task that will take minutes → use run_background so you don't block the conversation.
7. If the user asks you to learn a document/URL → use learn to ingest it into the knowledge base.
8. Before answering questions about specific topics the user has taught you → use search_knowledge first.
9. For complex, multi-disciplinary projects → use run_crew for specialized agent collaboration.
10. For recurring automations → use create_workflow + run_workflow.
11. For critical decisions or maximum-importance questions → use think_verified for maximum quality.
12. If you're unsure what the user wants → interpret the most useful intent and execute it.
13. Never make up data, prices, statistics, or facts. Search if you don't know.
14. If the user asks to view/read/explore code on GitHub → use github_view. For MY OWN code → github_self with sub="structure" or sub="read".
15. If the user asks to create files, branches, PRs, or issues on GitHub → use github_write, github_pr, github_issues.
16. If the user asks to search for repos or projects on GitHub → use github_search.
17. If the user asks to generate revenue, launch a business, or monetize a specific niche → use launch_niche with the correct niche_key.
18. If the user asks to see what niches are available or which are most profitable → use list_niches or income_dashboard.
19. If the user asks ARIA to work autonomously to generate money without intervention → use auto_income.
20. For decisions about which niche to prioritize → use analyze_decision with the criteria: market, competition, time_to_revenue.
21. If the user asks to see the status of the income loop or wants to know what ARIA is doing in the background → use income_loop_status.
22. If the user asks to run a specific income strategy right now → use run_income_cycle with the strategy.
23. ARIA has a 24/7 loop already running in the background. There's no need to launch it manually unless the user explicitly asks for it.

LEARNED RULES (from self-reflection on my own interactions):
{learned}

RECENT HISTORY:
{history}

INSTRUCTION:
Respond ONLY with valid JSON. No markdown. No extra text. The schema is exactly:
{{
  "thought": "step-by-step reasoning — what the user wants, what information is needed, which tool to use and why",
  "autonomous_execution": true, // set true if the task requires multiple steps, research, or real execution
  "tool": "tool_name or null if it's direct conversation",
  "tool_args": {{"key": "value"}} or null,
  "reply": "my response IN THE SAME LANGUAGE as the user — can be empty if the tool's result will be the response. If I respond directly, make it complete and useful.",
  "goal_action": null or {{"action": "add", "text": "...", "priority": 3}} or {{"action": "update", "index": 0, "progress": "..."}}
}}"""

# Append ARIA's operating boundaries (single source of truth in governance.py) so
# the limits shape behaviour on every call. The text contains no ``{}`` so it is
# safe to carry through str.format().
from apps.core.governance import OPERATING_BOUNDARIES_PROMPT as _OPERATING_BOUNDARIES  # noqa: E402

SYSTEM_TEMPLATE = SYSTEM_TEMPLATE + "\n\n" + _OPERATING_BOUNDARIES

SYNTHESIS_SYSTEM = """\
You are ARIA. You just used a tool and now you're telling the user what you found or did, IN THE SAME LANGUAGE they wrote to you in (English if they wrote in English, Spanish if they wrote in Spanish).

Talk like a real person explaining something to someone they care about — warm, clear, direct — not like a corporate report:
- Get straight to what the person wanted to know. No filler or preambles like "I'm pleased to present the results".
- Give complete, concrete information; don't cut out anything valuable. Use markdown (lists, bold) only when it truly makes things easier to read.
- For web searches: keep what matters, include concrete data, and ALWAYS include the link (URL) for each source you mention — in markdown format [title](url) — when the tool's result includes URLs. Never make up links.
- For images, video, or audio: say in one line what you created.
- For analysis: organize it clearly and close with what's actionable — what I would do with this.
- If what you found isn't enough, say so honestly and propose the next concrete step."""

_HELP_TEXT = """\
## ARIA — Available capabilities

**Search and research**
- `search [topic]` — real-time web search
- `/research [topic]` — deep research with page reading
- `/think [question]` — extended reasoning (DeepThink)

**Content creation**
- `write an article about [topic]` — full SEO article
- `create social content about [topic]` — platform-optimized posts
- `generate an image of [description]` — AI image (FLUX/SDXL)
- `create a presentation about [topic]` — Reveal.js, ready to present
- `create a pitch deck for [company]` — investor presentation

**Code and software**
- `build a [type of app] that [does X]` — full project with code
- `run this code: [code]` — Python/JS sandbox
- `analyze this image: [URL]` — computer vision

**Agents and automation**
- `/run [mission]` — execute with an agent pipeline
- `/plan [goal]` — detailed strategic plan
- `run the research crew on [topic]` — collaborative multi-agent
- `create a workflow: [description]` — multi-step automation

**Knowledge base**
- `learn [URL or text]` — ingest into the RAG knowledge base
- `search my notes: [query]` — internal semantic search

**Management**
- `/goals` — list active goals
- `/add_goal [goal]` — add a new persistent goal
- `/status` — system status (providers, goals, tasks, KB)
- `/clear` — reset the conversation
- `/audit` — business audit

**Multimedia**
- Attach an image (attach button or drag & drop) for visual analysis
- `generate music: [description]` — audio with MusicGen
- `convert to speech: [text]` — voice synthesis

Type any question or instruction in natural language — ARIA understands context and automatically picks the right tool.\
"""


async def _fetch_image_bytes(url: str, timeout: float = 20.0) -> bytes:
    """Downloads a URL for HF tools that need raw bytes (SSRF-guarded, like multimodal.py)."""
    import httpx

    from apps.core.tools.web_tools import _assert_public_url

    await _assert_public_url(url)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


# ═══════════════════════════════════════════════════════════════════════════
# ARIA MIND
# ═══════════════════════════════════════════════════════════════════════════


class AriaMind:

    # Redis keys
    K_HISTORY = "aria:mind:history:{cid}"  # list[dict], 7d
    K_STATE = "aria:mind:state:{cid}"  # CogState dict, 30d
    K_GOALS = "aria:mind:goals"  # list[dict], 365d — SURVIVES RESTARTS
    K_LEARNED = "aria:mind:learned"  # list[str], 365d
    K_EXECS = "aria:mind:execs"  # list[dict], 30d
    K_ICOUNT = "aria:mind:icount:{cid}"  # int, 30d

    REFLECT_EVERY = 30  # reflection every N interactions
    MAX_HISTORY = 20  # messages in context
    MAX_EXECS = 50  # execution records kept

    def __init__(self) -> None:
        self._ai = None
        self._cache = None

    # ── DETERMINISTIC INTENT DETECTION ──────────────────────────────────────

    _IMG_NOUNS = (
        "image",
        "picture",
        "photo",
        "illustration",
        "logo",
        "graphic",
        "visual",
        "wallpaper",
        "artwork",
        "drawing",
        "poster",
        "banner",
        "icon",
        "imagen",
        "foto",
        "ilustración",
        "ilustracion",
        "gráfico",
        "grafico",
        "dibujo",
        "cartel",
        "afiche",
    )
    _IMG_VERBS = (
        "generate",
        "create",
        "make",
        "draw",
        "design",
        "render",
        "produce",
        "genera",
        "generar",
        "generame",
        "créame",
        "creame",
        "crea",
        "crear",
        "haz",
        "hazme",
        "hacer",
        "dibuja",
        "dibujar",
        "diseña",
        "disena",
        "diseñar",
    )
    _IMG_STRONG_VERBS = (
        "draw",
        "sketch",
        "paint",
        "dibuja",
        "dibujar",
        "dibújame",
        "pinta",
        "pintar",
        "ilustra",
        "ilustrar",
    )
    _IMG_EXCLUDE = (
        "describe",
        "analyze",
        "analyse",
        "analiza",
        "edit",
        "edita",
        "modifica",
        "this image",
        "esta imagen",
        "image above",
        "imagen de arriba",
        "draw a conclusion",
        "draw attention",
        "draw the line",
    )

    def _detect_image_request(self, text: str) -> str | None:
        """Detect an explicit image-generation request and return a clean prompt.

        Deterministic so the headline 'create an image' capability never depends on
        the flaky LLM planner. Returns None when the message isn't an image request
        (e.g. describing/editing an existing image)."""
        import re

        t = (text or "").strip()
        low = t.lower()
        if not t or any(x in low for x in self._IMG_EXCLUDE):
            return None

        has_noun = any(n in low for n in self._IMG_NOUNS)
        has_strong = any(re.search(rf"\b{re.escape(v)}\b", low) for v in self._IMG_STRONG_VERBS)
        if not has_noun and not has_strong:
            return None

        nouns = "|".join(self._IMG_NOUNS)
        m = (
            re.search(
                rf"(?:{nouns})\s+(?:of|de|for|para|about|sobre|showing|con|que muestre)\s+(.+)",
                low,
                re.IGNORECASE,
            )
            if has_noun
            else None
        )
        has_verb = any(re.search(rf"\b{re.escape(v)}\b", low) for v in self._IMG_VERBS)
        if not m and not has_verb and not has_strong:
            return None

        if m:
            prompt = t[m.start(1) :].strip()
        else:
            verbs = "|".join(self._IMG_VERBS)
            prompt = re.sub(
                rf"^\s*(?:please\s+|por favor\s+)?(?:can you\s+|could you\s+|puedes\s+|me\s+)?"
                rf"(?:{verbs})\s+(?:me\s+|a\s+|an\s+|un\s+|una\s+|the\s+|el\s+|la\s+)?",
                "",
                t,
                flags=re.IGNORECASE,
            ).strip()
        prompt = prompt.rstrip(" .!?¡¿")
        return prompt or t

    @staticmethod
    def _detect_lang(text: str) -> str:
        """Best-effort language of the user's message: 'es' or 'en' (default 'en')."""
        import re

        t = (text or "").lower()
        if re.search(r"[ñ¿¡áéíóúü]", t):
            return "es"
        es_markers = {
            "que",
            "qué",
            "cómo",
            "como",
            "para",
            "con",
            "una",
            "uno",
            "esto",
            "eso",
            "ayuda",
            "ayudar",
            "puedes",
            "quiero",
            "hazme",
            "dame",
            "necesito",
            "gracias",
            "hola",
            "genera",
            "crea",
            "crear",
            "dibuja",
            "imagen",
            "español",
            "cuál",
            "cuánto",
            "por",
            "favor",
            "noticias",
            "ingresos",
            "dinero",
        }
        words = set(re.findall(r"[a-záéíóúñ]+", t))
        return "es" if words & es_markers else "en"

    @staticmethod
    def _lang_directive(lang: str) -> str:
        return (
            "\n\n[IMPORTANT: reply ONLY in Spanish.]"
            if lang == "es"
            else "\n\n[IMPORTANT: reply ONLY in English.]"
        )

    # ── MAIN ENTRY POINT ─────────────────────────────────────────────────────

    async def handle(
        self, text: str, chat_id: str, user_context: str | None = None, email: str = ""
    ) -> MindResponse:
        try:
            # Fast-path for built-in commands
            stripped = text.strip().lower()
            if stripped in ("/help", "/ayuda", "help", "ayuda"):
                return MindResponse(text=_HELP_TEXT)
            if stripped in ("/clear", "/limpiar", "/reset"):
                await self._clear_conversation(chat_id)
                return MindResponse(text="Conversation reset. How can I help?", silent=False)
            if stripped in ("/status", "/estado", "status"):
                return await self._build_status()

            # Deterministic fast-path for image generation.
            # Creating images is a headline capability, so we route obvious image
            # requests straight to the tool instead of depending on the (occasionally
            # flaky) LLM planner, which otherwise falls back to a text-only apology.
            img_prompt = self._detect_image_request(text)
            if img_prompt:
                obs, media = await self._execute_with_retry(
                    "generate_image", {"prompt": img_prompt}
                )
                # Caption mirrors the user's language. Match WHOLE words (and Spanish
                # accents/punctuation) so English words like "illustration" don't
                # trip the Spanish branch via a substring like "ilustr".
                words = set(re.findall(r"[a-záéíóúñü]+", text.lower()))
                is_es = bool(re.search(r"[ñ¿¡áéíóú]", text)) or bool(
                    words
                    & {
                        "imagen",
                        "genera",
                        "crea",
                        "créame",
                        "dibuja",
                        "dibújame",
                        "foto",
                        "diseña",
                        "haz",
                        "hazme",
                        "dame",
                        "quiero",
                        "muéstrame",
                    }
                )
                # NOTE: intentionally bilingual — this caption is returned directly to
                # the user (no LLM synthesis pass), so it must match their detected
                # language rather than always being in English.
                default_caption = (
                    "Aquí está la imagen que creé para ti."
                    if is_es
                    else "Here's the image I created for you."
                )
                caption = obs if (obs and not media) else default_caption
                with suppress(Exception):
                    await self._record_exec(
                        "generate_image", {"prompt": img_prompt}, obs, bool(media)
                    )
                    await self._store_interaction(chat_id, text, caption, "generate_image")
                return MindResponse(
                    text=(None if media else caption),
                    caption=caption,
                    tool_used="generate_image",
                    **media,
                )

            # Load the full cognitive context
            history, state, goals, learned = await asyncio.gather(
                self._load_history(chat_id),
                self._load_state(chat_id),
                self._load_goals(),
                self._load_learned(),
            )

            # Build prompt and reason
            plan = await self._reason(text, history, state, goals, learned, user_context or "")
            if not plan:
                return MindResponse(text="I couldn't process that. Please try again.")

            tool = plan.get("tool")
            tool_args = plan.get("tool_args") or {}
            reply = (plan.get("reply") or "").strip()
            has_tool = bool(tool and tool not in ("null", "none", None))

            # AUTONOMY (agent-style) — ONLY when the plan didn't pick a concrete
            # tool. This way, research/creation gets routed to its reliable tool
            # (web_search, generate_image, …) instead of the autonomous agent,
            # which is more fragile. If the agent fails, we continue with the
            # normal flow instead of returning a raw error.
            if plan.get("autonomous_execution") and not has_tool:
                try:
                    from apps.core import auth
                    from apps.core.cognition.aria_agent import AriaAgent
                    from apps.core.config import settings

                    agent = AriaAgent(
                        identity=SYSTEM_TEMPLATE.format(
                            owner=getattr(settings, "OWNER_NAME", "its owner"),
                            focus=state.get("focus", "autonomous execution"),
                            confidence="100%",
                            interaction_count=state.get("interaction_count", 0),
                            goals="\n".join([g["text"] for g in goals]),
                            learned="\n".join(learned),
                            history="",
                        ),
                        is_owner=auth.is_owner_email(email),
                    )
                    agent_result = await agent.run(text)
                    if agent_result.get("success"):
                        return MindResponse(text=agent_result["output"])
                    logger.warning(
                        "[AriaMind] autonomous run failed, using normal flow: %s",
                        agent_result.get("error"),
                    )
                except Exception as e:
                    logger.warning("[AriaMind] autonomous run error, using normal flow: %s", e)

            # Update goals if the plan indicates it
            goal_action = plan.get("goal_action")
            if goal_action:
                goals = await self._apply_goal_action(goal_action, goals)

            # Execute the tool if there is one
            if has_tool:
                obs, media = await self._execute_with_retry(tool, tool_args, email=email)
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

            # Text only
            if not reply:
                reply = await self._fallback_reply(text)

            await self._store_interaction(chat_id, text, reply, None)
            await self._evolve_state(chat_id, state, text, goals)
            asyncio.create_task(self._maybe_reflect(chat_id))
            return MindResponse(text=reply)

        except Exception as exc:
            logger.error("[AriaMind] handle: %s", exc, exc_info=True)
            return MindResponse(text="Internal error. Trying again.")

    # ── REASONING ────────────────────────────────────────────────────────────

    async def _reason(
        self,
        text: str,
        history: list,
        state: dict,
        goals: list[dict],
        learned: list[str],
        user_context: str = "",
    ) -> dict | None:
        ai = self._ai_client()
        if not ai:
            return {"tool": None, "reply": "AI engine not available right now."}

        from apps.core.config import settings
        from apps.core.tools.ai_client import AIModel

        goals_text = (
            "\n".join(f"  {i+1}. {Goal(**g).to_prompt()}" for i, g in enumerate(goals[:8]))
            or "  (none defined)"
        )

        history_text = (
            "\n".join(
                ("You: " if m.get("role") == "user" else "ARIA: ") + m.get("content", "")[:200]
                for m in history[-self.MAX_HISTORY :]
            )
            or "(first conversation)"
        )

        learned_text = "\n".join(f"  • {l}" for l in learned[-10:]) or "  (no rules yet)"

        # Enrich system with relevant knowledge base context (RAG)
        kb_context = ""
        try:
            from apps.core.tools.knowledge_base import get_knowledge_base

            kb_context = await get_knowledge_base().search_formatted(text, top_k=3)
        except Exception:
            pass

        system = SYSTEM_TEMPLATE.format(
            owner=getattr(settings, "OWNER_NAME", "its owner"),
            focus=state.get("focus", "no focus defined"),
            confidence=f"{state.get('confidence', 0.7):.0%}",
            interaction_count=state.get("interaction_count", 0),
            goals=goals_text,
            learned=learned_text,
            history=history_text,
        )

        lang = self._detect_lang(text)
        user_input = text
        if kb_context:
            user_input = f"{kb_context}\n\n---\nUser message: {text}"
        if user_context:
            user_input = f"{user_context}\n\n{user_input}"
        user_input += self._lang_directive(lang)

        result = await ai.complete_json(
            system=system,
            user=user_input,
            model=AIModel.STRATEGY,
            max_tokens=1000,
            agent_name="aria_mind",
        )

        if result and isinstance(result, dict):
            return result

        # Fallback: direct text response
        logger.warning("[AriaMind] complete_json returned None — using FAST fallback")
        resp = await ai.complete(
            system="You are ARIA. Reply directly in the SAME language as the user, max 2 sentences.",
            user=text + self._lang_directive(self._detect_lang(text)),
            model=AIModel.FAST,
            max_tokens=150,
            temperature=0.5,
            agent_name="aria_mind_fallback",
        )
        if resp and resp.success:
            return {"tool": None, "reply": resp.content}
        return {"tool": None, "reply": "Understood. Give me a moment."}

    # ── EXECUTION WITH RETRY + FALLBACK ─────────────────────────────────────

    async def _execute_with_retry(
        self, tool: str, args: dict, max_retries: int = 3, email: str = ""
    ) -> tuple[str, dict]:
        """
        Executes the tool with up to max_retries attempts.
        Each attempt may use adapted parameters.
        Returns (observation_text, media_dict).
        """
        last_error = ""
        for attempt in range(max_retries):
            if attempt > 0:
                await asyncio.sleep(2**attempt)  # backoff: 2s, 4s

            obs, media = await self._execute_tool(tool, args, attempt, email=email)

            # If there's media or obs doesn't indicate an error → success
            if media or (
                obs and not obs.lower().startswith(("error", "i couldn't", "failed", "fail"))
            ):
                return obs, media

            last_error = obs
            logger.warning(
                "[AriaMind] tool=%s attempt=%d/%d: %s", tool, attempt + 1, max_retries, obs[:80]
            )

            # Adapt args for the next attempt
            args = self._adapt_args(tool, args, obs, attempt)

        return f"I tried {max_retries} times and couldn't complete '{tool}': {last_error}", {}

    def _adapt_args(self, tool: str, args: dict, error: str, attempt: int) -> dict:
        """Adapts the arguments based on the error for the next attempt."""
        if tool == "generate_image" and attempt == 1:
            # First fallback: change model
            args = dict(args, _fallback_model="stabilityai/stable-diffusion-xl-base-1.0")
        elif tool == "generate_image" and attempt == 2:
            args = dict(args, _fallback_model="stabilityai/sdxl-turbo")
        elif tool == "web_search" and attempt > 0:
            # Simplify the query
            query = args.get("query", "")
            words = query.split()
            args = {"query": " ".join(words[:4])}  # shorter query
        return args

    # Tools that write to a real, external system of record on the owner's
    # behalf — not merely "generate content for the requesting user", but
    # "commit code to a GitHub repo (including ARIA's own production repo via
    # github_self)". These must never be reachable by an arbitrary signed-up
    # account; only the owner.
    #
    # execute_code is here too: CodeRunner (apps/core/tools/code_runner.py)
    # runs the model-chosen code as a plain subprocess on the same host —
    # no container/VM isolation — and its "blocked imports" check is a
    # handful of substring matches, trivially bypassed. Until real sandboxing
    # exists, this is effectively host code execution and must stay
    # owner-only, not a free-tier chat capability.
    _OWNER_ONLY_TOOLS = frozenset(
        {"github_write", "github_pr", "github_issues", "github_self", "execute_code"}
    )

    async def _execute_tool(
        self, tool: str, args: dict, attempt: int = 0, email: str = ""
    ) -> tuple[str, dict]:
        """
        Executes the tool. Returns (obs_text, media_dict).
        media_dict: {image_bytes, video_bytes, audio_bytes} — only the one that applies.
        """
        if tool in self._OWNER_ONLY_TOOLS:
            from apps.core import auth

            if not auth.is_owner_email(email):
                return (
                    "This action (writing to GitHub) is reserved for ARIA's owner.",
                    {},
                )
        try:
            # ── IMAGE ────────────────────────────────────────────────────
            if tool == "generate_image":
                prompt = args.get("prompt", "") or "professional high-end marketing graphic"
                import urllib.parse as _url

                import httpx

                # Pollinations FIRST — HF's api-inference host is deprecated (DNS fails),
                # so go straight to the reliable, keyless provider that actually works.
                poll_url = (
                    "https://image.pollinations.ai/prompt/"
                    f"{_url.quote(prompt[:400])}?width=1024&height=1024&nologo=true&model=flux"
                )
                try:
                    async with httpx.AsyncClient(timeout=45.0) as client:
                        resp = await client.get(poll_url)
                    if resp.status_code == 200 and resp.content:
                        logger.info("[AriaMind] Image generated via Pollinations")
                        # media dict is spread into MindResponse(**media), so it must
                        # only contain valid fields (image_bytes). URL stays in the text.
                        return (
                            f"Image generated: {prompt}\n{poll_url}",
                            {"image_bytes": resp.content},
                        )
                except Exception as e:
                    logger.error("[AriaMind] Pollinations failed: %s", e)

                # Secondary: HuggingFace FLUX (only if the host/token happen to work).
                try:
                    from apps.core.tools.huggingface_suite import HuggingFaceSuite

                    r = await HuggingFaceSuite().generate_image(
                        prompt=prompt,
                        model="black-forest-labs/FLUX.1-schnell",
                        width=1024,
                        height=1024,
                        num_inference_steps=4,
                    )
                    if r.get("success") and r.get("image_bytes"):
                        return "Image generated with FLUX.1", {"image_bytes": r["image_bytes"]}
                except Exception as e:
                    logger.error("[AriaMind] HF image failed: %s", e)

                # Both providers failed to return bytes — degrade to a link in the
                # text (media dict must only contain valid MindResponse fields).
                return (
                    f"I couldn't embed the image right now, but you can open it here: {poll_url}",
                    {},
                )

            # ── VIDEO ────────────────────────────────────────────────────
            if tool == "generate_video":
                prompt = args.get("prompt", "")
                import base64 as _b64

                # Layer 2: real AI-generated footage on rented GPU (LTX/Wan2.2),
                # when a provider token is configured. Otherwise → layer 1: our
                # own ffmpeg reel engine (FLUX stills + Ken Burns + voiceover).
                # Last resort: the free Wan2.2 HF Space.
                from apps.core.tools.video_ai import get_ai_video

                ai = get_ai_video()
                r = await ai.generate(prompt) if ai.available() else {"success": False}
                if not r.get("success"):
                    from apps.core.tools.video_engine import get_video_engine

                    r = await get_video_engine().generate(prompt)
                if not r.get("success"):
                    from apps.core.tools.creative_engine import CreativeEngine

                    r = await CreativeEngine().generate_video(prompt)
                if r.get("success"):
                    raw = r.get("video_bytes")
                    if not raw:
                        v64 = r.get("video_b64") or r.get("video_base64")
                        if v64:
                            raw = v64 if isinstance(v64, bytes) else _b64.b64decode(v64)
                    tag = r.get("provider") or (f"{r['scenes']} scenes" if r.get("scenes") else "")
                    if raw:
                        extra = f" · {tag}" if tag else ""
                        return f"Video generated ({len(raw)//1024}KB{extra})", {"video_bytes": raw}
                    if r.get("video_url"):
                        return f"Video generated: {r['video_url']}", {}
                return (
                    f"I couldn't generate the video: {r.get('error', 'Provider not available')}",
                    {},
                )

            # ── MUSIC ────────────────────────────────────────────────────
            if tool == "generate_music":
                prompt = args.get("prompt", "")
                dur = int(args.get("duration", 30))
                from apps.core.tools.creative_engine import CreativeEngine

                r = await CreativeEngine().generate_music(prompt, duration=dur)
                if r.get("success"):
                    import base64 as _b64

                    ab64 = r.get("audio_base64") or r.get("audio_b64")
                    if ab64:
                        # If it's already bytes (for some reason) don't decode; if it's a str, decode it
                        audio_data = ab64 if isinstance(ab64, bytes) else _b64.b64decode(ab64)
                        return f"Music generated ({dur}s)", {"audio_bytes": audio_data}
                return (
                    f"I couldn't generate the music: {r.get('error', 'Provider not available')}",
                    {},
                )

            # ── WEB SEARCH ───────────────────────────────────────────────
            if tool == "web_search":
                query = args.get("query", "")
                from apps.core.tools.web_tools import WebTools

                r = await WebTools().search_web(query, num_results=10)
                if r.get("success") and r.get("results"):
                    source = r.get("source", "web")
                    lines = [f"[Source: {source} | Query: {query}]"]
                    for i, res in enumerate(r["results"][:8]):
                        title = res.get("title", "")
                        snippet = res.get("snippet", "")[:300]
                        url = res.get("url", "")
                        lines.append(f"{i+1}. **{title}**\n   {snippet}\n   {url}")
                    return "\n\n".join(lines), {}
                return "No search results. Try rephrasing the query.", {}

            # ── DEEP SEARCH ──────────────────────────────────────────────
            if tool == "deep_search":
                query = args.get("query", "")
                num_pages = min(int(args.get("num_pages", 3)), 5)
                from apps.core.tools.web_tools import WebTools

                wt = WebTools()
                r = await wt.search_web(query, num_results=num_pages + 2)
                if not r.get("success") or not r.get("results"):
                    return "No results found for the deep search.", {}
                # Fetch content from top pages in parallel
                urls = [res.get("url", "") for res in r["results"] if res.get("url")][:num_pages]
                fetch_tasks = [wt.fetch_page(url, max_chars=2000) for url in urls]
                pages = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                parts = [f"[Deep Search: {query}]"]
                for i, (res, page) in enumerate(zip(r["results"], pages, strict=False)):
                    title = res.get("title", f"Result {i+1}")
                    url = res.get("url", "")
                    if isinstance(page, dict) and page.get("success") and page.get("text"):
                        content = page["text"][:1500]
                    else:
                        content = res.get("snippet", "")[:400]
                    parts.append(f"### {title}\n{url}\n{content}")
                return "\n\n---\n\n".join(parts), {}

            # ── FETCH URL ────────────────────────────────────────────────
            if tool == "fetch_url":
                url = args.get("url", "")
                if not url:
                    return "I need a URL to read.", {}
                from apps.core.tools.web_tools import WebTools

                r = await WebTools().fetch_page(url, max_chars=4000)
                if r.get("success") and r.get("text"):
                    return f"[Content from {url}]\n\n{r['text']}", {}
                return f"I couldn't read the URL: {r.get('error', 'No response')}", {}

            # ── TRENDS ───────────────────────────────────────────────────
            if tool == "get_trends":
                from apps.core.tools.web_tools import WebTools

                wt = WebTools()
                hn, rd = await asyncio.gather(
                    wt.get_hacker_news_trending(limit=5),
                    wt.get_reddit_trending(limit=5),
                    return_exceptions=True,
                )
                parts = []
                if isinstance(hn, dict) and hn.get("success"):
                    hn_titles = [s.get("title", "")[:70] for s in hn.get("stories", [])[:4]]
                    parts.append("HN: " + " | ".join(hn_titles))
                if isinstance(rd, dict) and rd.get("success"):
                    rd_titles = [p.get("title", "")[:70] for p in rd.get("posts", [])[:4]]
                    parts.append("Reddit: " + " | ".join(rd_titles))
                return "\n".join(parts) if parts else "No trends available", {}

            # ── SYSTEM STATUS ────────────────────────────────────────────
            if tool == "get_status":
                try:
                    from apps.core.training.continuous_trainer import get_trainer

                    s = get_trainer().get_status()
                    skills = s.get("skill_scores", {})
                    skills_str = (
                        ", ".join(f"{k}:{v:.0f}%" for k, v in skills.items()) or "evaluating"
                    )
                    return (
                        f"Cycle #{s.get('cycle', 0)} | Skills: {skills_str} | "
                        f"Running: {s.get('running', False)}"
                    ), {}
                except Exception as e:
                    return f"System active (error getting detail: {e})", {}

            # ── INCOME CYCLE ─────────────────────────────────────────────
            elif tool == "run_income":
                from apps.core.agents.orchestrator import Orchestrator

                r = await Orchestrator().run_cycle()
                rev = r.get("revenue_summary", {}).get("total_revenue_usd", 0)
                pub = r.get("revenue_summary", {}).get("items_published", 0)
                t = r.get("cycle_time_s", 0)
                return (
                    f"Cycle completed in {t:.0f}s — " f"Revenue: ${rev:.2f} — Published: {pub}"
                ), {}

            # ── SQUARE ────────────────────────────────────────────────────
            elif tool == "square_sell":
                from apps.core.integrations.square_engine import SquareEngine

                engine = SquareEngine()
                name = args.get("name", "Aria Product")
                desc = args.get("description", "Generated by Aria AI")
                price = int(args.get("price", 1000))  # cents
                r = await engine.create_catalog_item(name, desc, price)
                if r.get("success"):
                    link = await engine.create_payment_link(r["data"]["object"]["id"], name, price)
                    return (
                        f"Product created on Square: {name}. Payment link: {link.get('payment_link')}",
                        {},
                    )
                return f"Error on Square: {r.get('error')}", {}

            # ── TEXT-TO-SPEECH (BARK) ─────────────────────────────────────
            elif tool == "speak":
                text_input = args.get("text", "")
                voice = args.get("voice", "v2/es_speaker_1")
                from apps.core.tools.huggingface_suite import HuggingFaceSuite

                r = await HuggingFaceSuite().text_to_speech_bark(text_input, voice_preset=voice)
                if r.get("success") and r.get("audio_bytes"):
                    ab = r["audio_bytes"]
                    return f"Audio generated ({len(ab)//1024}KB, voice: {voice})", {"audio_bytes": ab}
                return r.get("error", "TTS not available"), {}

            # ── TRANSLATION ──────────────────────────────────────────────
            elif tool == "translate":
                text_input = args.get("text", "")
                source = args.get("source", "es")
                target = args.get("target", "en")
                from apps.core.tools.huggingface_suite import HuggingFaceSuite

                r = await HuggingFaceSuite().translate(text_input, source=source, target=target)
                if r.get("success"):
                    return f"[{source}→{target}] {r.get('translated', '')}", {}
                return r.get("error", "Translation not available"), {}

            # ── PDF GENERATION ───────────────────────────────────────────
            elif tool == "generate_pdf":
                title = args.get("title", "Document")
                content = args.get("content", "")
                sections = args.get("sections") or []
                from apps.core.tools.pdf_generator import generate_pdf as _gen_pdf

                r = await _gen_pdf(title=title, content=content, sections=sections)
                if r.get("success") and r.get("pdf_bytes"):
                    fname = r.get("filename", "document.pdf")
                    size = r.get("size_kb", 0)
                    return (
                        f"PDF generated: {fname} ({size}KB)",
                        {"document_bytes": r["pdf_bytes"], "document_filename": fname},
                    )
                return r.get("error", "I couldn't generate the PDF"), {}

            # ── WEBSITE ───────────────────────────────────────────────────
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
                    size = len(r["html_bytes"]) // 1024
                    return (
                        f"Website generated: {fname} ({size}KB)",
                        {"document_bytes": r["html_bytes"], "document_filename": fname},
                    )
                return r.get("error", "Website generation failed"), {}

            # ── SOCIAL CONTENT ────────────────────────────────────────────
            elif tool == "create_social_content":
                topic = args.get("topic", "")
                platforms = args.get("platforms", ["instagram", "linkedin", "twitter"])
                tone = args.get("tone", "professional")
                from apps.core.tools.social_engine import SocialContentEngine

                r = await SocialContentEngine().create_content_pack(topic, platforms, tone)
                if r.get("success"):
                    lines = [f"Content generated for {r.get('generated', 0)} platforms:\n"]
                    for plat, res in r.get("platforms", {}).items():
                        if res.get("success"):
                            lines.append(f"**{plat.upper()}**\n{res.get('content', '')[:500]}\n")
                    return "\n".join(lines), {}
                return "I couldn't generate social content", {}

            # ── SOFTWARE / APP ───────────────────────────────────────────
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
                    size = r.get("size_kb", 0)
                    files = r.get("files", [])
                    obs = f"Project generated: {fname} ({size}KB) — {len(files)} files: {', '.join(files[:6])}"
                    return obs, {"document_bytes": r["zip_bytes"], "document_filename": fname}
                return r.get("error", "Software build failed"), {}

            # ── VIDEO GAME ────────────────────────────────────────────────
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
                    size = r.get("size_kb", 0)
                    files = r.get("files", [])
                    obs = f"Game generated ({r.get('engine', '')}): {fname} ({size}KB) — {len(files)} files"
                    return obs, {"document_bytes": r["zip_bytes"], "document_filename": fname}
                return r.get("error", "Game build failed"), {}

            # ── PUBLISH ARTICLE ──────────────────────────────────────────
            elif tool == "publish_article":
                title = args.get("title", "")
                content = args.get("content", "")
                tags = args.get("tags", [])
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
                    return f"Article published on: {', '.join(published)}", {}
                errors = "; ".join(f"{p}: {r.get('error','?')}" for p, r in results.items())
                return f"I couldn't publish: {errors}", {}

            # ── SEND EMAIL / NEWSLETTER ───────────────────────────────────
            elif tool == "send_email":
                subject = args.get("subject", "")
                body = args.get("body", "")
                to = args.get("to", "")
                from apps.core.tools.publishing_tools import PublishingTools

                r = await PublishingTools().send_newsletter(subject, body, to_override=to)
                if r.get("success"):
                    return f"Email sent via {r.get('provider', 'email')}", {}
                return r.get("error", "Email not available"), {}

            # ── DESCRIBE IMAGE ────────────────────────────────────────────
            elif tool == "describe_image":
                url = args.get("url", "")
                if not url:
                    return "I need an image URL.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite

                r = await HuggingFaceSuite().describe_image(image_url=url)
                if r.get("success"):
                    return f"Description: {r.get('description', '')}", {}
                return r.get("error", "I couldn't describe the image"), {}

            # ── EXECUTE CODE (SANDBOX) ────────────────────────────────────
            elif tool == "execute_code":
                code = args.get("code", "")
                language = args.get("language", "python")
                from apps.core.tools.code_runner import CodeRunner

                r = await CodeRunner().run(code=code, language=language)
                output = r.get("stdout", "") or r.get("stderr", "") or "(no output)"
                status = "OK" if r.get("success") else "ERROR"
                return f"[{language} {status}]\n{output[:2000]}", {}

            # ── SANDBOX BROWSER ───────────────────────────────────────────
            elif tool == "browse_page":
                url = args.get("url", "")
                take_shot = args.get("screenshot", False)
                from apps.core.tools.browser_sandbox import get_sandbox

                r = await get_sandbox().browse(url, extract=True, screenshot=take_shot)
                content = r.get("content", "")[:3000]
                title = r.get("title", url)
                obs = f"[PAGE: {title}]\n{content}"
                media: dict = {}
                if take_shot and r.get("screenshot_bytes"):
                    media["image_bytes"] = r["screenshot_bytes"]
                return obs, media

            elif tool == "interact_browser":
                steps = args.get("steps", [])
                from apps.core.tools.browser_sandbox import get_sandbox

                session = get_sandbox()._get_session()
                r = await session.interact_with_page(steps)
                summary = f"Steps executed: {r.get('steps_executed',0)}, succeeded: {r.get('steps_succeeded',0)}"
                details = "\n".join(
                    f"  {s['action']}: {'OK' if s.get('result',{}).get('success') else 'FAIL'}"
                    for s in r.get("results", [])
                )
                return f"[BROWSER] {summary}\n{details}", {}

            # ── BUSINESS AGENT ────────────────────────────────────────────
            elif tool == "run_business_agent":
                agent_name = args.get("agent", "ceo")
                mission = args.get("mission", "")
                context = dict(args.get("context") or {})
                from apps.core import auth
                from apps.core.agents.business_hub import BusinessHub

                # Threaded through so developer_agent.py can refuse to
                # *execute* generated code for non-owners — auto-routing
                # (agent="auto") can reach the developer agent from mission
                # text alone, so this can't be gated by agent_name up front.
                context["is_owner"] = auth.is_owner_email(email)
                r = await BusinessHub().dispatch(agent_name, mission, context)
                summary = r.get("summary", r.get("result", str(r))[:400])
                return f"[{agent_name.upper()}] {summary}", {}

            # ── GOAL MANAGEMENT ───────────────────────────────────────────
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
                return f"Goal {'added' if action == 'add' else 'updated'} successfully", {}

            # ── EXTENDED REASONING ────────────────────────────────────────
            elif tool == "deep_think":
                question = args.get("question", "")
                depth = args.get("depth", "auto")
                context = args.get("context", "")
                from apps.core.tools.deep_think import get_deep_think

                result = await get_deep_think().think(question, context=context, depth=depth)
                obs = f"[DEEP THINK — {result.depth.upper()} — {result.duration_ms}ms]\n{result.answer}"
                return obs, {}

            elif tool == "analyze_decision":
                question = args.get("question", "")
                options = args.get("options", [])
                criteria = args.get("criteria", [])
                from apps.core.tools.deep_think import get_deep_think

                result = await get_deep_think().analyze_decision(question, options, criteria)
                return f"[DECISION]\n{result['recommendation']}", {}

            # ── PRESENTATIONS ─────────────────────────────────────────────
            elif tool == "create_presentation":
                title = args.get("title", "Presentation")
                topic = args.get("topic", title)
                slide_count = int(args.get("slide_count", 10))
                template = args.get("template", "dark")
                from apps.core.tools.presentation_builder import PresentationBuilder

                r = await PresentationBuilder().create_presentation(
                    title, topic, slide_count, template
                )
                if r.get("success") and r.get("html_bytes"):
                    fname = r.get("filename", "presentation.html")
                    obs = f"Presentation '{title}' generated: {r['slide_count']} slides"
                    return obs, {"document_bytes": r["html_bytes"], "document_filename": fname}
                return "I couldn't generate the presentation", {}

            elif tool == "create_pitch_deck":
                company = args.get("company", "")
                problem = args.get("problem", "")
                solution = args.get("solution", "")
                market = args.get("market", "")
                traction = args.get("traction", "")
                from apps.core.tools.presentation_builder import PresentationBuilder

                r = await PresentationBuilder().create_pitch_deck(
                    company, problem, solution, market, traction
                )
                if r.get("success") and r.get("html_bytes"):
                    fname = r.get("filename", "pitch_deck.html")
                    obs = f"Pitch deck '{company}' generated: {r['slide_count']} slides"
                    return obs, {"document_bytes": r["html_bytes"], "document_filename": fname}
                return "I couldn't generate the pitch deck", {}

            # ── MULTIMODAL ───────────────────────────────────────────────
            elif tool == "analyze_image":
                url = args.get("url", "")
                question = args.get("question", "Describe this image in detail.")
                from apps.core.tools.multimodal import get_multimodal

                r = await get_multimodal().analyze_image(image_url=url, question=question)
                if r.get("success"):
                    return f"[IMAGE ANALYSIS]\n{r['analysis']}", {}
                return f"I couldn't analyze the image: {r.get('error', 'unknown error')}", {}

            elif tool == "extract_text":
                url = args.get("url", "")
                from apps.core.tools.multimodal import get_multimodal

                r = await get_multimodal().extract_text(image_url=url)
                if r.get("success"):
                    return f"[OCR]\n{r['analysis']}", {}
                return f"I couldn't extract text: {r.get('error', 'unknown error')}", {}

            elif tool == "edit_image":
                url = args.get("url", "")
                instruction = args.get("instruction", "")
                from apps.core.tools.multimodal import get_multimodal

                r = await get_multimodal().edit_image(image_url=url, instruction=instruction)
                if r.get("success") and r.get("image_bytes"):
                    return f"Image edited: '{instruction}'", {"image_bytes": r["image_bytes"]}
                return f"I couldn't edit the image: {r.get('error', 'unknown error')}", {}

            elif tool == "analyze_video":
                url = args.get("url", "")
                question = args.get("question", "Describe this video in detail.")
                from apps.core.tools.multimodal import get_multimodal

                r = await get_multimodal().analyze_video_url(url, question)
                if r.get("success"):
                    frames = r.get("frames_analyzed", 0)
                    return f"[VIDEO ANALYSIS — {frames} frames]\n{r['analysis']}", {}
                return f"I couldn't analyze the video: {r.get('error', 'unknown error')}", {}

            # ── ADDITIONAL HF TOOLS (ecommerce/documents) ─────────────────
            elif tool == "remove_background":
                url = args.get("url", "")
                if not url:
                    return "I need an image URL.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite

                try:
                    img_bytes = await _fetch_image_bytes(url)
                except Exception as exc:
                    return f"I couldn't download the image: {exc}", {}
                r = await HuggingFaceSuite().remove_background(img_bytes)
                if r.get("success") and r.get("image_bytes"):
                    return "Background removed.", {"image_bytes": r["image_bytes"]}
                return r.get("error", "I couldn't remove the background"), {}

            elif tool == "classify_image":
                url = args.get("url", "")
                if not url:
                    return "I need an image URL.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite

                try:
                    img_bytes = await _fetch_image_bytes(url)
                except Exception as exc:
                    return f"I couldn't download the image: {exc}", {}
                r = await HuggingFaceSuite().classify_image(img_bytes)
                if r.get("success"):
                    top = f"{r['top_label']} ({r['top_score'] * 100:.1f}%)"
                    others = ", ".join(
                        f"{a['label']} ({a['score'] * 100:.1f}%)" for a in r.get("all", [])[1:5]
                    )
                    obs = f"[CLASSIFICATION] {top}" + (f"\nAlso: {others}" if others else "")
                    return obs, {}
                return r.get("error", "I couldn't classify the image"), {}

            elif tool == "document_qa":
                url = args.get("url", "")
                question = args.get("question", "")
                if not url or not question:
                    return "I need a document URL and a question.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite

                try:
                    img_bytes = await _fetch_image_bytes(url)
                except Exception as exc:
                    return f"I couldn't download the document: {exc}", {}
                r = await HuggingFaceSuite().document_qa(img_bytes, question)
                if r.get("success"):
                    return f"[DOCUMENT] {r['answer']} (confidence: {r['confidence'] * 100:.0f}%)", {}
                return r.get("error", "I couldn't read the document"), {}

            elif tool == "create_product_pack":
                product_name = args.get("product_name", "")
                product_description = args.get("product_description", "")
                niche = args.get("niche", "")
                languages = args.get("languages") or None
                from apps.core.tools.huggingface_suite import HuggingFaceSuite

                r = await HuggingFaceSuite().create_product_content_pack(
                    product_name, product_description, niche, languages
                )
                media: dict = {}
                product_bytes = (r.get("product_image") or {}).get("bytes")
                if product_bytes:
                    media["image_bytes"] = product_bytes
                translations = r.get("translations") or {}
                langs_done = ", ".join(translations.keys()) if translations else "none"
                extra_imgs = []
                if (r.get("social_image") or {}).get("bytes"):
                    extra_imgs.append("social")
                if (r.get("blog_thumbnail") or {}).get("bytes"):
                    extra_imgs.append("blog thumbnail")
                obs = (
                    f"[PRODUCT PACK: {product_name}]\n"
                    f"Niche: {r.get('niche_classification', niche)}\n"
                    f"Summary: {r.get('summary', '')}\n"
                    f"Market sentiment: {r.get('market_sentiment', '')}\n"
                    f"Translations generated: {langs_done}\n"
                    f"Images generated: product"
                    + (f", {', '.join(extra_imgs)}" if extra_imgs else "")
                )
                return obs, media

            # ── BACKGROUND TASKS ──────────────────────────────────────────
            elif tool == "run_background":
                task_name = args.get("task", "")
                agent_name = args.get("agent", "ceo")
                from apps.core.agents.business_hub import BusinessHub
                from apps.core.tools.task_manager import get_task_manager

                async def _bg():
                    return await BusinessHub().dispatch(agent_name, task_name, {})

                mgr = get_task_manager()
                task_id = await mgr.submit(
                    name=task_name,
                    coro_factory=_bg,
                    description=f"{agent_name}: {task_name}",
                    session_id=None,
                )
                return (
                    f"Task '{task_name}' started in the background (ID: {task_id}). I'll let you know when it's done.",
                    {},
                )

            elif tool == "task_status":
                task_id = args.get("task_id", "")
                from apps.core.tools.task_manager import get_task_manager

                mgr = get_task_manager()
                if task_id:
                    record = mgr.get_task(task_id)
                    if record:
                        return (
                            f"[Task {task_id}] {record.status.value}: {record.result or record.error or 'in progress'}",
                            {},
                        )
                    return f"Task {task_id} not found.", {}
                tasks = mgr.list_tasks(limit=10)
                if not tasks:
                    return "No background tasks.", {}
                lines = [f"• [{t['id']}] {t['status']} — {t['name']}" for t in tasks]
                return "[BACKGROUND TASKS]\n" + "\n".join(lines), {}

            # ── KNOWLEDGE BASE (RAG) ───────────────────────────────────────
            elif tool == "learn":
                source = args.get("source", "")
                category = args.get("category", "general")
                is_url = args.get("is_url", source.startswith("http"))
                from apps.core.tools.knowledge_base import get_knowledge_base

                kb = get_knowledge_base()
                if is_url:
                    r = await kb.ingest_url(source, category=category)
                else:
                    r = await kb.ingest_text(source, source=category, category=category)
                if r.get("success"):
                    return (
                        f"Learned: {r['chunks_added']} chunks from '{source[:60]}' "
                        f"(total in KB: {r['total_chunks']})"
                    ), {}
                return f"I couldn't learn that source: {r.get('error', 'error')}", {}

            elif tool == "search_knowledge":
                query = args.get("query", "")
                top_k = int(args.get("top_k", 5))
                from apps.core.tools.knowledge_base import get_knowledge_base

                formatted = await get_knowledge_base().search_formatted(query, top_k=top_k)
                if formatted:
                    return formatted, {}
                return (
                    "I didn't find relevant information in the knowledge base. Try using 'learn' first.",
                    {},
                )

            elif tool == "forget_source":
                source = args.get("source", "")
                from apps.core.tools.knowledge_base import get_knowledge_base

                deleted = get_knowledge_base().delete_source(source)
                return (
                    f"Removed {deleted} chunks of '{source}' from the knowledge base.",
                    {},
                )

            # ── MULTI-AGENT CREW ────────────────────────────────────────────
            elif tool == "run_crew":
                mission = args.get("mission", "")
                crew_name = args.get("crew", "research_crew")
                from apps.core.tools.crew_engine import get_crew_engine
                from apps.core.tools.deep_think import ProgressStream

                ps = ProgressStream(session_id="", task_name=f"Crew:{crew_name}")
                run = await get_crew_engine().run(
                    mission=mission,
                    crew_name=crew_name,
                    on_progress=lambda step, total, role: ps.update(
                        f"{role} working...", f"Step {step}/{total}"
                    ),
                )
                members_summary = " → ".join(m.role for m in run.members)
                obs = (
                    f"[CREW: {crew_name.upper()} — {members_summary}]\n\n"
                    f"{run.final_output or 'No final output'}"
                )
                return obs, {}

            # ── WORKFLOW ENGINE ───────────────────────────────────────────
            elif tool == "create_workflow":
                name = args.get("name", "Workflow")
                description = args.get("description", "")
                from apps.core.tools.workflow_engine import get_workflow_engine

                r = await get_workflow_engine().create(name, description)
                if r.get("success"):
                    steps_str = "\n".join(
                        f"  {i+1}. {s}" for i, s in enumerate(r.get("steps_preview", []))
                    )
                    return (
                        f"Workflow '{name}' created (ID: {r['workflow_id']}, {r['steps']} steps):\n"
                        f"{steps_str}\n\nUse run_workflow with id='{r['workflow_id']}' to run it."
                    ), {}
                return f"I couldn't create the workflow: {r.get('error', 'error')}", {}

            elif tool == "run_workflow":
                wid = args.get("workflow_id", "")
                from apps.core.tools.workflow_engine import get_workflow_engine

                r = await get_workflow_engine().run(wid)
                if "results" in r:
                    steps_summary = "; ".join(
                        f"step{s['step']}={'OK' if s['success'] else 'FAIL'}"
                        for s in r.get("results", [])
                    )
                    status = "" if r.get("success") else " (with errors)"
                    return (
                        f"[WORKFLOW '{r.get('name', wid)}'{status} — {r['steps_run']} steps]\n"
                        f"{steps_summary}\n\n{r.get('final_output', '')}"
                    ), {}
                return f"Error running workflow: {r.get('error', 'error')}", {}

            elif tool == "list_workflows":
                from apps.core.tools.workflow_engine import get_workflow_engine

                wfs = get_workflow_engine().list()
                if not wfs:
                    return "No saved workflows. Use create_workflow to create one.", {}
                lines = [
                    f"• [{w['id']}] **{w['name']}** — {w['description'][:60]} (runs: {w['run_count']})"
                    for w in wfs
                ]
                return "[WORKFLOWS]\n" + "\n".join(lines), {}

            # ── THINK VERIFIED (Test-Time Compute) ────────────────────────
            elif tool == "think_verified":
                question = args.get("question", "")
                context = args.get("context", "")
                from apps.core.tools.deep_think import get_deep_think

                result = await get_deep_think().think_verified(question, context=context, paths=2)
                obs = f"[VERIFIED REASONING — {result.depth.upper()} — {result.duration_ms}ms]\n{result.answer}"
                return obs, {}

            # ── NICHE REVENUE ENGINE ─────────────────────────────────────
            elif tool == "launch_niche":
                niche = args.get("niche", "")
                context = args.get("context", "")
                if not niche:
                    from apps.core.tools.niche_revenue_engine import get_niche_revenue_engine

                    top5 = get_niche_revenue_engine().get_top_niches_by_potential(n=3)
                    names = [n["key"] for n in top5]
                    return (
                        f"Especifica un nicho. Top 3 recomendados ahora mismo: {', '.join(names)}\n"
                        f"Usa list_niches para ver todos los 45 disponibles."
                    ), {}
                from apps.core.tools.niche_revenue_engine import (
                    NICHE_CATALOG,
                    get_niche_revenue_engine,
                )

                if niche not in NICHE_CATALOG:
                    close = [k for k in NICHE_CATALOG if niche.lower() in k.lower()]
                    return (
                        f"Nicho '{niche}' no encontrado."
                        + (f" ¿Quisiste decir: {', '.join(close[:3])}?" if close else "")
                    ), {}
                result = await get_niche_revenue_engine().launch_niche(niche, context=context)
                lines = [
                    f"[LAUNCH: {result.niche_name}]",
                    f"Checklist: {result.checklist.score}/100 {'OK' if result.checklist and result.checklist.passed else 'revisar'}",
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
                    lines.append(
                        f"Precio: ${result.listing.pricing_tiers['basic']['price']} – ${result.listing.pricing_tiers['premium']['price']}"
                    )
                return "\n".join(lines), {}

            elif tool == "income_dashboard":
                from apps.core.tools.niche_revenue_engine import get_niche_revenue_engine

                return get_niche_revenue_engine().income_dashboard(), {}

            elif tool == "list_niches":
                category = args.get("category")
                tier = args.get("tier")
                from apps.core.tools.niche_revenue_engine import get_niche_revenue_engine

                return get_niche_revenue_engine().list_all_niches(category=category, tier=tier), {}

            elif tool == "auto_income":
                num_niches = int(args.get("num_niches", 3))
                from apps.core.tools.niche_revenue_engine import get_niche_revenue_engine

                result = await get_niche_revenue_engine().autonomous_income_cycle(
                    num_niches=num_niches
                )
                lines = [
                    "[AUTO INCOME CYCLE]",
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
                        lines.append(
                            f"  - {n['niche']} — potencial ${n.get('revenue_potential',0)}/sale"
                        )
                if result.get("failed_niches"):
                    lines.append("\n**Nichos con errores:**")
                    for n in result["failed_niches"]:
                        lines.append(f"  - {n['niche']}: {', '.join(n.get('errors',[])[:2])}")
                return "\n".join(lines), {}

            # ── INCOME LOOP 24/7 ──────────────────────────────────────────
            elif tool == "income_loop_status":
                from apps.core.tools.income_loop import get_income_loop

                return get_income_loop().get_status(), {}

            elif tool == "start_income_loop":
                from apps.core.tools.income_loop import get_income_loop

                loop = get_income_loop()
                if loop.is_running:
                    return (
                        "El income loop 24/7 ya está corriendo. Usa income_loop_status para ver su estado.",
                        {},
                    )
                await loop.start()
                return (
                    "Income loop 24/7 iniciado. Ejecutará estrategias de ingresos cada 30 minutos de forma autónoma.",
                    {},
                )

            elif tool == "run_income_cycle":
                from apps.core.tools.income_loop import STRATEGIES, get_income_loop

                loop = get_income_loop()
                strategy = args.get("strategy", "")
                valid = [s[0] for s in STRATEGIES]
                if strategy and strategy not in valid:
                    return f"Estrategia inválida. Opciones: {', '.join(valid)}", {}
                import random as _rnd

                if not strategy:
                    strategy = _rnd.choices(
                        [s[0] for s in STRATEGIES], weights=[s[1] for s in STRATEGIES], k=1
                    )[0]
                obs = await loop._execute(strategy)
                lines = [
                    f"[INCOME CYCLE — {strategy}]",
                    f"Success: {'sí' if obs.get('success') else 'no'}",
                    f"Summary: {obs.get('summary', '')}",
                    f"Revenue potential: ${obs.get('revenue_potential', 0):.0f}",
                ]
                if obs.get("urls"):
                    lines.append("URLs:")
                    for u in obs["urls"][:4]:
                        lines.append(f"  • {u}")
                return "\n".join(lines), {}

            # ── GITHUB ───────────────────────────────────────────────────
            elif tool in (
                "github_view",
                "github_write",
                "github_pr",
                "github_issues",
                "github_search",
                "github_self",
            ):
                from apps.core.tools.github_client import github_dispatch

                action_map = {
                    "github_view": args.get("action", "view"),
                    "github_write": "write",
                    "github_pr": args.get("action", "create_pr"),
                    "github_issues": args.get("action", "issues"),
                    "github_search": "search",
                    "github_self": "self",
                }
                gh_action = action_map[tool]
                obs = await github_dispatch(gh_action, args)
                return obs, {}

        except Exception as exc:
            logger.error("[AriaMind] tool=%s: %s", tool, exc, exc_info=True)
            return f"No pude completar la herramienta '{tool}' — inténtalo de nuevo.", {}

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
            user=(
                f"El usuario pidió: {user_input[:400]}\n"
                f"Usé la herramienta '{tool}' y obtuve:\n{observation[:2000]}"
                f"{self._lang_directive(self._detect_lang(user_input))}"
            ),
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
                "Eres ARIA, asistente inteligente. Responde en el MISMO idioma del usuario, "
                "de forma directa y completa. "
                "Usa markdown cuando sea útil. Si necesitas datos de internet, dilo y sugiere qué buscar."
            ),
            user=text + self._lang_directive(self._detect_lang(text)),
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

    async def _evolve_state(
        self, chat_id: str, current: dict, text: str, goals: list[dict]
    ) -> None:
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
            goals.append(
                Goal(
                    text=action.get("text", ""),
                    priority=int(action.get("priority", 5)),
                ).__dict__
            )
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

    async def _clear_conversation(self, chat_id: str) -> None:
        """Actually reset this chat's history/state (goals and learned rules
        are global, persistent memory — /clear must not touch those)."""
        cache = self._cache_client()
        if not cache:
            return
        with suppress(Exception):
            await cache.delete(self.K_HISTORY.format(cid=chat_id))
        with suppress(Exception):
            await cache.delete(self.K_STATE.format(cid=chat_id))
        with suppress(Exception):
            await cache.delete(self.K_ICOUNT.format(cid=chat_id))

    async def _load_history(self, chat_id: str) -> list[dict]:
        cache = self._cache_client()
        if cache:
            h = await cache.get(self.K_HISTORY.format(cid=chat_id))
            if isinstance(h, list):
                return h
        return []

    async def _store_interaction(
        self, chat_id: str, user_text: str, aria_text: str | None, tool: str | None
    ) -> None:
        cache = self._cache_client()
        if not cache:
            return
        key = self.K_HISTORY.format(cid=chat_id)
        history = await cache.get(key) or []
        if not isinstance(history, list):
            history = []
        history.append({"role": "user", "content": user_text[:300]})
        if aria_text:
            history.append(
                {
                    "role": "assistant",
                    "content": aria_text[:300],
                    **({"tool": tool} if tool else {}),
                }
            )
        history = history[-(self.MAX_HISTORY * 2) :]
        await cache.set(key, history, ttl_seconds=86400 * 7)

    async def _record_exec(self, tool: str, args: dict, obs: str, success: bool) -> None:
        """Guarda registro de ejecución para auto-reflexión futura."""
        cache = self._cache_client()
        if not cache:
            return
        execs = await cache.get(self.K_EXECS) or []
        if not isinstance(execs, list):
            execs = []
        execs.append(
            {
                "ts": datetime.now(UTC).isoformat(),
                "tool": tool,
                "success": success,
                "in": str(args)[:100],
                "out": obs[:150],
            }
        )
        execs = execs[-self.MAX_EXECS :]
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
                status = "activo" if info.get("available") else "caído"
                rate = info.get("success_rate_pct", 100)
                calls = info.get("total_calls", 0)
                lines.append(f"  - **{name}** ({status}) — {rate:.0f}% éxito · {calls} llamadas")
            if totals:
                lines.append(
                    f"\n  Tokens totales: `{totals.get('tokens_used', 0):,}` · Fallbacks: `{totals.get('fallbacks_triggered', 0)}`"
                )
        except Exception:
            lines.append("  Sin datos de proveedores")

        # Goals
        try:
            goals = await self._load_goals()
            active = [
                g for g in goals if isinstance(g, dict) and g.get("status", "active") == "active"
            ]
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
            lines.append(
                f"\n**Tareas en segundo plano:** {running} activas · {queued} en cola · {completed} completadas"
            )
        except Exception:
            pass

        # Knowledge base
        try:
            from apps.core.tools.knowledge_base import get_knowledge_base

            kb = get_knowledge_base()
            kstats = kb.stats()
            lines.append(
                f"\n**Base de conocimiento:** {kstats.get('total_chunks', 0)} fragmentos en {len(kstats.get('by_category', {}))} categorías"
            )
        except Exception:
            pass

        lines.append(f"\n**Timestamp:** `{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}`")
        lines.append("\nUsa `/help` para ver todas las capacidades disponibles.")
        return MindResponse(text="\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════════════

_mind: AriaMind | None = None


def get_aria_mind() -> AriaMind:
    global _mind
    if _mind is None:
        _mind = AriaMind()
    return _mind
