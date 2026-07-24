"""
presentation_builder.py — Generates professional presentations like Manus/slides.

ARIA can create:
  - Interactive HTML presentations (Reveal.js) from bullet points or a topic
  - Slides exportable as PDF (via Playwright screenshot)
  - Investor pitch decks
  - Product, training, and marketing presentations

Inspired by: Manus `slides` tool + Google Slides API
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

logger = logging.getLogger("aria.presentation_builder")

# Default Reveal.js CDN version
REVEAL_CDN = "https://cdnjs.cloudflare.com/ajax/libs/reveal.js/4.6.1"


class PresentationBuilder:
    """
    Generates HTML presentations with Reveal.js from:
    - A topic and description (ARIA generates the content)
    - A structured outline (list of slides)
    - Raw data (ARIA organizes it into slides)
    """

    async def create_presentation(
        self,
        title: str,
        topic: str,
        slide_count: int = 10,
        template: str = "dark",
        include_speaker_notes: bool = False,
    ) -> dict[str, Any]:
        """
        Generates a complete presentation from a topic.
        ARIA researches and generates the slides automatically.
        """
        # 1. Generate outline with AI
        outline = await self._generate_outline(title, topic, slide_count)

        # 2. Generate content for each slide
        slides = await self._generate_slides(title, topic, outline)

        # 3. Render HTML
        html = self._render_html(title, slides, template, include_speaker_notes)

        return {
            "success": True,
            "title": title,
            "slide_count": len(slides),
            "html_bytes": html.encode("utf-8"),
            "filename": f"{title.lower().replace(' ', '_')[:40]}_presentation.html",
            "template": template,
        }

    async def create_from_outline(
        self,
        title: str,
        outline: list[dict],
        template: str = "dark",
    ) -> dict[str, Any]:
        """
        Creates a presentation from a manual outline.
        outline: [{"title": "...", "bullets": ["...", "..."], "notes": "..."}]
        """
        slides = await self._enrich_slides(title, outline)
        html = self._render_html(title, slides, template, True)
        return {
            "success": True,
            "title": title,
            "slide_count": len(slides),
            "html_bytes": html.encode("utf-8"),
            "filename": f"{title.lower().replace(' ', '_')[:40]}.html",
        }

    async def create_pitch_deck(
        self,
        company: str,
        problem: str,
        solution: str,
        market: str = "",
        traction: str = "",
    ) -> dict[str, Any]:
        """
        Generates an investor pitch deck (YC style).
        10 slides: Problem, Solution, Market, Product, Traction,
                   Business Model, Team, Competition, Ask, Closing.
        """
        from apps.core.tools.ai_client import AIModel, get_ai_client

        client = get_ai_client()

        content = await client.complete(
            model=AIModel.STRATEGY,
            system="You are an expert in startup pitch decks. You create compelling presentations for YC/a16z investors.",
            user=(
                f"Company: {company}\n"
                f"Problem: {problem}\n"
                f"Solution: {solution}\n"
                f"Market: {market or 'To be defined'}\n"
                f"Traction: {traction or 'Pre-launch'}\n\n"
                f"Generate a 10-slide pitch deck in JSON:\n"
                f'[{{"title": "...", "subtitle": "...", "bullets": ["..."], "visual_description": "...", "notes": "..."}}]\n'
                f"Slides: Problem, Solution, Market Size, Product Demo, Business Model, "
                f"Traction, Team, Competition, Investment Ask, Vision.\n"
                f"Respond ONLY with the JSON array."
            ),
        )

        slides = self._parse_slides_json(content.content) or self._default_pitch_deck(
            company, problem, solution
        )
        html = self._render_html(f"{company} — Pitch Deck", slides, "corporate", True)

        return {
            "success": True,
            "title": f"{company} Pitch Deck",
            "slide_count": len(slides),
            "html_bytes": html.encode("utf-8"),
            "filename": f"{company.lower().replace(' ', '_')}_pitch_deck.html",
        }

    async def export_to_images(
        self, html_content: str, output_prefix: str = "slide"
    ) -> dict[str, Any]:
        """
        Exports each slide as a PNG image using Playwright.
        Returns a list of image bytes.
        """
        try:
            import os
            import tempfile

            from playwright.async_api import async_playwright

            with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
                f.write(html_content)
                tmp_path = f.name

            images = []
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": 1280, "height": 720})
                await page.goto(f"file://{tmp_path}", wait_until="networkidle")
                await asyncio.sleep(1)

                # Count slides
                slide_count = await page.evaluate("() => Reveal.getTotalSlides()")
                for i in range(slide_count):
                    await page.evaluate(f"() => Reveal.slide({i})")
                    await asyncio.sleep(0.3)
                    img_bytes = await page.screenshot(type="png", full_page=False)
                    images.append(img_bytes)

                await browser.close()
            os.unlink(tmp_path)

            return {"success": True, "images": images, "count": len(images)}
        except Exception as exc:
            logger.warning("[PresentationBuilder] export_to_images failed: %s", exc)
            return {"success": False, "error": str(exc), "images": []}

    # ══════════════════════════════════════════════════════════════
    # PRIVATE — GENERATION
    # ══════════════════════════════════════════════════════════════

    async def _generate_outline(self, title: str, topic: str, count: int) -> list[str]:
        from apps.core.tools.ai_client import AIModel, get_ai_client

        client = get_ai_client()
        resp = await client.complete(
            model=AIModel.FAST,
            system="You are an expert in communication and executive presentations.",
            user=(
                f"Title: {title}\nTopic: {topic}\n"
                f"Generate exactly {count} slide titles for this presentation.\n"
                f"Respond ONLY with a numbered list: 1. Title\\n2. Title\\n..."
            ),
        )
        lines = [l.strip() for l in resp.content.split("\n") if l.strip()]
        titles = [re.sub(r"^\d+[\.\)]\s*", "", l) for l in lines if re.match(r"^\d", l)]
        return titles[:count] if titles else [f"Slide {i+1}" for i in range(count)]

    async def _generate_slides(self, title: str, topic: str, outline: list[str]) -> list[dict]:
        from apps.core.tools.ai_client import AIModel, get_ai_client

        client = get_ai_client()

        async def gen_slide(slide_title: str, idx: int) -> dict:
            resp = await client.complete(
                model=AIModel.FAST,
                system="You are an expert in executive presentations. Respond ONLY with JSON.",
                user=(
                    f"Presentation: '{title}' about '{topic}'\n"
                    f"Slide {idx+1}: '{slide_title}'\n\n"
                    f"Generate the content in JSON:\n"
                    f'{{"title": "...", "subtitle": "...", "bullets": ["...", "...", "..."], '
                    f'"highlight": "key data point or statistic", "visual_hint": "suggested visual type"}}\n'
                    f"Maximum 5 concise bullets. Respond ONLY with JSON."
                ),
            )
            slide = self._parse_single_slide(resp.content)
            slide.setdefault("title", slide_title)
            return slide

        tasks = [gen_slide(t, i) for i, t in enumerate(outline)]
        slides = await asyncio.gather(*tasks, return_exceptions=True)
        return [s if isinstance(s, dict) else {"title": outline[i]} for i, s in enumerate(slides)]

    async def _enrich_slides(self, title: str, outline: list[dict]) -> list[dict]:
        return outline  # Already structured, return as-is

    # ══════════════════════════════════════════════════════════════
    # PRIVATE — PARSING
    # ══════════════════════════════════════════════════════════════

    def _parse_slides_json(self, text: str) -> list[dict] | None:
        try:
            text = re.sub(r"^```[a-z]*\n?", "", text.strip(), flags=re.M)
            text = re.sub(r"\n?```$", "", text.strip())
            m = re.search(r"\[.*\]", text, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception:
            pass
        return None

    def _parse_single_slide(self, text: str) -> dict:
        try:
            text = re.sub(r"^```[a-z]*\n?", "", text.strip(), flags=re.M)
            text = re.sub(r"\n?```$", "", text.strip())
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception:
            pass
        return {}

    def _default_pitch_deck(self, company: str, problem: str, solution: str) -> list[dict]:
        return [
            {"title": company, "subtitle": "Pitch Deck", "bullets": []},
            {"title": "The Problem", "bullets": [problem]},
            {"title": "Our Solution", "bullets": [solution]},
            {"title": "Market Opportunity", "bullets": ["Huge TAM", "Growing market"]},
            {"title": "Product", "bullets": ["Demo here"]},
            {"title": "Business Model", "bullets": ["SaaS / Recurring revenue"]},
            {"title": "Traction", "bullets": ["Early customers", "Growing metrics"]},
            {"title": "Team", "bullets": ["Experienced founders"]},
            {"title": "Competition", "bullets": ["Competitive advantages"]},
            {"title": "The Ask", "bullets": ["Investment amount", "Use of funds"]},
        ]

    # ══════════════════════════════════════════════════════════════
    # PRIVATE — HTML RENDERING
    # ══════════════════════════════════════════════════════════════

    def _render_html(
        self,
        title: str,
        slides: list[dict],
        template: str = "dark",
        speaker_notes: bool = False,
    ) -> str:
        theme_map = {
            "dark": "black",
            "light": "white",
            "corporate": "moon",
            "minimal": "simple",
            "tech": "dracula",
            "warm": "serif",
        }
        reveal_theme = theme_map.get(template, "black")

        slides_html = ""
        for slide in slides:
            slide_title = slide.get("title", "")
            slide_subtitle = slide.get("subtitle", "")
            bullets = slide.get("bullets", [])
            highlight = slide.get("highlight", "")
            notes = slide.get("notes", "")

            bullets_html = "".join(f"<li>{b}</li>" for b in bullets[:6]) if bullets else ""
            list_html = f"<ul>{bullets_html}</ul>" if bullets_html else ""
            sub_html = f"<p class='subtitle'>{slide_subtitle}</p>" if slide_subtitle else ""
            hi_html = f"<div class='highlight-box'>{highlight}</div>" if highlight else ""
            notes_html = f"<aside class='notes'>{notes}</aside>" if notes and speaker_notes else ""

            slides_html += f"""
        <section>
          <h2>{slide_title}</h2>
          {sub_html}
          {list_html}
          {hi_html}
          {notes_html}
        </section>"""

        return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link rel="stylesheet" href="{REVEAL_CDN}/reset.min.css">
  <link rel="stylesheet" href="{REVEAL_CDN}/reveal.min.css">
  <link rel="stylesheet" href="{REVEAL_CDN}/theme/{reveal_theme}.min.css">
  <link rel="stylesheet" href="{REVEAL_CDN}/plugin/highlight/monokai.min.css">
  <style>
    .reveal h2 {{ font-size: 1.6em; margin-bottom: 0.3em; }}
    .reveal .subtitle {{ font-size: 0.9em; opacity: 0.7; margin-bottom: 1em; font-style: italic; }}
    .reveal ul {{ text-align: left; margin: 0 auto; max-width: 80%; }}
    .reveal li {{ margin: 0.4em 0; font-size: 0.85em; line-height: 1.4; }}
    .highlight-box {{
      margin: 1em auto; padding: 0.8em 1.5em;
      background: rgba(100,100,255,0.15); border-left: 4px solid #7c3aed;
      border-radius: 4px; font-size: 1.1em; font-weight: 600; max-width: 80%;
    }}
    .reveal .controls {{ color: #7c3aed; }}
    .reveal .progress {{ background: rgba(124,58,237,0.3); }}
    .reveal .progress span {{ background: #7c3aed; }}
  </style>
</head>
<body>
<div class="reveal">
  <div class="slides">
    {slides_html}
  </div>
</div>
<script src="{REVEAL_CDN}/reveal.min.js"></script>
<script src="{REVEAL_CDN}/plugin/highlight/highlight.min.js"></script>
<script src="{REVEAL_CDN}/plugin/notes/notes.min.js"></script>
<script>
  Reveal.initialize({{
    hash: true,
    transition: 'slide',
    backgroundTransition: 'fade',
    controls: true,
    progress: true,
    center: true,
    plugins: [RevealHighlight, RevealNotes]
  }});
</script>
</body>
</html>"""
