"""
IncomeLoop v2.0 — ARIA's 24/7 Autonomous Income Machine.

Runs every 30 minutes alongside the orchestrator (60 min).
Focuses on PURE EXECUTION — no planning overhead.

Every cycle picks a strategy based on weighted probability (13 strategies):
  18% — Content Pipeline   (SEO articles + affiliate → Medium/dev.to/Hashnode)
  15% — Niche Rotator      (launches next niche in catalog → Gumroad + Zapier)
  13% — Product Factory    (creates new digital products for trending topics)
   9% — Opportunity Scan   (web research for new income streams)
   8% — GitHub Publish     (open-source resources → SEO + authority, always active)
   7% — Shopify Listing    (creates Shopify digital product from trending topic)
   7% — Email Campaign     (Mailchimp campaign to owned audience)
   6% — Affiliate Content  (review/comparison articles with Amazon links)
   6% — Ebook Factory      (AI-generated ebook sold on Gumroad at $7-$27)
   5% — Lead Magnet        (free resource funnel → email capture → upsell)
   4% — Social Blitz       (Zapier distribution for all existing products)
   1% — Premium Offer      (high-ticket B2B consulting offers $500-$5,000)
   1% — Viral Thread       (Twitter/X thread → virality → traffic)

Additional automation:
  - Product Launch Sequence: every created product gets a blog announcement
  - Portfolio Bootstrap: aria-portfolio updated on each startup
  - Morning Briefing: daily Telegram summary of stats and published URLs
  - Topic Deduplication: Redis cache prevents repeated blog content

Scale at 30-min intervals:
  48 cycles/day → up to 144 articles + 14 products + 7 ebooks
  Revenue compounds: more products + more content = more discovery

The loop NEVER stops. Every exception is caught, logged, and the
loop resumes after a short backoff. Redis tracks all results.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from apps.core.config import settings

logger = logging.getLogger("aria.income_loop")

INTERVAL_SECONDS  = 1800   # 30 minutes between cycles
FIRST_RUN_DELAY   = 45     # seconds after startup before first run
ERROR_BACKOFF     = 300    # 5 min backoff after errors
MAX_STRATEGY_TIME = 240    # 4 min max per strategy (avoids blocking)

# Strategy probability weights (sum = 100)
STRATEGIES = [
    ("content_pipeline",  16),
    ("niche_rotator",     15),
    ("product_factory",   13),
    ("opportunity_scan",   9),
    ("github_publish",     8),   # works with only GITHUB_TOKEN — always active
    ("shopify_listing",    7),
    ("email_campaign",     7),
    ("affiliate_content",  6),   # review/comparison articles with affiliate links
    ("ebook_factory",      6),
    ("lead_magnet",        5),   # free resource funnel → email capture → upsell
    ("hf_spaces_demo",     4),   # live AI demo on HuggingFace Spaces (free, massive community)
    ("social_blitz",       2),
    ("premium_offer",      1),
    ("viral_thread",       1),   # Twitter/X thread optimized for virality
]


@dataclass
class CycleResult:
    cycle_id: int
    strategy: str
    success: bool
    summary: str
    revenue_potential: float = 0.0
    urls_created: list[str] = field(default_factory=list)
    elapsed_seconds: int = 0
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class IncomeLoop:
    """
    Autonomous income machine. Never sleeps for more than 30 minutes.
    Each cycle executes one income strategy, tracks results in Redis,
    and notifies via Telegram only on significant events.
    """

    def __init__(self) -> None:
        self._running    = False
        self._task       = None
        self._cycle      = 0
        self._niche_idx  = 0    # Round-robin through niche catalog (loaded from Redis in first cycle)

    # ── Control ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch the income loop as a background coroutine."""
        if self._running:
            logger.info("[IncomeLoop] Already running")
            return
        self._running = True
        self._task    = asyncio.create_task(self._run_forever())
        logger.info("[IncomeLoop] 24/7 income loop started (interval=%ds)", INTERVAL_SECONDS)
        # Proactive Telegram notification on startup
        asyncio.create_task(self._notify_startup())

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("[IncomeLoop] Stopped")

    @property
    def is_running(self) -> bool:
        return self._running and (self._task is not None) and (not self._task.done())

    # ── Main loop ─────────────────────────────────────────────────────

    async def _run_forever(self) -> None:
        """Infinite loop. Never crashes. Always resumes."""
        logger.info("[IncomeLoop] First run in %ds", FIRST_RUN_DELAY)
        await asyncio.sleep(FIRST_RUN_DELAY)

        while self._running:
            try:
                await self._run_one_cycle()
            except asyncio.CancelledError:
                logger.info("[IncomeLoop] Cancelled gracefully")
                break
            except Exception as exc:
                logger.error("[IncomeLoop] Unhandled error: %s", exc, exc_info=True)
                await self._save_error(str(exc))
                await asyncio.sleep(ERROR_BACKOFF)
                continue

            await asyncio.sleep(INTERVAL_SECONDS)

    async def _run_one_cycle(self, force_strategy: str | None = None) -> "CycleResult":
        self._cycle += 1
        strategy = force_strategy if force_strategy else self._pick_strategy()
        start    = time.time()
        logger.info("[IncomeLoop] Cycle #%d — strategy: %s", self._cycle, strategy)

        result = CycleResult(
            cycle_id=self._cycle,
            strategy=strategy,
            success=False,
            summary="",
        )

        try:
            obs = await asyncio.wait_for(
                self._execute(strategy), timeout=MAX_STRATEGY_TIME
            )
            result.success          = obs.get("success", False)
            result.summary          = obs.get("summary", "")
            result.revenue_potential = obs.get("revenue_potential", 0.0)
            result.urls_created     = obs.get("urls", [])
        except asyncio.TimeoutError:
            result.summary = f"Strategy '{strategy}' timed out after {MAX_STRATEGY_TIME}s"
            logger.warning("[IncomeLoop] %s", result.summary)
        except Exception as exc:
            result.summary = f"Strategy '{strategy}' error: {str(exc)[:150]}"
            logger.error("[IncomeLoop] %s", result.summary)
        finally:
            result.elapsed_seconds = int(time.time() - start)

        await self._save_result(result)

        # Notify on wins
        if result.success and result.urls_created:
            await self._notify_win(result)

        # Product launch sequence: announce newly created products on the blog
        if result.success and result.urls_created and result.strategy in ("product_factory", "ebook_factory", "premium_offer"):
            asyncio.create_task(self._announce_product_on_blog(result))

        # Persist to product catalog for all income-generating strategies
        if result.success and result.urls_created and result.revenue_potential > 0:
            asyncio.create_task(self._register_product(result))

        logger.info(
            "[IncomeLoop] Cycle #%d done in %ds | success=%s | %s",
            self._cycle, result.elapsed_seconds, result.success, result.summary[:80]
        )
        return result

    def _pick_strategy(self) -> str:
        """Weighted random strategy selection."""
        names   = [s[0] for s in STRATEGIES]
        weights = [s[1] for s in STRATEGIES]
        return random.choices(names, weights=weights, k=1)[0]

    async def _announce_product_on_blog(self, result: CycleResult) -> None:
        """Write a blog post announcing a newly created product — drives organic traffic to it."""
        if not settings.GITHUB_TOKEN:
            return
        try:
            await asyncio.sleep(10)  # let the main cycle finish logging first
            from apps.core.tools.ai_client import get_ai_client, AIModel
            ai = get_ai_client()
            if not ai:
                return

            product_url = result.urls_created[0] if result.urls_created else ""
            announcement = await ai.complete_json(
                system="You write compelling product launch posts. Be enthusiastic but specific. Output JSON only.",
                user=f"""Write a product launch announcement blog post.

Product: {result.summary[:200]}
URL: {product_url}
Strategy: {result.strategy}

JSON:
{{
  "title": "Exciting launch post title (60 chars max)",
  "slug": "url-slug-for-post",
  "description": "Meta description (155 chars)",
  "tags": ["launch", "product", "ai"],
  "content": "Product launch blog post (400+ words). Cover: what the product solves, who it's for, key benefits, CTA with link. Use markdown."
}}""",
                model=AIModel.FAST,
                max_tokens=2000,
            )
            if announcement and product_url:
                if "content" in announcement:
                    announcement["content"] += f"\n\n**[Get it here →]({product_url})**\n"
                await self._exec_github_blog([announcement], cp=None)
                logger.info("[IncomeLoop] Product announcement published for: %s", result.summary[:60])
        except Exception as exc:
            logger.debug("[IncomeLoop] product announcement: %s", exc)

    # ── Strategy Executors ───────────────────────────────────────────────────

    async def _execute(self, strategy: str) -> dict:
        if strategy == "content_pipeline":
            return await self._exec_content_pipeline()
        elif strategy == "niche_rotator":
            return await self._exec_niche_rotator()
        elif strategy == "product_factory":
            return await self._exec_product_factory()
        elif strategy == "opportunity_scan":
            return await self._exec_opportunity_scan()
        elif strategy == "github_publish":
            return await self._exec_github_publish()
        elif strategy == "shopify_listing":
            return await self._exec_shopify_listing()
        elif strategy == "email_campaign":
            return await self._exec_email_campaign()
        elif strategy == "ebook_factory":
            return await self._exec_ebook_factory()
        elif strategy == "social_blitz":
            return await self._exec_social_blitz()
        elif strategy == "premium_offer":
            return await self._exec_premium_offer()
        elif strategy == "affiliate_content":
            return await self._exec_affiliate_content()
        elif strategy == "lead_magnet":
            return await self._exec_lead_magnet()
        elif strategy == "hf_spaces_demo":
            return await self._exec_hf_spaces_demo()
        elif strategy == "viral_thread":
            return await self._exec_viral_thread()
        return {"success": False, "summary": "Unknown strategy"}

    async def _exec_content_pipeline(self) -> dict:
        """Run the full content pipeline: trending → articles → publish → affiliate.
        Falls back to GitHub blog when publishing credentials are missing."""
        try:
            from apps.core.tools.content_pipeline import ContentPipeline
            cp     = ContentPipeline()
            result = await cp.run_pipeline(num_articles=3, language="es")
            arts   = result.get("articles", [])
            urls   = [u["url"] for a in arts for u in a.get("urls", []) if u.get("url")]

            if result.get("success", False) and urls:
                return {
                    "success": True,
                    "summary": f"Published {len(arts)} articles to {result.get('articles_published',0)} platforms",
                    "revenue_potential": len(arts) * 2.5,
                    "urls": urls[:6],
                }

            # Fallback: push generated content to GitHub blog
            if settings.GITHUB_TOKEN:
                blog_result = await self._exec_github_blog(arts, cp)
                if blog_result.get("success"):
                    return blog_result

            return {
                "success": False,
                "summary": f"Content pipeline: no publishing credentials (add DEVTO_API_KEY or MEDIUM_TOKEN)",
                "revenue_potential": 0,
                "urls": [],
            }
        except Exception as exc:
            logger.error("[IncomeLoop] content_pipeline: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_github_blog(self, existing_articles: list, cp=None) -> dict:
        """
        Maintain aria-insights GitHub repo as a public blog.
        Generates SEO-optimized articles and pushes them as markdown files.
        Includes Amazon affiliate links when AMAZON_ASSOCIATE_TAG is configured.
        GitHub indexes public repos — free organic traffic.
        """
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.github_client import AriaGitHubClient
            from apps.core.tools.web_tools import WebTools
            import base64 as _b64
            from datetime import datetime, timezone

            ai    = get_ai_client()
            gh    = AriaGitHubClient()
            owner = settings.GITHUB_USERNAME or "Geremypolanco"
            repo  = "aria-insights"
            assoc = getattr(settings, "AMAZON_ASSOCIATE_TAG", None) or ""

            # Ensure the blog repo exists
            existing = await gh._get(f"/repos/{owner}/{repo}")
            if "error" in existing:
                create_r = await gh._post("/user/repos", {
                    "name": repo,
                    "description": "AI-generated insights on technology, business & productivity",
                    "private": False,
                    "auto_init": True,
                    "has_issues": False,
                    "has_wiki": False,
                })
                if "error" in create_r:
                    return {"success": False, "summary": f"Could not create {repo}: {create_r.get('error','')[:60]}"}
                await asyncio.sleep(2)  # wait for GitHub to init
                # Enable GitHub Pages (one-time setup — makes the blog a real website)
                try:
                    await gh._post(f"/repos/{owner}/{repo}/pages", {
                        "source": {"branch": "main", "path": "/"},
                    })
                    # Add FUNDING.yml for Sponsor button
                    import base64 as _b64blog
                    funding_yml = (
                        f"github: [{owner}]\n"
                        f"custom: [\"https://github.com/{owner}/aria-portfolio\"]\n"
                    )
                    await gh._put(f"/repos/{owner}/{repo}/contents/.github/FUNDING.yml", {
                        "message": "chore: add FUNDING.yml",
                        "content": _b64blog.b64encode(funding_yml.encode()).decode(),
                    })
                    # Add minimal Jekyll config
                    jekyll_config = (
                        "title: ARIA Insights\n"
                        "description: AI-generated insights on technology, business & productivity\n"
                        "theme: minima\n"
                        "plugins:\n"
                        "  - jekyll-feed\n"
                        "  - jekyll-seo-tag\n"
                    )
                    await gh._put(f"/repos/{owner}/{repo}/contents/_config.yml", {
                        "message": "chore: enable Jekyll for GitHub Pages",
                        "content": _b64.b64encode(jekyll_config.encode()).decode(),
                    })
                except Exception:
                    pass  # Pages may already be enabled or not available on free plan

            # Load published topics for deduplication
            published_topics: set = set()
            try:
                from apps.core.memory.redis_client import get_cache as _get_cache
                _cache = _get_cache()
                if _cache:
                    raw_topics = await _cache.get("aria:blog:published_topics")
                    if raw_topics:
                        published_topics = set(json.loads(raw_topics) if isinstance(raw_topics, str) else raw_topics)
            except Exception:
                pass

            # Get a trending topic if no articles provided
            if not existing_articles:
                if not ai:
                    return {"success": False, "summary": "AI unavailable"}
                wt = WebTools()
                r  = await wt.search_web("trending tech AI productivity 2025 tutorial", num_results=8)
                topic = "AI Productivity Guide 2025"
                # Pick first result not already published
                if r.get("success") and r.get("results"):
                    for res in r["results"]:
                        candidate = res.get("title", "")[:80]
                        # Simple dedup: skip if a very similar title was already published
                        candidate_words = set(candidate.lower().split())
                        already_published = any(
                            len(candidate_words & set(pt.lower().split())) >= 3
                            for pt in published_topics
                        )
                        if not already_published:
                            topic = candidate
                            break
                    else:
                        topic = r["results"][0].get("title", topic)[:80]

                article_json = await ai.complete_json(
                    system=(
                        "You write viral, SEO-optimized technical articles. "
                        "Use markdown. Be specific and actionable. Output JSON only."
                    ),
                    user=f"""Write a complete blog post about: "{topic}"

JSON:
{{
  "title": "SEO title (60 chars max)",
  "slug": "url-friendly-slug-max-50-chars",
  "description": "Meta description (155 chars)",
  "tags": ["tag1", "tag2", "tag3"],
  "content": "Full markdown article (800+ words). Use H2/H3 headers, bullet points, code blocks if relevant, practical tips."
}}""",
                    model=AIModel.STRATEGY,
                    max_tokens=3000,
                )
                if not article_json:
                    return {"success": False, "summary": "AI failed to generate article"}
                existing_articles = [article_json]

            published_urls = []
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            for art in existing_articles[:2]:
                title   = art.get("title", art.get("product_name", "ARIA Insights"))[:60]
                slug    = (art.get("slug", title.lower().replace(" ", "-").replace("'", ""))
                           .replace(" ", "-")[:50])
                content = art.get("content", art.get("description", ""))
                tags    = art.get("tags", ["ai", "productivity"])

                # Inject Amazon affiliate links if configured
                if assoc and content:
                    aff_note = (
                        f"\n\n---\n*Some links in this article may be affiliate links. "
                        f"If you purchase through them, we earn a small commission at no extra cost to you.*\n"
                        f"[Browse recommended tools on Amazon](https://amazon.com?tag={assoc})\n"
                    )
                    content += aff_note

                # Build markdown file
                frontmatter = (
                    f"---\n"
                    f"title: \"{title}\"\n"
                    f"date: {today}\n"
                    f"description: \"{art.get('description', '')[:155]}\"\n"
                    f"tags: {tags}\n"
                    f"author: ARIA AI\n"
                    f"---\n\n"
                )
                full_content = frontmatter + f"# {title}\n\n" + content

                filename = f"posts/{today}-{slug}.md"
                encoded  = _b64.b64encode(full_content.encode()).decode()

                file_r = await gh._put(f"/repos/{owner}/{repo}/contents/{filename}", {
                    "message": f"post: {title[:60]}",
                    "content": encoded,
                })

                if "error" not in file_r:
                    published_urls.append(f"https://github.com/{owner}/{repo}/blob/main/{filename}")

            if published_urls:
                # Update the blog index, sitemap, and published topics cache
                try:
                    published_titles = [art.get("title", "Article") for art in existing_articles[:len(published_urls)]]
                    await self._update_blog_index(gh, owner, repo, published_titles, published_urls)
                    await self._update_sitemap(gh, owner, repo)
                    await self._update_rss_feed(gh, owner, repo)
                    # Track published topics to avoid duplication
                    try:
                        from apps.core.memory.redis_client import get_cache as _gc2
                        _c2 = _gc2()
                        if _c2:
                            updated_topics = list(published_topics | set(published_titles))[-100:]
                            await _c2.set("aria:blog:published_topics", json.dumps(updated_topics), ttl_seconds=86400 * 90)
                    except Exception:
                        pass
                except Exception:
                    pass

                # Also cross-post to Dev.to if API key is configured (bonus distribution)
                devto_key = getattr(settings, "DEVTO_API_KEY", None)
                devto_urls = []
                if devto_key:
                    try:
                        import httpx as _httpx_dt
                        async with _httpx_dt.AsyncClient(timeout=20) as _dt:
                            for art in existing_articles[:2]:
                                art_title   = art.get("title", "")[:60]
                                art_content = art.get("content", art.get("description", ""))
                                art_tags    = [t.replace(" ", "").lower() for t in art.get("tags", ["ai", "productivity"])[:4]]
                                dt_body = {
                                    "article": {
                                        "title": art_title,
                                        "body_markdown": f"# {art_title}\n\n{art_content}",
                                        "published": True,
                                        "tags": art_tags[:4],
                                        "canonical_url": published_urls[0] if published_urls else None,
                                    }
                                }
                                dt_r = await _dt.post(
                                    "https://dev.to/api/articles",
                                    json=dt_body,
                                    headers={"api-key": devto_key, "Content-Type": "application/json"},
                                    timeout=15,
                                )
                                if dt_r.status_code in (200, 201):
                                    dt_url = dt_r.json().get("url", "")
                                    if dt_url:
                                        devto_urls.append(dt_url)
                    except Exception:
                        pass

                # Cross-post to Hashnode if configured
                hn_token = getattr(settings, "HASHNODE_TOKEN", None)
                hn_pub   = getattr(settings, "HASHNODE_PUBLICATION_ID", None)
                hashnode_urls: list[str] = []
                if hn_token and hn_pub:
                    try:
                        import httpx as _httpx_hn
                        async with _httpx_hn.AsyncClient(timeout=20) as _hn:
                            for art in existing_articles[:1]:
                                art_title   = art.get("title", "")[:150]
                                art_content = art.get("content", art.get("description", ""))
                                art_tags    = [{"slug": t.replace(" ", "-").lower()} for t in art.get("tags", ["ai", "productivity"])[:5]]
                                hn_mutation = """
                                mutation PublishPost($input: PublishPostInput!) {
                                  publishPost(input: $input) {
                                    post { url }
                                  }
                                }"""
                                hn_vars = {
                                    "input": {
                                        "title": art_title,
                                        "contentMarkdown": f"# {art_title}\n\n{art_content}",
                                        "publicationId": hn_pub,
                                        "tags": art_tags,
                                        "disableComments": False,
                                        "originalArticleURL": published_urls[0] if published_urls else None,
                                    }
                                }
                                hn_r = await _hn.post(
                                    "https://gql.hashnode.com",
                                    json={"query": hn_mutation, "variables": hn_vars},
                                    headers={"Authorization": hn_token, "Content-Type": "application/json"},
                                    timeout=20,
                                )
                                if hn_r.status_code == 200:
                                    hn_url = (
                                        hn_r.json()
                                        .get("data", {})
                                        .get("publishPost", {})
                                        .get("post", {})
                                        .get("url", "")
                                    )
                                    if hn_url:
                                        hashnode_urls.append(hn_url)
                    except Exception:
                        pass

                # Discord notification for new content
                discord_url = getattr(settings, "DISCORD_WEBHOOK_URL", None)
                if discord_url:
                    try:
                        import httpx as _httpx
                        async with _httpx.AsyncClient(timeout=10) as _client:
                            extra = ""
                            if devto_urls:
                                extra += f"Dev.to: {devto_urls[0]}\n"
                            if hashnode_urls:
                                extra += f"Hashnode: {hashnode_urls[0]}\n"
                            await _client.post(discord_url, json={
                                "content": (
                                    f"📝 **New article published!**\n"
                                    f"{published_urls[0]}\n"
                                    + extra
                                    + f"*ARIA Insights — AI-generated content*"
                                )
                            })
                    except Exception:
                        pass

                all_urls = published_urls + devto_urls + hashnode_urls
                platform_parts = ["GitHub"]
                if devto_urls:
                    platform_parts.append("Dev.to")
                if hashnode_urls:
                    platform_parts.append("Hashnode")
                platforms = " + ".join(platform_parts)
                return {
                    "success": True,
                    "summary": f"Published {len(published_urls)} article(s) to {platforms}" +
                               (f" with Amazon affiliate links" if assoc else " (add AMAZON_ASSOCIATE_TAG for affiliate income)"),
                    "revenue_potential": len(all_urls) * 1.5,
                    "urls": all_urls,
                }
            return {"success": False, "summary": "GitHub blog: no articles pushed"}
        except Exception as exc:
            logger.error("[IncomeLoop] github_blog: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _update_blog_index(self, gh, owner: str, repo: str, new_titles: list[str], new_urls: list[str]) -> None:
        """Update LINKS.md in aria-insights with recent article links."""
        try:
            import base64 as _b64
            # Load existing links from Redis
            try:
                from apps.core.memory.redis_client import get_cache
                cache = get_cache()
                raw = await cache.get("aria:blog:links") if cache else None
                existing_links: list = json.loads(raw) if raw else []
            except Exception:
                existing_links = []

            # Prepend new links
            for title, url in zip(new_titles, new_urls):
                existing_links.insert(0, {"title": title, "url": url})
            existing_links = existing_links[:50]  # keep latest 50

            # Save back to Redis
            try:
                if cache:
                    await cache.set("aria:blog:links", json.dumps(existing_links), ttl_seconds=86400 * 90)
            except Exception:
                pass

            # Build LINKS.md content
            lines = [
                "# ARIA Insights — Article Index",
                "",
                "AI-generated insights on technology, business & productivity.",
                "",
                "## Latest Articles",
                "",
            ]
            for item in existing_links[:30]:
                lines.append(f"- [{item['title']}]({item['url']})")
            lines += ["", "---", "*Updated by ARIA AI — autonomously generated content*"]
            md_content = "\n".join(lines)
            encoded = _b64.b64encode(md_content.encode()).decode()

            # Push LINKS.md
            existing_file = await gh._get(f"/repos/{owner}/{repo}/contents/LINKS.md")
            sha = existing_file.get("sha", "") if "error" not in existing_file else ""
            put_args: dict = {"message": "docs: update article index", "content": encoded}
            if sha:
                put_args["sha"] = sha
            await gh._put(f"/repos/{owner}/{repo}/contents/LINKS.md", put_args)
        except Exception as exc:
            logger.debug("[IncomeLoop] blog_index_update: %s", exc)

    async def _update_rss_feed(self, gh, owner: str, repo: str) -> None:
        """Generate RSS feed for the blog — discoverable by RSS readers and news aggregators."""
        try:
            import base64 as _b64
            from datetime import datetime, timezone
            base_url    = f"https://{owner.lower()}.github.io/{repo}"
            repo_url    = f"https://github.com/{owner}/{repo}"
            today       = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
            # Load recent articles from Redis
            try:
                from apps.core.memory.redis_client import get_cache
                cache = get_cache()
                raw   = await cache.get("aria:blog:links") if cache else None
                links = json.loads(raw) if raw else []
            except Exception:
                links = []
            items = []
            for link in links[:20]:
                title = link.get("title", "Article")
                url   = link.get("url", "").replace("github.com", f"{owner.lower()}.github.io").replace(f"/{owner}/{repo}/blob/main/", f"/{repo}/")
                items.append(
                    f"  <item>\n"
                    f"    <title>{title}</title>\n"
                    f"    <link>{url}</link>\n"
                    f"    <guid>{url}</guid>\n"
                    f"    <pubDate>{today}</pubDate>\n"
                    f"    <description>AI-generated article: {title}</description>\n"
                    f"  </item>"
                )
            rss = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
                "  <channel>\n"
                f"    <title>ARIA Insights</title>\n"
                f"    <link>{base_url}</link>\n"
                f"    <description>AI-generated insights on technology, business and productivity</description>\n"
                f"    <atom:link href=\"{base_url}/feed.xml\" rel=\"self\" type=\"application/rss+xml\"/>\n"
                f"    <lastBuildDate>{today}</lastBuildDate>\n"
                + "\n".join(items) + "\n"
                "  </channel>\n"
                "</rss>\n"
            )
            encoded = _b64.b64encode(rss.encode()).decode()
            existing = await gh._get(f"/repos/{owner}/{repo}/contents/feed.xml")
            sha      = existing.get("sha", "") if "error" not in existing else ""
            put_args: dict = {"message": "chore: update RSS feed", "content": encoded}
            if sha:
                put_args["sha"] = sha
            await gh._put(f"/repos/{owner}/{repo}/contents/feed.xml", put_args)
        except Exception as exc:
            logger.debug("[IncomeLoop] rss_feed_update: %s", exc)

    async def _update_sitemap(self, gh, owner: str, repo: str) -> None:
        """Generate sitemap.xml for the blog — helps search engines discover content."""
        try:
            import base64 as _b64
            from datetime import datetime, timezone
            # List all posts in the posts/ directory
            files_r = await gh._get(f"/repos/{owner}/{repo}/contents/posts")
            if "error" in files_r or not isinstance(files_r, list):
                return
            base_url = f"https://{owner.lower()}.github.io/{repo}"
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            urls = [f"  <url><loc>{base_url}/</loc><lastmod>{today}</lastmod><priority>1.0</priority></url>"]
            for f in files_r:
                if f.get("name", "").endswith(".md"):
                    slug = f["name"].replace(".md", "")
                    urls.append(f"  <url><loc>{base_url}/posts/{slug}/</loc><lastmod>{today}</lastmod><priority>0.8</priority></url>")
            sitemap = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                + "\n".join(urls) +
                "\n</urlset>\n"
            )
            encoded = _b64.b64encode(sitemap.encode()).decode()
            existing_file = await gh._get(f"/repos/{owner}/{repo}/contents/sitemap.xml")
            sha = existing_file.get("sha", "") if "error" not in existing_file else ""
            put_args: dict = {"message": "chore: update sitemap", "content": encoded}
            if sha:
                put_args["sha"] = sha
            await gh._put(f"/repos/{owner}/{repo}/contents/sitemap.xml", put_args)
        except Exception as exc:
            logger.debug("[IncomeLoop] sitemap_update: %s", exc)

    async def _exec_niche_rotator(self) -> dict:
        """Rotate through niche catalog — launch next unstarted niche."""
        try:
            from apps.core.tools.niche_revenue_engine import (
                get_niche_revenue_engine, NICHE_CATALOG
            )
            engine  = get_niche_revenue_engine()
            launched = {ls.niche_key for ls in await engine._load_listings()}
            all_keys = list(NICHE_CATALOG.keys())

            # Find next unlaunched niche (round-robin)
            candidates = [k for k in all_keys if k not in launched]
            if not candidates:
                # All launched — pick the oldest for a refresh
                candidates = all_keys
            # Load from Redis on first use to survive restarts
            if self._niche_idx == 0:
                self._niche_idx = await self._load_niche_idx()
            target = candidates[self._niche_idx % len(candidates)]
            self._niche_idx += 1
            await self._save_niche_idx()

            result = await engine.launch_niche(target)
            urls   = [u["url"] for u in result.published_urls + result.seo_article_urls if u.get("url")]

            if result.success and urls:
                return {
                    "success":          True,
                    "summary":          f"Niche '{target}': checklist={result.checklist.score if result.checklist else 0}/100 | {len(result.published_urls)} listings | {len(result.seo_article_urls)} articles",
                    "revenue_potential": result.revenue_potential_usd,
                    "urls":             urls,
                }

            # Fallback: publish the niche as a GitHub landing page (free SEO)
            if settings.GITHUB_TOKEN:
                try:
                    from apps.core.tools.ai_client import get_ai_client, AIModel
                    from apps.core.tools.github_client import AriaGitHubClient
                    import base64 as _b64
                    niche_info = NICHE_CATALOG.get(target, {})
                    ai = get_ai_client()
                    if ai:
                        niche_page = await ai.complete_json(
                            system="You create SEO-optimized landing pages for service businesses. Output JSON only.",
                            user=f"""Create a landing page for a niche service business: "{target}"
Niche info: {str(niche_info)[:400]}

JSON:
{{
  "headline": "Service headline (10 words max)",
  "description": "Service description (200+ words). Highlight benefits, ROI, outcomes.",
  "services": ["Service 1", "Service 2", "Service 3"],
  "price_range": "$X - $Y per project"
}}""",
                            model=AIModel.FAST,
                            max_tokens=1000,
                        )
                        if niche_page:
                            gh    = AriaGitHubClient()
                            owner = settings.GITHUB_USERNAME or "Geremypolanco"
                            repo  = f"aria-niche-{target.replace('_', '-')[:30]}"
                            readme = (
                                f"# {niche_page.get('headline', target.replace('_', ' ').title())}\n\n"
                                f"> {niche_page.get('description', '')}\n\n"
                                f"## Services Offered\n\n"
                                + "\n".join(f"- {s}" for s in niche_page.get("services", []))
                                + f"\n\n## Pricing\n\n{niche_page.get('price_range', '')}\n\n"
                                f"## Get Started\n\nOpen an issue or visit our [portfolio](https://github.com/{owner}/aria-portfolio).\n\n"
                                f"---\n*Service by ARIA AI — Autonomous Business Platform*"
                            )
                            existing = await gh._get(f"/repos/{owner}/{repo}")
                            if "error" in existing:
                                await gh._post("/user/repos", {
                                    "name": repo, "description": niche_page.get("headline", "")[:100],
                                    "private": False, "auto_init": False,
                                })
                            file_r = await gh._put(f"/repos/{owner}/{repo}/contents/README.md", {
                                "message": f"feat: {target} service landing page",
                                "content": _b64.b64encode(readme.encode()).decode(),
                            })
                            if "error" not in file_r:
                                repo_url = f"https://github.com/{owner}/{repo}"
                                return {
                                    "success": True,
                                    "summary": f"Niche '{target}' landing page published to GitHub (add Gumroad/Dev.to for full monetization)",
                                    "revenue_potential": 2.0,
                                    "urls": [repo_url],
                                }
                except Exception:
                    pass

            return {
                "success": result.success,
                "summary": f"Niche '{target}': {result.summary if hasattr(result, 'summary') else 'no publishing credentials'} — add GUMROAD_TOKEN or DEVTO_API_KEY",
                "revenue_potential": result.revenue_potential_usd if result.success else 0,
                "urls": urls,
            }
        except Exception as exc:
            logger.error("[IncomeLoop] niche_rotator: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_product_factory(self) -> dict:
        """Create a new digital product — uses opportunity queue first, then trending topics."""
        try:
            from apps.core.tools.content_pipeline import ContentPipeline
            from apps.core.tools.gumroad_tools import GumroadTools
            from apps.core.tools.ai_client import get_ai_client, AIModel

            # Try the opportunity queue first (populated by opportunity_scan)
            topic = None
            try:
                from apps.core.memory.redis_client import get_cache
                cache = get_cache()
                if cache:
                    raw = await cache.lpop("aria:income:opportunity_queue")
                    if raw:
                        opp = json.loads(raw) if isinstance(raw, str) else raw
                        topic = {
                            "title": opp.get("name", ""),
                            "category": opp.get("niche_key", "tech"),
                            "_from_queue": True,
                            "_platform": opp.get("platform", ""),
                            "_tagline": opp.get("description", ""),
                        }
            except Exception:
                pass

            if not topic:
                cp     = ContentPipeline()
                topics = await cp.get_trending_topics(limit=5)
                if not topics:
                    return {"success": False, "summary": "No trending topics found"}
                topic = topics[0]

            title = topic.get("title", "Digital Guide")[:60]
            cat   = topic.get("category", "tech")

            ai    = get_ai_client()
            if not ai:
                return {"success": False, "summary": "AI client unavailable"}

            product_data = await ai.complete_json(
                system=(
                    "You are a bestselling digital product creator. "
                    "Write complete, actionable content. No fluff. Output JSON only."
                ),
                user=f"""Create a complete digital product for the trending topic: \"{title}\"
Category: {cat}

Output JSON:
{{
  \"product_name\": \"Compelling title with keyword\",
  \"tagline\": \"One-line value proposition\",
  \"description\": \"300+ word sales description with pain points, solution, benefits, social proof, CTA\",
  \"table_of_contents\": [\"Chapter 1: ...\", \"Chapter 2: ...\", \"Chapter 3: ...\", \"Chapter 4: ...\", \"Chapter 5: ...\"],
  \"price_cents\": 1997,
  \"tags\": [\"tag1\", \"tag2\", \"tag3\"]
}}""",
                model=AIModel.CREATIVE,
                max_tokens=2000,
            )

            if not product_data:
                return {"success": False, "summary": "AI generation failed"}

            gt     = GumroadTools()
            gr_res = await gt.create_product(
                name=product_data.get("product_name", title),
                description=product_data.get("description", ""),
                price_cents=product_data.get("price_cents", 997),
                tags=product_data.get("tags", [cat, "digital", "guide"]),
            )

            if gr_res.get("success"):
                url = gr_res.get("url", "")
                try:
                    from apps.core.tools.zapier_connector import ZapierConnector
                    await ZapierConnector().dispatch_event(
                        "NEW_PRODUCT",
                        {
                            "product_name": product_data.get("product_name"),
                            "tagline": product_data.get("tagline"),
                            "price": gr_res.get("price_usd"),
                            "url": url,
                            "category": cat,
                        },
                    )
                except Exception:
                    pass

                return {
                    "success": True,
                    "summary": f"New product '{product_data.get('product_name',title)[:50]}' at ${product_data.get('price_cents',997)/100:.0f}",
                    "revenue_potential": product_data.get("price_cents", 997) / 100,
                    "urls": [url] if url else [],
                }

            # LemonSqueezy fallback (alternative payment processor, lower fees)
            try:
                from apps.core.tools.lemon_squeezy_tools import LemonSqueezyTools
                ls = LemonSqueezyTools()
                if ls._configured():
                    ls_res = await ls.create_product(
                        name=product_data.get("product_name", title),
                        description=product_data.get("description", ""),
                        price_cents=product_data.get("price_cents", 997),
                    )
                    if ls_res.get("success"):
                        return {
                            "success": True,
                            "summary": f"Product '{product_data.get('product_name',title)[:50]}' at ${product_data.get('price_cents',997)/100:.0f} on LemonSqueezy",
                            "revenue_potential": product_data.get("price_cents", 997) / 100,
                            "urls": [ls_res.get("url", "")] if ls_res.get("url") else [],
                        }
            except Exception:
                pass

            # Fallback: publish as free GitHub repo (builds credibility + traffic)
            if settings.GITHUB_TOKEN:
                logger.info("[IncomeLoop] Gumroad unavailable — publishing product as GitHub repo")
                from apps.core.tools.github_client import AriaGitHubClient
                import base64 as _b64
                gh    = AriaGitHubClient()
                owner = settings.GITHUB_USERNAME or "Geremypolanco"
                repo_name = (product_data.get("product_name", title)
                             .lower().replace(" ", "-").replace("'", "")[:40] + "-guide")
                readme = (
                    f"# {product_data.get('product_name', title)}\n\n"
                    f"> {product_data.get('tagline', 'A complete guide.')}\n\n"
                    f"{product_data.get('description', '')}\n\n"
                    f"## Table of Contents\n"
                    + "\n".join(f"- {ch}" for ch in product_data.get("table_of_contents", []))
                    + "\n\n---\n*Generated by ARIA AI*"
                )
                create_r = await gh._post("/user/repos", {
                    "name": repo_name, "description": product_data.get("tagline", "")[:100],
                    "private": False, "auto_init": False,
                })
                if "error" not in create_r:
                    await gh._put(f"/repos/{owner}/{repo_name}/contents/README.md", {
                        "message": "feat: initial guide",
                        "content": _b64.b64encode(readme.encode()).decode(),
                    })
                    repo_url = f"https://github.com/{owner}/{repo_name}"
                    return {
                        "success": True,
                        "summary": f"Published '{product_data.get('product_name',title)[:40]}' to GitHub (Gumroad needs GUMROAD_TOKEN)",
                        "revenue_potential": 1.0,
                        "urls": [repo_url],
                    }

            return {
                "success": False,
                "summary": f"Gumroad: {gr_res.get('error', 'failed')} — add GUMROAD_TOKEN to Fly.io secrets",
            }
        except Exception as exc:
            logger.error("[IncomeLoop] product_factory: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_opportunity_scan(self) -> dict:
        """Web research to discover NEW income opportunities ARIA hasn't tried yet."""
        try:
            from apps.core.tools.web_tools import WebTools
            from apps.core.tools.ai_client import get_ai_client, AIModel

            wt  = WebTools()
            queries = [
                "high converting digital product niches 2025 trending",
                "best affiliate marketing niches low competition 2025",
                "profitable online business ideas AI tools 2025",
            ]
            all_results = []
            for q in queries:
                r = await wt.search_web(q, num_results=5)
                if r.get("success"):
                    all_results.extend(r.get("results", [])[:3])

            if not all_results:
                return {"success": False, "summary": "No search results for opportunity scan"}

            ai = get_ai_client()
            if not ai:
                return {"success": False, "summary": "AI unavailable for opportunity analysis"}

            results_text = "\n".join(
                f"- {r.get('title','')}: {r.get('snippet','')[:150]}"
                for r in all_results[:12]
            )

            opp_data = await ai.complete_json(
                system="You are an income opportunity analyst. Be specific and actionable. Output JSON only.",
                user=f"""Analyze these search results and extract 3 SPECIFIC income opportunities:

{results_text}

Output JSON:
{{
  \"opportunities\": [
    {{
      \"name\": \"specific opportunity name\",
      \"niche_key\": \"snake_case_key\",
      \"description\": \"what exactly to do\",
      \"platform\": \"where to sell\",
      \"time_to_first_dollar\": \"X days\",
      \"estimated_monthly_revenue\": 500,
      \"difficulty\": \"easy|medium|hard\"
    }}
  ]
}}""",
                model=AIModel.STRATEGY,
                max_tokens=1000,
            )

            opportunities = (opp_data or {}).get("opportunities", [])

            if opportunities:
                try:
                    from apps.core.memory.redis_client import get_cache
                    cache = get_cache()
                    if cache:
                        for i, opp in enumerate(opportunities):
                            # Distribute: odd index → product_factory, even → ebook_factory
                            queue = "aria:income:opportunity_queue" if i % 2 == 0 else "aria:income:ebook_queue"
                            await cache.rpush(queue, json.dumps(opp))
                except Exception:
                    pass

            summaries = [f"{o.get('name','')} ({o.get('time_to_first_dollar','')}" for o in opportunities[:3]]
            return {
                "success": True,
                "summary": f"Found {len(opportunities)} opportunities: {', '.join(summaries)}",
                "revenue_potential": sum(o.get("estimated_monthly_revenue", 0) for o in opportunities),
                "urls": [],
            }
        except Exception as exc:
            logger.error("[IncomeLoop] opportunity_scan: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_social_blitz(self) -> dict:
        """Promote all live products via Zapier; falls back to Discord + GitHub cross-linking."""
        try:
            from apps.core.tools.niche_revenue_engine import get_niche_revenue_engine
            from apps.core.tools.zapier_connector import ZapierConnector

            engine   = get_niche_revenue_engine()
            listings = await engine._load_listings()
            live     = [ls for ls in listings if ls.listing_urls]
            sent = 0

            if live:
                zc = ZapierConnector()
                for ls in live[:5]:
                    try:
                        await zc.dispatch_event(
                            "CONTENT_READY",
                            {
                                "product_name": ls.title,
                                "tagline": ls.tagline,
                                "price": ls.pricing_tiers.get("basic", {}).get("price", 0),
                                "urls": ls.listing_urls,
                                "keywords": ", ".join(ls.keywords[:3]),
                                "category": ls.category,
                            },
                        )
                        sent += 1
                        await asyncio.sleep(2)
                    except Exception:
                        pass

            # Discord fallback: announce all recent GitHub content
            discord_url = getattr(settings, "DISCORD_WEBHOOK_URL", None)
            if discord_url and settings.GITHUB_TOKEN:
                try:
                    owner = settings.GITHUB_USERNAME or "Geremypolanco"
                    import httpx as _httpx
                    async with _httpx.AsyncClient(timeout=10) as _client:
                        msg = (
                            f"🚀 **ARIA Content Update**\n"
                            f"📚 Blog: https://github.com/{owner}/aria-insights\n"
                            f"🌐 Portfolio: https://github.com/{owner}/aria-portfolio\n"
                            f"*New AI-generated content published — check it out!*"
                        )
                        await _client.post(discord_url, json={"content": msg})
                        sent += 1
                except Exception:
                    pass

            if sent > 0:
                return {
                    "success": True,
                    "summary": f"Social blitz: {sent} channels promoted",
                    "revenue_potential": 0,
                    "urls": [],
                }
            return {"success": False, "summary": "Social blitz: no channels available (add ZAPIER_WEBHOOK_URL or DISCORD_WEBHOOK_URL)"}
        except Exception as exc:
            logger.error("[IncomeLoop] social_blitz: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_premium_offer(self) -> dict:
        """Create a high-ticket B2B service offer ($500-$5,000+)."""
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.gumroad_tools import GumroadTools
            from apps.core.tools.web_tools import WebTools

            wt = WebTools()
            r  = await wt.search_web("business automation AI consulting demand 2025", num_results=5)
            context = ""
            if r.get("success") and r.get("results"):
                context = r["results"][0].get("snippet", "")[:300]

            ai = get_ai_client()
            if not ai:
                return {"success": False, "summary": "AI unavailable"}

            offer = await ai.complete_json(
                system="You are a B2B sales expert. Create premium service packages that command $500-$5000. Output JSON only.",
                user=f"""Create a premium B2B consulting offer based on this market insight:
{context}

Focus on AI automation / business efficiency / revenue growth.

JSON:
{{
  \"offer_name\": \"Premium offer title\",
  \"tagline\": \"ROI-focused one-liner\",
  \"description\": \"Compelling 250+ word description. Lead with ROI.\",
  \"what_included\": [\"Deliverable 1\", \"Deliverable 2\", \"Deliverable 3\", \"Deliverable 4\"],
  \"price_cents\": 149700,
  \"target_client\": \"Description of ideal B2B client\",
  \"tags\": [\"consulting\", \"automation\", \"ai\", \"b2b\"]
}}""",
                model=AIModel.STRATEGY,
                max_tokens=1500,
            )

            if not offer:
                return {"success": False, "summary": "AI failed"}

            gt = GumroadTools()
            gr = await gt.create_product(
                name=offer.get("offer_name", "Premium AI Consulting"),
                description=offer.get("description", ""),
                price_cents=offer.get("price_cents", 149700),
                tags=offer.get("tags", ["consulting", "ai", "b2b"]),
            )

            if gr.get("success"):
                return {
                    "success": True,
                    "summary": f"Premium offer '{offer.get('offer_name','')[:50]}' at ${offer.get('price_cents',149700)/100:.0f}",
                    "revenue_potential": offer.get("price_cents", 149700) / 100,
                    "urls": [gr.get("url", "")] if gr.get("url") else [],
                }

            # GitHub fallback: create a consulting landing page repo
            if settings.GITHUB_TOKEN:
                try:
                    from apps.core.tools.github_client import AriaGitHubClient
                    import base64 as _b64
                    gh    = AriaGitHubClient()
                    owner = settings.GITHUB_USERNAME or "Geremypolanco"
                    repo_name = "ai-consulting-services"
                    included = "\n".join(f"- {item}" for item in offer.get("what_included", []))
                    readme = (
                        f"# {offer.get('offer_name', 'AI Business Consulting')}\n\n"
                        f"> {offer.get('tagline', 'Transform your business with AI')}\n\n"
                        f"## About This Service\n\n{offer.get('description', '')}\n\n"
                        f"## What's Included\n\n{included}\n\n"
                        f"## Pricing\n\n**${offer.get('price_cents', 149700)/100:.0f}**\n\n"
                        f"## Target Client\n\n{offer.get('target_client', 'B2B companies looking to leverage AI')}\n\n"
                        f"## Contact\n\nOpen an issue or email us to inquire.\n\n"
                        f"---\n*Service by ARIA AI — Autonomous AI Business Platform*"
                    )
                    existing = await gh._get(f"/repos/{owner}/{repo_name}")
                    if "error" in existing:
                        await gh._post("/user/repos", {
                            "name": repo_name,
                            "description": offer.get("tagline", "AI consulting services")[:100],
                            "private": False, "auto_init": False,
                        })
                    existing_file = await gh._get(f"/repos/{owner}/{repo_name}/contents/README.md")
                    sha = existing_file.get("sha", "") if "error" not in existing_file else ""
                    put_args: dict = {
                        "message": f"feat: update consulting offer — {offer.get('offer_name','')[:50]}",
                        "content": _b64.b64encode(readme.encode()).decode(),
                    }
                    if sha:
                        put_args["sha"] = sha
                    await gh._put(f"/repos/{owner}/{repo_name}/contents/README.md", put_args)
                    return {
                        "success": True,
                        "summary": f"Premium offer landing page: github.com/{owner}/{repo_name} (add GUMROAD_TOKEN to enable payments)",
                        "revenue_potential": 50.0,
                        "urls": [f"https://github.com/{owner}/{repo_name}"],
                    }
                except Exception:
                    pass

            return {"success": False, "summary": f"Gumroad: {gr.get('error', 'failed')} — add GUMROAD_TOKEN to Fly.io secrets"}

        except Exception as exc:
            logger.error("[IncomeLoop] premium_offer: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_shopify_listing(self) -> dict:
        """Create a Shopify product listing for a trending digital item."""
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.commerce_tools import get_commerce_tools
            from apps.core.tools.content_pipeline import ContentPipeline

            cp     = ContentPipeline()
            topics = await cp.get_trending_topics(limit=3)
            topic  = topics[0] if topics else "AI productivity tools 2025"

            ai = get_ai_client()
            if not ai:
                return {"success": False, "summary": "AI unavailable"}

            product = await ai.complete_json(
                system="You are a Shopify product expert. Create compelling digital product listings. Output JSON only.",
                user=f"""Create a Shopify digital product listing for the trending topic: \"{topic}\"

JSON:
{{
  \"title\": \"Product title (60 chars max)\",
  \"description\": \"Compelling HTML product description (200+ words).\",
  \"price\": \"29.99\",
  \"product_type\": \"Digital Download\",
  \"tags\": [\"digital\", \"download\", \"productivity\"],
  \"status\": \"active\"
}}""",
                model=AIModel.FAST,
                max_tokens=800,
            )

            if not product:
                return {"success": False, "summary": "AI failed to generate product"}

            ct    = get_commerce_tools()
            price = float(product.get("price", "29.99"))
            res   = await ct.shopify_create_product(
                title=product.get("title", f"Digital Product: {topic[:40]}"),
                description=product.get("description", ""),
                price=price,
                product_type=product.get("product_type", "Digital Download"),
            )

            if res.get("success"):
                url = res.get("shop_url", "")
                return {
                    "success": True,
                    "summary": f"Shopify product '{product.get('title','')[:50]}' at ${price:.2f}",
                    "revenue_potential": price,
                    "urls": [url] if url else [],
                }

            # Fallback: LemonSqueezy
            try:
                from apps.core.tools.lemon_squeezy_tools import LemonSqueezyTools
                ls = LemonSqueezyTools()
                if ls._configured():
                    ls_res = await ls.create_product(
                        name=product.get("title", f"Digital: {str(topic)[:40]}"),
                        description=product.get("description", ""),
                        price_cents=int(price * 100),
                    )
                    if ls_res.get("success"):
                        return {
                            "success": True,
                            "summary": f"LemonSqueezy product '{product.get('title','')[:50]}' at ${price:.2f}",
                            "revenue_potential": price,
                            "urls": [ls_res.get("url", "")] if ls_res.get("url") else [],
                        }
            except Exception:
                pass

            # Fallback: Gumroad
            try:
                from apps.core.tools.gumroad_tools import GumroadTools
                gt = GumroadTools()
                gr = await gt.create_product(
                    name=product.get("title", f"Digital: {str(topic)[:40]}"),
                    description=product.get("description", ""),
                    price_cents=int(price * 100),
                    tags=product.get("tags", ["digital", "download"]),
                )
                if gr.get("success"):
                    return {
                        "success": True,
                        "summary": f"Gumroad product '{product.get('title','')[:50]}' at ${price:.2f} (Shopify unavailable)",
                        "revenue_potential": price,
                        "urls": [gr.get("url", "")] if gr.get("url") else [],
                    }
            except Exception:
                pass

            return {"success": False, "summary": f"Shopify: {res.get('error', 'failed')} — add SHOPIFY_ADMIN_TOKEN or GUMROAD_TOKEN"}

        except Exception as exc:
            logger.error("[IncomeLoop] shopify_listing: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_ebook_factory(self) -> dict:
        """Generate a complete ebook on a trending topic and sell it on Gumroad at $7-$27."""
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.gumroad_tools import GumroadTools
            from apps.core.tools.content_pipeline import ContentPipeline

            # Try opportunity queue first (same source as product_factory but dedicated key)
            topic_str = ""
            try:
                from apps.core.memory.redis_client import get_cache
                cache = get_cache()
                if cache:
                    raw = await cache.lpop("aria:income:ebook_queue")
                    if raw:
                        opp = json.loads(raw) if isinstance(raw, str) else raw
                        topic_str = opp.get("name", "")
            except Exception:
                pass

            if not topic_str:
                cp     = ContentPipeline()
                topics = await cp.get_trending_topics(limit=5)
                if topics:
                    raw_topic = topics[random.randint(0, min(2, len(topics)-1))]
                    topic_str = raw_topic.get("title", str(raw_topic))[:80] if isinstance(raw_topic, dict) else str(raw_topic)[:80]
                else:
                    topic_str = "AI side income strategies for solopreneurs"

            ai = get_ai_client()
            if not ai:
                return {"success": False, "summary": "AI unavailable"}

            ebook = await ai.complete_json(
                system="You are a bestselling ebook author. Create detailed, valuable ebooks that people buy. Output JSON only.",
                user=f"""Create a complete sellable ebook on: \"{topic_str}\"

JSON:
{{
  \"title\": \"Compelling ebook title (60 chars max)\",
  \"subtitle\": \"Subtitle explaining the value (80 chars)\",
  \"description\": \"Sales page description (300+ words). Lead with transformation.\",
  \"table_of_contents\": [\"Chapter 1: ...\", \"Chapter 2: ...\", \"Chapter 3: ...\", \"Chapter 4: ...\", \"Chapter 5: ...\"],
  \"price_cents\": 1700,
  \"tags\": [\"ebook\", \"guide\", \"productivity\"],
  \"category\": \"Self-Help\"
}}""",
                model=AIModel.STRATEGY,
                max_tokens=1500,
            )

            if not ebook:
                return {"success": False, "summary": "AI failed to generate ebook"}

            toc = ebook.get("table_of_contents", [])
            full_description = ebook.get("description", "")
            if toc:
                full_description += "\n\n**What You'll Learn:**\n" + "\n".join(f"✓ {ch}" for ch in toc)
            full_description += f"\n\n**Format:** PDF Ebook | Instant Download | {len(toc)} Chapters"

            gt  = GumroadTools()
            gr  = await gt.create_product(
                name=ebook.get("title", f"The Complete Guide to {topic_str[:30]}"),
                description=full_description,
                price_cents=ebook.get("price_cents", 1700),
                tags=ebook.get("tags", ["ebook", "guide"]),
            )

            if gr.get("success"):
                price = ebook.get("price_cents", 1700) / 100
                return {
                    "success": True,
                    "summary": f"Ebook '{ebook.get('title','')[:50]}' at ${price:.2f} — {len(toc)} chapters",
                    "revenue_potential": price,
                    "urls": [gr.get("url", "")] if gr.get("url") else [],
                }

            # LemonSqueezy fallback for ebook
            try:
                from apps.core.tools.lemon_squeezy_tools import LemonSqueezyTools
                ls = LemonSqueezyTools()
                if ls._configured():
                    ls_res = await ls.create_product(
                        name=ebook.get("title", f"Guide to {topic_str[:30]}"),
                        description=full_description,
                        price_cents=ebook.get("price_cents", 1700),
                    )
                    if ls_res.get("success"):
                        price = ebook.get("price_cents", 1700) / 100
                        return {
                            "success": True,
                            "summary": f"Ebook '{ebook.get('title','')[:50]}' at ${price:.2f} on LemonSqueezy",
                            "revenue_potential": price,
                            "urls": [ls_res.get("url", "")] if ls_res.get("url") else [],
                        }
            except Exception:
                pass

            # Fallback: generate real PDF with actual chapter content
            logger.info("[IncomeLoop] Gumroad unavailable — generating real PDF ebook")
            try:
                from apps.core.tools.pdf_generator import generate_pdf as _gen_pdf

                # Generate real content for each chapter
                chapters_content_parts = []
                if toc and ai:
                    for i, chapter_title in enumerate(toc[:5]):
                        try:
                            chapter_data = await ai.complete_json(
                                system="You write detailed, actionable educational content. Output JSON only.",
                                user=f"""Write content for chapter: "{chapter_title}"
Book: "{ebook.get('title', 'Guide')}"
Topic: {topic_str}

JSON: {{"content": "Chapter content (300+ words). Use practical tips, examples, numbered lists. No fluff."}}""",
                                model=AIModel.FAST,
                                max_tokens=800,
                            )
                            chapter_content = (chapter_data or {}).get("content", f"Content about {chapter_title}.")
                        except Exception:
                            chapter_content = f"This chapter covers {chapter_title} in depth with practical examples and actionable tips."
                        chapters_content_parts.append(f"## {chapter_title}\n\n{chapter_content}")
                else:
                    chapters_content_parts = [
                        f"## {ch}\n\nThis chapter provides a comprehensive overview of {ch.lower()} with practical examples and implementation strategies."
                        for ch in toc[:5]
                    ]

                chapters_content = "\n\n---\n\n".join(chapters_content_parts)
                pdf_content = (
                    f"{ebook.get('description', '')}\n\n"
                    f"---\n\n{chapters_content}"
                )
                pdf_r = await _gen_pdf(
                    title=ebook.get("title", f"Guide to {topic}"),
                    content=pdf_content,
                    sections=[],
                )
                if pdf_r.get("success") and pdf_r.get("pdf_bytes"):
                    try:
                        from apps.core.tools.telegram_bot import get_bot
                        bot = get_bot()
                        fname = pdf_r.get("filename", "ebook.pdf")
                        await bot._send_document_bytes(
                            chat_id=str(getattr(settings, "TELEGRAM_CHAT_ID", "")),
                            doc_bytes=pdf_r["pdf_bytes"],
                            filename=fname,
                            caption=(
                                f"📚 <b>Ebook generado (pendiente publicación)</b>\n"
                                f"Título: {ebook.get('title','')[:60]}\n"
                                f"Precio sugerido: ${ebook.get('price_cents',1700)/100:.0f}\n"
                                f"Sube este PDF a Gumroad para empezar a vender.\n"
                                f"Falta: <code>GUMROAD_TOKEN</code> en Fly.io secrets"
                            ),
                        )
                    except Exception as tg_exc:
                        logger.warning("[IncomeLoop] Telegram send: %s", tg_exc)
                    return {
                        "success": True,
                        "summary": f"Ebook PDF generated locally: '{ebook.get('title','')[:50]}' (needs Gumroad upload)",
                        "revenue_potential": ebook.get("price_cents", 1700) / 100,
                        "urls": [],
                    }
            except Exception as pdf_exc:
                logger.warning("[IncomeLoop] PDF fallback failed: %s", pdf_exc)

            return {"success": False, "summary": f"Gumroad: {gr.get('error', 'failed')} — PDF fallback also attempted"}

        except Exception as exc:
            logger.error("[IncomeLoop] ebook_factory: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_email_campaign(self) -> dict:
        """Create and send a Mailchimp email campaign; falls back to GitHub newsletter edition."""
        # Primary: Mailchimp
        try:
            from apps.core.tools.mailchimp_tools import MailchimpTools
            from apps.core.tools.ai_client import get_ai_client, AIModel

            mc = MailchimpTools()
            if mc._configured():
                lists = await mc.get_lists()
                if lists.get("lists"):
                    list_id = lists["lists"][0]["id"]
                    ai = get_ai_client()
                    if ai:
                        email_data = await ai.complete_json(
                            system="You are an email marketing expert. Write high-converting email campaigns. Output JSON only.",
                            user="""Create an email campaign promoting AI productivity tools and digital products.

JSON:
{
  "subject": "Email subject line (compelling, under 60 chars)",
  "preview_text": "Preview text (50 chars max)",
  "html_body": "Full HTML email body (300+ words). Include CTA button. Professional and persuasive."
}""",
                            model=AIModel.FAST,
                            max_tokens=1200,
                        )
                        if email_data:
                            result = await mc.create_campaign(
                                list_id=list_id,
                                subject=email_data.get("subject", "Discover AI Tools That Make You Money"),
                                from_name=getattr(settings, "MAILCHIMP_FROM_NAME", None) or "ARIA AI",
                                reply_to=getattr(settings, "MAILCHIMP_REPLY_TO", None) or "noreply@aria.ai",
                                preview_text=email_data.get("preview_text", "Exclusive offer inside"),
                                body_html=email_data.get("html_body", "<p>Check out our latest products!</p>"),
                            )
                            if result.get("success"):
                                return {
                                    "success": True,
                                    "summary": f"Email campaign '{email_data.get('subject','')[:50]}' → {list_id}",
                                    "revenue_potential": 150.0,
                                    "urls": [],
                                }
        except Exception:
            pass

        # Fallback: publish a newsletter edition to GitHub (public, indexed by Google)
        if not settings.GITHUB_TOKEN:
            return {"success": False, "summary": "Email campaign: add MAILCHIMP_API_KEY; GitHub newsletter requires GITHUB_TOKEN"}
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.github_client import AriaGitHubClient
            import base64 as _b64
            from datetime import datetime, timezone

            ai = get_ai_client()
            if not ai:
                return {"success": False, "summary": "AI unavailable"}

            owner = settings.GITHUB_USERNAME or "Geremypolanco"
            repo  = "aria-newsletter"
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            month = datetime.now(timezone.utc).strftime("%B %Y")

            edition = await ai.complete_json(
                system="You write valuable newsletter editions that people forward to their friends. Output JSON only.",
                user=f"""Write a monthly newsletter edition for {month} about AI tools, productivity, and making money online.

The newsletter is from ARIA AI — an autonomous AI business platform.

JSON:
{{
  "subject": "Newsletter subject (catchy, 60 chars max)",
  "headline": "Main headline for this edition",
  "intro": "Opening paragraph — hook the reader (100 words)",
  "section_1_title": "First section title",
  "section_1_body": "First section content (200+ words). Actionable insights.",
  "section_2_title": "Second section title",
  "section_2_body": "Second section content (200+ words). Tips or tools.",
  "tool_of_month": "One specific tool or resource recommendation with why",
  "cta": "Call to action paragraph with link to https://github.com/{owner}/aria-portfolio"
}}""",
                model=AIModel.STRATEGY,
                max_tokens=2500,
            )

            if not edition:
                return {"success": False, "summary": "AI failed to generate newsletter"}

            assoc = getattr(settings, "AMAZON_ASSOCIATE_TAG", None) or ""
            aff_link = f"https://amazon.com/s?k=ai+tools+productivity&tag={assoc}" if assoc else "https://github.com/{owner}/aria-insights"

            newsletter_md = (
                f"# {edition.get('headline', f'ARIA AI Newsletter — {month}')}\n\n"
                f"*{edition.get('subject', f'{month} Edition')}*\n\n"
                f"---\n\n"
                f"{edition.get('intro', '')}\n\n"
                f"## {edition.get('section_1_title', 'This Month in AI')}\n\n"
                f"{edition.get('section_1_body', '')}\n\n"
                f"## {edition.get('section_2_title', 'Tools & Resources')}\n\n"
                f"{edition.get('section_2_body', '')}\n\n"
                f"## 🔧 Tool of the Month\n\n"
                f"{edition.get('tool_of_month', '')}\n\n"
                f"## Resources\n\n"
                + (f"- [Best AI Tools on Amazon]({aff_link})\n" if assoc else "")
                + f"- [ARIA Portfolio](https://github.com/{owner}/aria-portfolio)\n"
                f"- [ARIA Insights Blog](https://github.com/{owner}/aria-insights)\n\n"
                f"---\n\n"
                f"{edition.get('cta', '')}\n\n"
                f"*Newsletter by [ARIA AI](https://github.com/{owner}/aria-portfolio) — Published {today}*"
            )

            gh = AriaGitHubClient()
            existing = await gh._get(f"/repos/{owner}/{repo}")
            if "error" in existing:
                await gh._post("/user/repos", {
                    "name": repo,
                    "description": f"ARIA AI Monthly Newsletter — AI tools, productivity, and online income",
                    "private": False, "auto_init": True,
                })
                await asyncio.sleep(2)
                try:
                    await gh._post(f"/repos/{owner}/{repo}/pages", {"source": {"branch": "main", "path": "/"}})
                    await gh._put(f"/repos/{owner}/{repo}/topics", {"names": ["newsletter", "ai", "productivity", "income", "tools"]})
                except Exception:
                    pass

            filename = f"editions/{today}-newsletter.md"
            file_r   = await gh._put(f"/repos/{owner}/{repo}/contents/{filename}", {
                "message": f"newsletter: {edition.get('subject', month)[:60]}",
                "content": _b64.b64encode(newsletter_md.encode()).decode(),
            })

            if "error" not in file_r:
                url = f"https://github.com/{owner}/{repo}/blob/main/{filename}"
                return {
                    "success": True,
                    "summary": f"Newsletter '{edition.get('subject','')[:50]}' published to GitHub (add MAILCHIMP_API_KEY to send to subscribers)",
                    "revenue_potential": 5.0,
                    "urls": [url],
                }
            return {"success": False, "summary": "Email campaign: Mailchimp not configured; GitHub newsletter push failed"}

        except Exception as exc:
            logger.error("[IncomeLoop] email_campaign fallback: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_github_publish(self) -> dict:
        """
        Publish a valuable resource to GitHub — works with only GITHUB_TOKEN.
        Creates a public repo with a complete guide/tool, making ARIA visible online.
        All public GitHub repos get indexed by search engines within 24h.
        """
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.web_tools import WebTools
            from apps.core.tools.github_client import AriaGitHubClient

            if not settings.GITHUB_TOKEN:
                return {"success": False, "summary": "GITHUB_TOKEN not configured"}

            wt     = WebTools()
            ai     = get_ai_client()
            if not ai:
                return {"success": False, "summary": "AI unavailable"}

            # Get a trending topic
            r = await wt.search_web("trending developer tools AI productivity 2025", num_results=5)
            topic = "AI Productivity Tools for Developers"
            if r.get("success") and r.get("results"):
                topic = r["results"][0].get("title", topic)[:80]

            # Generate a complete, valuable resource (README + examples + contributing)
            content_data = await ai.complete_json(
                system=(
                    "You create high-value open-source resources that developers star and share. "
                    "Write complete, working content. No placeholders. Output JSON only."
                ),
                user=f"""Create a complete GitHub resource for: "{topic}"

JSON:
{{
  "repo_name": "snake_case_repo_name_60_chars_max",
  "description": "One-line description under 100 chars",
  "readme": "Complete README.md (600+ words). Include: badges, overview, features, installation, usage with realistic code examples, contributing, license. Use proper markdown.",
  "example_code": "A realistic, working Python/JS/bash script (50+ lines) that demonstrates the core concept. Include comments.",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}}""",
                model=AIModel.STRATEGY,
                max_tokens=4000,
            )

            if not content_data:
                return {"success": False, "summary": "AI failed to generate content"}

            repo_name   = content_data.get("repo_name", "ai-productivity-guide").replace(" ", "-").lower()[:60]
            description = content_data.get("description", f"A complete guide to {topic}")[:100]
            readme      = content_data.get("readme", f"# {topic}\n\nA comprehensive guide.\n")
            example     = content_data.get("example_code", "")
            topics      = content_data.get("tags", ["ai", "productivity", "guide"])[:5]

            gh     = AriaGitHubClient()
            owner  = settings.GITHUB_USERNAME or "Geremypolanco"

            # Check if repo exists — create it if not
            existing = await gh._get(f"/repos/{owner}/{repo_name}")
            if "error" in existing:
                create_r = await gh._post(f"/user/repos", {
                    "name":        repo_name,
                    "description": description,
                    "private":     False,
                    "auto_init":   False,
                    "has_issues":  True,
                    "has_wiki":    False,
                })
                if "error" in create_r:
                    return {"success": False, "summary": f"GitHub repo creation: {create_r.get('error','failed')[:80]}"}

            import base64 as _b64

            # Push README.md
            encoded = _b64.b64encode(readme.encode()).decode()
            file_r  = await gh._put(f"/repos/{owner}/{repo_name}/contents/README.md", {
                "message": f"feat: add comprehensive guide — {description[:60]}",
                "content": encoded,
            })

            if "error" in file_r:
                # File may already exist — try updating
                existing_file = await gh._get(f"/repos/{owner}/{repo_name}/contents/README.md")
                sha = existing_file.get("sha", "")
                if sha:
                    file_r = await gh._put(f"/repos/{owner}/{repo_name}/contents/README.md", {
                        "message": f"update: refresh guide content",
                        "content": encoded,
                        "sha": sha,
                    })

            # Push examples/quickstart — makes repo more valuable and searchable
            if example:
                try:
                    ext = "py" if ("def " in example or "import " in example) else ("js" if "function " in example or "const " in example else "sh")
                    example_encoded = _b64.b64encode(example.encode()).decode()
                    await gh._put(f"/repos/{owner}/{repo_name}/contents/examples/quickstart.{ext}", {
                        "message": "feat: add quickstart example",
                        "content": example_encoded,
                    })
                except Exception:
                    pass

            # Push CONTRIBUTING.md — signals active community, improves discoverability
            try:
                contributing = (
                    f"# Contributing to {repo_name}\n\n"
                    f"Thank you for your interest in contributing! This project is maintained by ARIA AI.\n\n"
                    f"## How to Contribute\n\n"
                    f"1. Fork the repository\n"
                    f"2. Create a feature branch: `git checkout -b feature/your-feature`\n"
                    f"3. Make your changes and commit: `git commit -m 'feat: your feature'`\n"
                    f"4. Push to your fork: `git push origin feature/your-feature`\n"
                    f"5. Open a Pull Request\n\n"
                    f"## Code Style\n\n"
                    f"- Keep code simple and well-commented\n"
                    f"- Add tests for new features\n"
                    f"- Update README.md when adding features\n\n"
                    f"## Questions?\n\nOpen an issue — we respond within 24 hours.\n"
                )
                await gh._put(f"/repos/{owner}/{repo_name}/contents/CONTRIBUTING.md", {
                    "message": "docs: add contributing guide",
                    "content": _b64.b64encode(contributing.encode()).decode(),
                })
            except Exception:
                pass

            # Set topics and homepage (GitHub Pages URL for better SEO)
            try:
                await gh._put(f"/repos/{owner}/{repo_name}/topics", {"names": topics})
            except Exception:
                pass
            try:
                pages_url = f"https://{owner.lower()}.github.io/{repo_name}/"
                await gh._patch(f"/repos/{owner}/{repo_name}", {
                    "homepage": pages_url,
                    "has_wiki": False,
                })
                # Enable GitHub Pages
                await gh._post(f"/repos/{owner}/{repo_name}/pages", {
                    "source": {"branch": "main", "path": "/"},
                })
            except Exception:
                pass

            # Add FUNDING.yml — enables the "Sponsor" button on GitHub
            try:
                import base64 as _b64f
                assoc = getattr(settings, "AMAZON_ASSOCIATE_TAG", None) or ""
                funding_content = (
                    f"# ARIA AI Open Source Funding\n"
                    f"# Support our AI projects\n"
                    f"github: [{owner}]\n"
                    f"custom: [\"https://github.com/{owner}/aria-portfolio\"]\n"
                )
                if assoc:
                    funding_content += f"# amazon_wishlist: {assoc}\n"
                existing_funding = await gh._get(f"/repos/{owner}/{repo_name}/contents/.github/FUNDING.yml")
                sha_f = existing_funding.get("sha", "") if "error" not in existing_funding else ""
                put_f: dict = {
                    "message": "chore: add FUNDING.yml",
                    "content": _b64f.b64encode(funding_content.encode()).decode(),
                }
                if sha_f:
                    put_f["sha"] = sha_f
                await gh._put(f"/repos/{owner}/{repo_name}/contents/.github/FUNDING.yml", put_f)
            except Exception:
                pass

            repo_url = f"https://github.com/{owner}/{repo_name}"
            return {
                "success": True,
                "summary": f"Published '{repo_name}' to GitHub: {description[:60]}",
                "revenue_potential": 5.0,  # Indirect: traffic + credibility
                "urls": [repo_url],
            }

        except Exception as exc:
            logger.error("[IncomeLoop] github_publish: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_affiliate_content(self) -> dict:
        """
        Generate affiliate-optimized review/comparison articles published to GitHub blog.
        Uses real Amazon ASINs from the catalog for higher conversion.
        Works with only GITHUB_TOKEN — earns passive income via affiliate clicks.
        """
        try:
            import re as _re
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.web_tools import WebTools
            from apps.core.tools.content_pipeline import AFFILIATE_CATALOG

            ai = get_ai_client()
            if not ai:
                return {"success": False, "summary": "AI unavailable for affiliate content"}

            assoc = getattr(settings, "AMAZON_ASSOCIATE_TAG", None) or ""

            # Pick a category with known products from catalog
            categories = list(AFFILIATE_CATALOG.keys())
            category   = random.choice(categories)
            products   = AFFILIATE_CATALOG[category][:5]

            # Build topic from category
            category_topics = {
                "tech":             "best tech accessories for developers and entrepreneurs 2025",
                "ai":               "best AI tools and hardware for machine learning 2025",
                "business":         "best business tools for entrepreneurs and solopreneurs 2025",
                "finance":          "best finance books and tools for building wealth 2025",
                "fitness":          "best fitness trackers and health gadgets for productivity 2025",
                "marketing":        "best marketing tools and books for digital marketers 2025",
                "crypto":           "best crypto hardware wallets and resources for investors 2025",
                "productivity":     "best productivity tools and books for high performers 2025",
                "ecommerce":        "best tools and equipment for starting an ecommerce business 2025",
                "content_creator":  "best gear and equipment for content creators and streamers 2025",
            }
            topic = category_topics.get(category, f"best {category} products and tools 2025")

            wt = WebTools()
            r  = await wt.search_web(f"{topic} review", num_results=5)
            search_context = ""
            if r.get("success") and r.get("results"):
                search_context = "\n".join(
                    f"- {res.get('title','')}: {res.get('snippet','')[:100]}"
                    for res in r["results"][:4]
                )

            # Build product hints for AI
            product_hints = "\n".join(
                f"- {p['title']} (keyword: {p['keyword']})"
                for p in products
            )

            article_data = await ai.complete_json(
                system=(
                    "You write high-converting affiliate review articles. "
                    "Be specific, practical, name real products. Output JSON only."
                ),
                user=f"""Write a detailed review article about: "{topic}"

Known products to cover (include these naturally in the article):
{product_hints}

Web context:
{search_context}

JSON:
{{
  "title": "SEO title with year (60 chars max)",
  "slug": "url-friendly-slug-max-50-chars",
  "description": "Meta description (155 chars)",
  "tags": ["{category}", "review", "tools", "2025"],
  "content": "Complete markdown article (700+ words). Include: compelling intro, H2 section for each product from the list, pros/cons, who it's for, pricing. End with a comparison table and final recommendation."
}}""",
                model=AIModel.STRATEGY,
                max_tokens=3000,
            )

            if not article_data:
                return {"success": False, "summary": "AI failed to generate affiliate article"}

            content = article_data.get("content", "")

            # Inject real ASIN-based affiliate links
            for product in products:
                kw  = product["keyword"].lower()
                if kw in content.lower():
                    aff_url = (
                        f"https://amazon.com/dp/{product['asin']}?tag={assoc}"
                        if assoc else
                        f"https://amazon.com/dp/{product['asin']}"
                    )
                    import re as _re2
                    pattern = _re2.compile(re.escape(product["title"]), _re2.IGNORECASE)
                    content, n = pattern.subn(f"[{product['title']}]({aff_url})", content, count=1)
                    if n == 0:
                        pattern2 = _re2.compile(re.escape(kw), _re2.IGNORECASE)
                        content, _ = pattern2.subn(f"[{kw}]({aff_url})", content, count=1)

            if assoc:
                search_kw = topic.replace(" ", "+")
                content += (
                    f"\n\n---\n"
                    f"*Disclosure: This article contains Amazon affiliate links. "
                    f"We earn a small commission at no extra cost to you.*\n"
                    f"[Browse all {category} products on Amazon](https://amazon.com/s?k={search_kw}&tag={assoc})\n"
                )

            result = await self._exec_github_blog(
                existing_articles=[{
                    "title":       article_data.get("title", topic),
                    "slug":        article_data.get("slug", topic.replace(" ", "-").lower()[:50]),
                    "description": article_data.get("description", f"Best {topic} reviewed"),
                    "tags":        article_data.get("tags", [category, "tools", "review"]),
                    "content":     content,
                }],
            )
            suffix = f" ({len(products)} Amazon links, tag={assoc})" if assoc else " (add AMAZON_ASSOCIATE_TAG for commissions)"
            result["summary"] = f"Affiliate review: '{article_data.get('title', topic)[:45]}'{suffix}"
            return result

        except Exception as exc:
            logger.error("[IncomeLoop] affiliate_content: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_lead_magnet(self) -> dict:
        """
        Create a high-value free resource (checklist, template, toolkit) published to GitHub.
        Goal: email capture funnel → free value → upsell to paid products.
        Works with GITHUB_TOKEN only. Drives organic traffic via SEO.
        """
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.web_tools import WebTools
            from apps.core.tools.github_client import AriaGitHubClient
            import base64 as _b64

            if not settings.GITHUB_TOKEN:
                return {"success": False, "summary": "GITHUB_TOKEN required"}

            ai = get_ai_client()
            if not ai:
                return {"success": False, "summary": "AI unavailable"}

            wt = WebTools()
            r  = await wt.search_web("high demand free resources templates checklists entrepreneurs 2025", num_results=5)
            topic = "AI Business Automation Toolkit"
            if r.get("success") and r.get("results"):
                topic = r["results"][0].get("title", topic)[:80]

            magnet = await ai.complete_json(
                system="You create irresistible free lead magnets that build email lists. Output JSON only.",
                user=f"""Create a complete free lead magnet resource on: "{topic}"

This should be something people would happily give their email to receive.

JSON:
{{
  "title": "Resource title (60 chars, power words)",
  "slug": "url-slug",
  "tagline": "What they get in one sentence",
  "resource_type": "checklist|template|toolkit|swipe-file|cheat-sheet",
  "content": "Complete resource content (600+ words). If checklist: 20+ actionable items. If template: full working template. Make it genuinely valuable.",
  "cta": "Email capture CTA text",
  "upsell_hint": "Brief mention of a paid upgrade they can get"
}}""",
                model=AIModel.STRATEGY,
                max_tokens=3000,
            )

            if not magnet:
                return {"success": False, "summary": "AI failed to generate lead magnet"}

            owner     = settings.GITHUB_USERNAME or "Geremypolanco"
            repo_name = "aria-free-resources"
            slug      = magnet.get("slug", "free-toolkit").replace(" ", "-").lower()[:50]
            title     = magnet.get("title", topic)[:60]
            content   = magnet.get("content", "")
            rtype     = magnet.get("resource_type", "toolkit")

            # Build the resource file
            resource_md = (
                f"# {title}\n\n"
                f"> {magnet.get('tagline', 'A free resource from ARIA AI')}\n\n"
                f"**Type:** {rtype.replace('-', ' ').title()}\n\n"
                f"---\n\n"
                f"{content}\n\n"
                f"---\n\n"
                f"## Want More?\n\n"
                f"{magnet.get('upsell_hint', 'Check out our premium resources.')}\n\n"
                f"⭐ Star this repo to get notified of new free resources!\n\n"
                f"*Free resource by [ARIA AI](https://github.com/{owner}/aria-portfolio)*"
            )

            gh = AriaGitHubClient()
            existing = await gh._get(f"/repos/{owner}/{repo_name}")
            if "error" in existing:
                create_r = await gh._post("/user/repos", {
                    "name": repo_name,
                    "description": "Free AI-powered resources, templates, and toolkits for entrepreneurs",
                    "private": False, "auto_init": True, "has_issues": False,
                })
                if "error" in create_r:
                    return {"success": False, "summary": f"Could not create {repo_name}"}
                await asyncio.sleep(2)
                # Set topics
                try:
                    await gh._put(f"/repos/{owner}/{repo_name}/topics", {
                        "names": ["free-resources", "templates", "productivity", "ai", "entrepreneur"]
                    })
                except Exception:
                    pass

            # Push the resource
            filename = f"resources/{slug}.md"
            encoded  = _b64.b64encode(resource_md.encode()).decode()
            file_r   = await gh._put(f"/repos/{owner}/{repo_name}/contents/{filename}", {
                "message": f"feat: add {rtype} — {title[:50]}",
                "content": encoded,
            })

            repo_url = f"https://github.com/{owner}/{repo_name}"
            if "error" not in file_r:
                # Also publish announcement on blog
                asyncio.create_task(self._exec_github_blog([{
                    "title": f"Free {rtype.title()}: {title}",
                    "slug": f"free-{slug}",
                    "description": magnet.get("tagline", "")[:155],
                    "tags": ["free", "resource", rtype, "ai", "productivity"],
                    "content": (
                        f"We just published a completely free {rtype} that you can download right now.\n\n"
                        f"**{title}**\n\n{magnet.get('tagline', '')}\n\n"
                        f"[Download free →]({repo_url}/blob/main/{filename})\n\n"
                        f"{content[:400]}...\n\n"
                        f"[Get the full {rtype} here →]({repo_url})"
                    ),
                }], cp=None))
                return {
                    "success": True,
                    "summary": f"Lead magnet '{title[:40]}' published as free {rtype}",
                    "revenue_potential": 3.0,  # indirect: list building + upsell
                    "urls": [f"{repo_url}/blob/main/{filename}"],
                }
            return {"success": False, "summary": f"Lead magnet: could not push to {repo_name}"}

        except Exception as exc:
            logger.error("[IncomeLoop] lead_magnet: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_hf_spaces_demo(self) -> dict:
        """
        Publish a live Gradio AI demo to HuggingFace Spaces.
        HF Spaces is free, indexed by search engines, and has millions of AI community visitors.
        Requires: HF_TOKEN (HuggingFace API token) or GITHUB_TOKEN fallback.
        """
        try:
            from apps.core.llm.llm_client import complete_json
            hf_token = getattr(settings, "HF_TOKEN", None)
            owner    = getattr(settings, "GITHUB_USERNAME", None) or "Geremypolanco"

            # Generate demo concept
            niches = [
                ("AI Content Generator", "content-generator", "Generate SEO-optimized blog posts with AI"),
                ("Keyword Research Tool", "keyword-research", "Find profitable keywords for your niche"),
                ("Product Description Writer", "product-writer", "Write compelling product descriptions instantly"),
                ("Email Subject Line Optimizer", "email-optimizer", "A/B test email subject lines with AI scoring"),
                ("AI Summarizer", "ai-summarizer", "Summarize any article or document in seconds"),
                ("Headline Generator", "headline-gen", "Generate 10 viral headlines for any topic"),
                ("SEO Score Analyzer", "seo-analyzer", "Analyze and score your content for SEO"),
            ]
            niche_idx   = self._niche_idx % len(niches)
            demo_name, demo_slug, demo_desc = niches[niche_idx]
            space_name  = f"aria-{demo_slug}"

            # Generate the Gradio app code
            demo_data = await complete_json(
                f"""Create a simple but impressive Gradio demo for: {demo_name}
Description: {demo_desc}
Generate a Python Gradio app that:
1. Takes 1-2 text inputs
2. Processes them with a convincing AI simulation (pattern matching + templates)
3. Returns useful output
4. Looks professional with title, description, examples

Return JSON:
{{
  "app_code": "import gradio as gr\\n\\ndef process(text):\\n    # ... return result",
  "title": "{demo_name}",
  "description": "{demo_desc}",
  "examples": [["example input 1"], ["example input 2"]],
  "tagline": "30-word compelling tagline for this tool"
}}""",
                model="fast",
            )

            app_code    = demo_data.get("app_code", "")
            tagline     = demo_data.get("tagline", demo_desc)
            examples    = demo_data.get("examples", [])

            if not app_code:
                # Default minimal app
                app_code = f'''import gradio as gr

def process(text: str) -> str:
    """Simple {demo_name} demo."""
    if not text.strip():
        return "Please provide some input."
    words = text.split()
    return f"✅ Processed {{len(words)}} words. Result: {{text[:200]}}..."

demo = gr.Interface(
    fn=process,
    inputs=gr.Textbox(label="Input", placeholder="Enter your text here..."),
    outputs=gr.Textbox(label="Result"),
    title="{demo_name}",
    description="{demo_desc}",
    examples={json.dumps(examples[:3]) if examples else '[["Sample text to process"]]'},
)

if __name__ == "__main__":
    demo.launch()
'''

            readme_md = f"""---
title: {demo_name}
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 4.44.1
app_file: app.py
pinned: false
license: mit
short_description: {tagline[:100]}
---

# {demo_name}

{demo_desc}

## About

{tagline}

Built with ❤️ by [ARIA AI](https://github.com/{owner}/aria-ai) — autonomous AI business agent.

## Features

- ⚡ Instant results
- 🎯 AI-powered processing
- 🔓 Free to use

## Try it above!

Enter your text and see the magic happen.
"""

            requirements_txt = "gradio>=4.44.1\n"

            # Try to push to HuggingFace Spaces
            space_url = ""
            if hf_token:
                try:
                    import httpx as _hf_http
                    hf_api = "https://huggingface.co/api"
                    headers = {"Authorization": f"Bearer {hf_token}"}

                    async with _hf_http.AsyncClient(timeout=30) as _hf:
                        # Create space repo
                        cr = await _hf.post(
                            f"{hf_api}/repos/create",
                            json={"type": "space", "name": space_name, "sdk": "gradio", "private": False},
                            headers=headers,
                        )
                        repo_exists = cr.status_code in (200, 201, 409)  # 409 = already exists

                        if repo_exists:
                            import base64 as _b64

                            def _hf_commit_file(path: str, content: str) -> dict:
                                return {
                                    "path": path,
                                    "encoding": "base64",
                                    "content": _b64.b64encode(content.encode()).decode(),
                                }

                            commit_r = await _hf.post(
                                f"{hf_api}/{owner}/{space_name}/commit/main",
                                json={
                                    "summary": f"ARIA: deploy {demo_name} demo",
                                    "files": [
                                        _hf_commit_file("app.py", app_code),
                                        _hf_commit_file("requirements.txt", requirements_txt),
                                        _hf_commit_file("README.md", readme_md),
                                    ],
                                },
                                headers=headers,
                            )
                            if commit_r.status_code in (200, 201):
                                space_url = f"https://huggingface.co/spaces/{owner}/{space_name}"
                                logger.info("[IncomeLoop] HF Space deployed: %s", space_url)
                except Exception as hf_exc:
                    logger.debug("[IncomeLoop] HF Spaces API: %s", hf_exc)

            # GitHub fallback — create a demo repo with the Gradio code
            if not space_url and settings.GITHUB_TOKEN:
                from apps.core.tools.github_client import AriaGitHubClient
                import base64 as _b64
                gh    = AriaGitHubClient()
                repo  = f"aria-demo-{demo_slug}"
                desc  = f"{demo_name} — AI demo by ARIA"

                # Create repo (POST /user/repos)
                r_create = await gh._post("/user/repos", {
                    "name": repo, "description": desc,
                    "private": False, "auto_init": False,
                })
                if "html_url" in r_create or r_create.get("status") == 422:
                    # 422 may mean repo already exists
                    files = {
                        "app.py":           app_code,
                        "requirements.txt": requirements_txt,
                        "README.md":        readme_md,
                    }
                    pushed = []
                    for fname, fcontent in files.items():
                        fr = await gh.create_or_update_file(
                            owner=owner, repo=repo, path=fname,
                            content=_b64.b64encode(fcontent.encode()).decode(),
                            message=f"feat: {demo_name} AI demo",
                        )
                        if "content" in fr or fr.get("commit"):
                            pushed.append(fname)
                    if pushed:
                        space_url = f"https://github.com/{owner}/{repo}"

            if space_url:
                # Announce on blog
                asyncio.create_task(self._exec_github_blog([{
                    "title":       f"Free {demo_name}: Live AI Demo",
                    "slug":        f"free-{demo_slug}-ai-demo",
                    "description": tagline,
                    "content":     f"# Free {demo_name}\n\n{tagline}\n\n{demo_desc}\n\n[**Try the live demo →**]({space_url})\n\nBuilt with ARIA AI autonomous agent.\n",
                    "tags":        ["ai", "demo", "free-tool", "productivity"],
                }]))

                return {
                    "success": True,
                    "summary": f"HF Space deployed: {demo_name} — {space_url}",
                    "revenue_potential": 8.0,
                    "urls": [space_url],
                }

            return {
                "success": False,
                "summary": "hf_spaces_demo: add HF_TOKEN to fly secrets for HuggingFace deployment",
                "revenue_potential": 0,
                "urls": [],
            }

        except Exception as exc:
            logger.error("[IncomeLoop] hf_spaces_demo: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_viral_thread(self) -> dict:
        """
        Generate a viral Twitter/X thread on a trending topic + post via Zapier.
        Falls back to GitHub Gist for public visibility when Zapier isn't configured.
        """
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.web_tools import WebTools
            from apps.core.tools.zapier_connector import ZapierConnector

            ai = get_ai_client()
            if not ai:
                return {"success": False, "summary": "AI unavailable"}

            wt = WebTools()
            r  = await wt.search_web("viral twitter thread topics trending AI business 2025", num_results=5)
            topic = "AI is changing everything — here's what nobody tells you"
            if r.get("success") and r.get("results"):
                topic = r["results"][0].get("title", topic)[:100]

            thread = await ai.complete_json(
                system=(
                    "You write viral Twitter/X threads that get thousands of retweets. "
                    "Hook → story → insight → CTA. Output JSON only."
                ),
                user=f"""Write a viral Twitter/X thread about: "{topic}"

Rules:
- First tweet: POWERFUL hook (max 270 chars)
- Tweets 2-9: one insight per tweet, numbered (2/10, 3/10 etc.)
- Last tweet: strong CTA + link to ARIA portfolio

JSON:
{{
  "topic": "thread topic",
  "tweets": [
    "Hook tweet text (max 270 chars)",
    "2/10 insight...",
    "3/10 insight...",
    "4/10 insight...",
    "5/10 insight...",
    "6/10 insight...",
    "7/10 insight...",
    "8/10 insight...",
    "9/10 insight...",
    "10/10 CTA + https://github.com/Geremypolanco/aria-portfolio"
  ]
}}""",
                model=AIModel.CREATIVE,
                max_tokens=2000,
            )

            if not thread:
                return {"success": False, "summary": "AI failed to generate thread"}

            tweets   = thread.get("tweets", [])
            hook     = tweets[0][:280] if tweets else ""
            full_txt = "\n\n".join(f"[{i+1}] {t}" for i, t in enumerate(tweets))

            # Try Zapier first
            zc       = ZapierConnector()
            zapier_ok = False
            try:
                zr = await zc.dispatch_event("VIRAL_THREAD", {
                    "topic":       thread.get("topic", topic),
                    "hook":        hook,
                    "full_thread": full_txt,
                    "tweet_count": len(tweets),
                })
                zapier_ok = bool(zr and zr.get("success"))
            except Exception:
                pass

            # Fallback: publish as GitHub Gist (public, indexed by Google)
            if not zapier_ok and settings.GITHUB_TOKEN:
                try:
                    from apps.core.tools.github_client import AriaGitHubClient
                    import base64 as _b64
                    gh = AriaGitHubClient()
                    owner = settings.GITHUB_USERNAME or "Geremypolanco"
                    repo  = "aria-insights"
                    from datetime import datetime, timezone
                    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    slug  = thread.get("topic", "viral-thread")[:40].lower().replace(" ", "-")
                    filename = f"threads/{today}-{slug}.md"
                    content  = (
                        f"# Thread: {thread.get('topic', topic)}\n\n"
                        f"*Optimized for Twitter/X — {len(tweets)} tweets*\n\n"
                        + "\n\n---\n\n".join(
                            f"**Tweet {i+1}:**\n\n{t}" for i, t in enumerate(tweets)
                        )
                        + f"\n\n---\n\n*Thread by [ARIA AI](https://github.com/{owner}/aria-portfolio)*"
                    )
                    encoded = _b64.b64encode(content.encode()).decode()
                    file_r  = await gh._put(f"/repos/{owner}/{repo}/contents/{filename}", {
                        "message": f"thread: {thread.get('topic', topic)[:60]}",
                        "content": encoded,
                    })
                    if "error" not in file_r:
                        url = f"https://github.com/{owner}/{repo}/blob/main/{filename}"
                        return {
                            "success": True,
                            "summary": f"Viral thread published to GitHub (add ZAPIER_WEBHOOK_URL to auto-post to Twitter)",
                            "revenue_potential": 1.5,
                            "urls": [url],
                        }
                except Exception:
                    pass

            if zapier_ok:
                return {
                    "success": True,
                    "summary": f"Viral thread posted: '{topic[:50]}' ({len(tweets)} tweets via Zapier)",
                    "revenue_potential": 5.0,
                    "urls": [],
                }
            return {"success": False, "summary": "Viral thread: add ZAPIER_WEBHOOK_URL or GITHUB_TOKEN"}

        except Exception as exc:
            logger.error("[IncomeLoop] viral_thread: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    def check_credentials(self) -> dict:
        """Returns which income channels are configured vs. missing."""
        channels = {
            "ai_generation": {
                "active": bool(settings.HF_TOKEN or getattr(settings, "HF_API_KEY", None) or
                               getattr(settings, "GROQ_API_KEY", None) or
                               getattr(settings, "OPENAI_API_KEY", None)),
                "keys_needed": ["HF_TOKEN or GROQ_API_KEY or OPENAI_API_KEY"],
                "revenue_channels": ["content generation", "product descriptions", "ebooks"],
            },
            "github": {
                "active": bool(settings.GITHUB_TOKEN),
                "keys_needed": ["GITHUB_TOKEN"],
                "revenue_channels": ["open source projects", "SEO content", "free tools"],
            },
            "gumroad": {
                "active": bool(settings.GUMROAD_TOKEN),
                "keys_needed": ["GUMROAD_TOKEN"],
                "revenue_channels": ["ebook sales", "digital products", "courses", "templates"],
            },
            "lemonsqueezy": {
                "active": bool(getattr(settings, "LEMONSQUEEZY_API_KEY", None) and
                               getattr(settings, "LEMONSQUEEZY_STORE_ID", None)),
                "keys_needed": ["LEMONSQUEEZY_API_KEY", "LEMONSQUEEZY_STORE_ID"],
                "revenue_channels": ["digital products", "subscriptions", "lower fees than Gumroad (5%+$0.50)"],
            },
            "medium": {
                "active": bool(getattr(settings, "MEDIUM_TOKEN", None)),
                "keys_needed": ["MEDIUM_TOKEN"],
                "revenue_channels": ["paid articles", "Medium Partner Program"],
            },
            "devto": {
                "active": bool(getattr(settings, "DEVTO_API_KEY", None)),
                "keys_needed": ["DEVTO_API_KEY"],
                "revenue_channels": ["developer audience", "product launches"],
            },
            "hashnode": {
                "active": bool(getattr(settings, "HASHNODE_TOKEN", None) and
                               getattr(settings, "HASHNODE_PUBLICATION_ID", None)),
                "keys_needed": ["HASHNODE_TOKEN", "HASHNODE_PUBLICATION_ID"],
                "revenue_channels": ["tech blogging", "newsletter"],
            },
            "shopify": {
                "active": bool(getattr(settings, "SHOPIFY_ADMIN_TOKEN", None) and
                               getattr(settings, "SHOPIFY_URL", None)),
                "keys_needed": ["SHOPIFY_ADMIN_TOKEN", "SHOPIFY_URL"],
                "revenue_channels": ["e-commerce products", "digital downloads"],
            },
            "mailchimp": {
                "active": bool(getattr(settings, "MAILCHIMP_API_KEY", None)),
                "keys_needed": ["MAILCHIMP_API_KEY"],
                "revenue_channels": ["email campaigns", "newsletter monetization"],
            },
            "twitter": {
                "active": bool(getattr(settings, "TWITTER_API_KEY", None) and
                               getattr(settings, "TWITTER_ACCESS_TOKEN", None)),
                "keys_needed": ["TWITTER_API_KEY", "TWITTER_API_SECRET",
                                "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_TOKEN_SECRET"],
                "revenue_channels": ["product promotion", "audience building"],
            },
            "amazon_affiliate": {
                "active": bool(getattr(settings, "AMAZON_ASSOCIATE_TAG", None)),
                "keys_needed": ["AMAZON_ASSOCIATE_TAG"],
                "revenue_channels": ["product recommendations", "review articles", "tool lists"],
            },
            "discord": {
                "active": bool(getattr(settings, "DISCORD_WEBHOOK_URL", None)),
                "keys_needed": ["DISCORD_WEBHOOK_URL"],
                "revenue_channels": ["community building", "product announcements"],
            },
            "zapier": {
                "active": bool(getattr(settings, "ZAPIER_WEBHOOK_URL", None)),
                "keys_needed": ["ZAPIER_WEBHOOK_URL"],
                "revenue_channels": ["social automation", "multi-platform distribution", "viral threads"],
            },
            "huggingface": {
                "active": bool(getattr(settings, "HF_TOKEN", None)),
                "keys_needed": ["HF_TOKEN"],
                "revenue_channels": ["AI demo traffic", "HuggingFace Spaces", "millions of AI community visitors"],
            },
        }
        active   = {k: v for k, v in channels.items() if v["active"]}
        inactive = {k: v for k, v in channels.items() if not v["active"]}
        return {"active": active, "inactive": inactive}

    # ── Persistence ─────────────────────────────────────────────────────

    async def _load_niche_idx(self) -> int:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                val = await cache.get("aria:income:niche_idx")
                return int(val) if val else 0
        except Exception:
            pass
        return 0

    async def _save_niche_idx(self) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                await cache.set("aria:income:niche_idx", str(self._niche_idx), ttl_seconds=86400 * 90)
        except Exception:
            pass

    async def _save_result(self, result: CycleResult) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                data = json.dumps(asdict(result))
                await cache.rpush("aria:income:loop_history", data)
                await cache.ltrim("aria:income:loop_history", -200, -1)
                await cache.set("aria:income:last_cycle", data, ttl_seconds=86400 * 30)
                await cache.increment("aria:income:total_cycles")
                if result.success:
                    await cache.increment("aria:income:successful_cycles")
                # Per-strategy stats
                strat = result.strategy
                await cache.increment(f"aria:income:strategy:{strat}:runs")
                if result.success:
                    await cache.increment(f"aria:income:strategy:{strat}:successes")
                if result.revenue_potential > 0:
                    # Accumulate revenue — store as string, parse on read
                    raw_rev = await cache.get(f"aria:income:strategy:{strat}:revenue")
                    current_rev = float(raw_rev) if raw_rev else 0.0
                    await cache.set(
                        f"aria:income:strategy:{strat}:revenue",
                        str(current_rev + result.revenue_potential),
                        ttl_seconds=86400 * 90,
                    )
                # Track URLs count
                if result.urls_created:
                    for _ in result.urls_created:
                        await cache.increment("aria:income:total_urls_published")
        except Exception as exc:
            logger.warning("[IncomeLoop] Redis save: %s", exc)

    async def _save_error(self, error: str) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                await cache.rpush("aria:income:errors", json.dumps({
                    "error": error, "ts": datetime.now(timezone.utc).isoformat()
                }))
                await cache.ltrim("aria:income:errors", -50, -1)
        except Exception:
            pass

    # ── Notifications ───────────────────────────────────────────────────

    async def _notify_startup(self) -> None:
        """Send startup Telegram message and bootstrap portfolio + blog on first run."""
        try:
            await asyncio.sleep(5)  # wait for bot to be ready
            creds    = self.check_credentials()
            active   = list(creds.get("active", {}).keys())
            inactive = list(creds.get("inactive", {}).keys())
            from apps.core.tools.telegram_bot import get_bot
            owner = settings.GITHUB_USERNAME or "Geremypolanco"
            msg = (
                f"🤖 <b>ARIA Income Loop iniciado</b>\n"
                f"Canales activos: {', '.join(active) or 'ninguno configurado'}\n"
                f"Estrategias: {len(STRATEGIES)} rotando cada {INTERVAL_SECONDS//60} min\n"
            )
            if inactive:
                top = inactive[:3]
                msg += f"\n💡 Para activar más canales de ingresos:\n"
                if "gumroad" in top:
                    msg += "  • <code>fly secrets set GUMROAD_TOKEN=...</code> → venta de productos\n"
                if "devto" in top:
                    msg += "  • <code>fly secrets set DEVTO_API_KEY=...</code> → artículos técnicos\n"
                if "twitter" in top:
                    msg += "  • Twitter API keys → distribución social\n"
            await get_bot().notify_owner(msg)
        except Exception as exc:
            logger.debug("[IncomeLoop] startup notify: %s", exc)

        # Bootstrap portfolio on first startup (runs in background, won't block loop)
        asyncio.create_task(self._bootstrap_github_presence())

    async def _bootstrap_github_presence(self) -> None:
        """One-time: create/update aria-portfolio landing page on startup."""
        if not settings.GITHUB_TOKEN:
            return
        try:
            await asyncio.sleep(30)  # let the app fully start first
            # Only run if we haven't bootstrapped in the last 24 hours
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                last_bootstrap = await cache.get("aria:income:last_portfolio_bootstrap")
                if last_bootstrap and (time.time() - float(last_bootstrap)) < 86400:
                    return
            from apps.core.cognition.aria_mind import AriaMind
            mind = AriaMind()
            result = await mind._handle_tool_call("setup_portfolio", {})
            url = (result or {}).get("url", "")
            logger.info("[IncomeLoop] Portfolio bootstrapped: %s", url)
            if cache:
                await cache.set("aria:income:last_portfolio_bootstrap", str(time.time()), ttl_seconds=86400 * 90)
        except Exception as exc:
            logger.debug("[IncomeLoop] bootstrap portfolio: %s", exc)

    async def _notify_win(self, result: CycleResult) -> None:
        """Notify via Telegram when something was published or is high-value."""
        # Always notify for high-value wins ($10+)
        # For lower-value wins with URLs, throttle to once per 60 min to avoid spam
        high_value = result.revenue_potential >= 10
        has_urls   = bool(result.urls_created)

        if not high_value and not has_urls:
            return

        if not high_value and has_urls:
            # Rate-limit low-value URL notifications to once per hour
            try:
                from apps.core.memory.redis_client import get_cache
                cache = get_cache()
                if cache:
                    lock_key = "aria:income:last_url_notify"
                    last_ts  = await cache.get(lock_key)
                    if last_ts and (time.time() - float(last_ts)) < 3600:
                        return
                    await cache.set(lock_key, str(time.time()), ttl_seconds=3600)
            except Exception:
                pass

        try:
            from apps.core.tools.telegram_bot import get_bot
            urls_text = "\n".join(result.urls_created[:3])
            emoji = "💰" if high_value else ("📝" if result.strategy in ("github_publish", "content_pipeline", "affiliate_content") else "✅")
            msg = (
                f"{emoji} <b>ARIA publicó contenido nuevo</b>\n"
                f"Estrategia: {result.strategy}\n"
                f"Potencial: ${result.revenue_potential:.1f}\n"
                f"{result.summary[:200]}"
                + (f"\n\n{urls_text}" if urls_text else "")
            )
            bot = get_bot()
            await bot.notify_owner(msg)
        except Exception:
            pass

    # ── Status ──────────────────────────────────────────────────────────

    async def get_status_dict(self) -> dict:
        """Return structured status dict for API/dashboard consumption."""
        total_cycles    = 0
        success_count   = 0
        error_count     = 0
        last_cycle_data = {}
        recent_cycles   = []
        opportunities   = []
        total_revenue   = 0.0

        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                total_cycles  = int(await cache.get("aria:income:total_cycles") or 0)
                success_count = int(await cache.get("aria:income:successful_cycles") or 0)
                err_len       = await cache.llen("aria:income:errors")
                error_count   = err_len or 0

                last_raw = await cache.get("aria:income:last_cycle")
                if last_raw:
                    last_cycle_data = json.loads(last_raw) if isinstance(last_raw, str) else last_raw

                history_raw = await cache.lrange("aria:income:loop_history", -20, -1)
                for raw in reversed(history_raw or []):
                    try:
                        c = json.loads(raw) if isinstance(raw, str) else raw
                        if isinstance(c, dict):
                            recent_cycles.append(c)
                            total_revenue += c.get("revenue_potential", 0)
                    except Exception:
                        pass

                opp_raw = await cache.lrange("aria:income:opportunity_queue", 0, 9)
                for raw in (opp_raw or []):
                    try:
                        opportunities.append(json.loads(raw) if isinstance(raw, str) else raw)
                    except Exception:
                        pass
        except Exception:
            pass

        return {
            "running": self.is_running,
            "total_cycles": total_cycles,
            "successful_cycles": success_count,
            "errors": error_count,
            "success_rate": round(success_count / total_cycles * 100, 1) if total_cycles else 0,
            "total_revenue_potential": round(total_revenue, 2),
            "last_cycle": last_cycle_data or None,
            "recent_cycles": recent_cycles,
            "opportunities": opportunities,
            "opportunity_count": len(opportunities),
            "interval_minutes": INTERVAL_SECONDS // 60,
        }

    async def get_status(self) -> str:
        total_cycles = 0
        success_rate = 0.0
        last_cycle   = {}
        recent_urls  = []

        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                total_cycles  = int(await cache.get("aria:income:total_cycles") or 0)
                success_count = int(await cache.get("aria:income:successful_cycles") or 0)
                success_rate  = (success_count / total_cycles * 100) if total_cycles else 0

                last_raw = await cache.get("aria:income:last_cycle")
                if last_raw:
                    last_cycle = json.loads(last_raw) if isinstance(last_raw, str) else last_raw

                history_raw = await cache.lrange("aria:income:loop_history", -10, -1)
                for raw in (history_raw or []):
                    try:
                        cycle = json.loads(raw) if isinstance(raw, str) else raw
                        if isinstance(cycle, dict):
                            recent_urls.extend(cycle.get("urls_created", []))
                    except Exception:
                        pass
        except Exception:
            pass

        next_run = INTERVAL_SECONDS - ((self._cycle * INTERVAL_SECONDS) % INTERVAL_SECONDS) if self._cycle else FIRST_RUN_DELAY
        status_label = "🟢 RUNNING" if self.is_running else "🔴 STOPPED"

        lines = [
            f"**ARIA Income Loop — {status_label}**",
            f"━━━━━━━━━━━━━━━━━━━━━━",
            f"Cycles completed: {total_cycles}",
            f"Success rate: {success_rate:.1f}%",
            f"Interval: every {INTERVAL_SECONDS//60} minutes",
            f"",
            f"**Last cycle:**",
        ]
        if last_cycle:
            lines += [
                f"  Strategy: {last_cycle.get('strategy','?')}",
                f"  Success: {'✅' if last_cycle.get('success') else '❌'}",
                f"  Summary: {last_cycle.get('summary','')[:100]}",
                f"  Revenue potential: ${last_cycle.get('revenue_potential',0):.0f}",
                f"  Time: {last_cycle.get('elapsed_seconds',0)}s",
            ]
        else:
            lines.append("  (no cycles yet)")

        if recent_urls:
            unique_urls = list(dict.fromkeys(u for u in recent_urls if u))[:5]
            if unique_urls:
                lines.append("")
                lines.append("**Recent URLs created:**")
                for u in unique_urls:
                    lines.append(f"  • {u}")

        lines += [
            "",
            f"**Strategies in rotation:**",
        ]
        for name, weight in STRATEGIES:
            lines.append(f"  {weight}% — {name}")

        return "\n".join(lines)

    async def _register_product(self, result: CycleResult) -> None:
        """Persist a newly published product/URL to the product catalog in Redis."""
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if not cache:
                return
            entry = {
                "title":     result.summary[:120],
                "strategy":  result.strategy,
                "urls":      result.urls_created,
                "revenue":   result.revenue_potential,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await cache.rpush("aria:products:catalog", json.dumps(entry))
            await cache.ltrim("aria:products:catalog", -500, -1)
        except Exception as exc:
            logger.debug("[IncomeLoop] register_product: %s", exc)

    async def get_product_catalog(self, limit: int = 20) -> str:
        """Return a formatted catalog of all products/URLs published by ARIA."""
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if not cache:
                return "⚠️ Redis no disponible — sin catálogo de productos."

            raw_items = await cache.lrange("aria:products:catalog", -limit, -1)
            if not raw_items:
                return (
                    "📦 <b>Catálogo de Productos ARIA</b>\n\n"
                    "⏳ Aún no hay productos registrados.\n"
                    "El income loop irá llenando el catálogo con cada ciclo exitoso."
                )

            items = []
            for raw in reversed(raw_items or []):
                try:
                    items.append(json.loads(raw) if isinstance(raw, str) else raw)
                except Exception:
                    pass

            lines = [
                "📦 <b>Catálogo de Productos ARIA</b>",
                f"<i>{len(items)} productos/publicaciones</i>",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            ]
            for i, item in enumerate(items[:limit], 1):
                title   = item.get("title", "")[:80]
                strat   = item.get("strategy", "")
                revenue = item.get("revenue", 0)
                urls    = item.get("urls", [])
                date    = item.get("created_at", "")[:10]
                lines.append(f"\n<b>{i}. {title}</b>")
                lines.append(f"   📅 {date}  |  📊 {strat}  |  💰 ${revenue:.0f} potencial")
                for url in urls[:2]:
                    if url:
                        lines.append(f"   🔗 {url}")

            total_rev = sum(i.get("revenue", 0) for i in items)
            lines += [
                "",
                f"<b>Revenue potencial acumulado: ${total_rev:.2f}</b>",
                f"<i>Actualizado automáticamente en cada ciclo exitoso</i>",
            ]
            return "\n".join(lines)

        except Exception as exc:
            logger.error("[IncomeLoop] product_catalog: %s", exc)
            return f"⚠️ Error: {exc}"

    async def get_analytics_report(self) -> str:
        """Return a per-strategy performance breakdown from Redis analytics."""
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if not cache:
                return "⚠️ Redis no disponible — sin datos de analíticas."

            total_cycles   = int(await cache.get("aria:income:total_cycles") or 0)
            success_cycles = int(await cache.get("aria:income:successful_cycles") or 0)
            total_urls     = int(await cache.get("aria:income:total_urls_published") or 0)
            success_rate   = (success_cycles / total_cycles * 100) if total_cycles else 0

            rows: list[tuple[str, int, int, float, float]] = []
            total_tracked_rev = 0.0
            for name, weight in STRATEGIES:
                runs  = int(await cache.get(f"aria:income:strategy:{name}:runs") or 0)
                wins  = int(await cache.get(f"aria:income:strategy:{name}:successes") or 0)
                raw_r = await cache.get(f"aria:income:strategy:{name}:revenue")
                rev   = float(raw_r) if raw_r else 0.0
                total_tracked_rev += rev
                rows.append((name, runs, wins, rev, weight))

            # Sort by revenue desc, then runs desc
            rows.sort(key=lambda r: (-r[3], -r[1]))

            lines = [
                "📊 <b>ARIA — Reporte de Analíticas por Estrategia</b>",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"Ciclos totales: <b>{total_cycles}</b>  |  Éxitos: <b>{success_cycles}</b>  ({success_rate:.1f}%)",
                f"URLs publicadas: <b>{total_urls}</b>  |  Revenue acumulado: <b>${total_tracked_rev:.2f}</b>",
                "",
                "<b>Estrategia              Runs  Win%  Revenue  Peso</b>",
            ]
            for (name, runs, wins, rev, weight) in rows:
                win_pct = (wins / runs * 100) if runs else 0
                bar     = "█" * min(int(win_pct / 10), 10)
                lines.append(
                    f"<code>{name:<22}</code>  {runs:>3}  {win_pct:>4.0f}%  ${rev:>7.2f}  {weight}%"
                )

            if total_cycles == 0:
                lines += ["", "⏳ Sin datos aún — el loop inicia en unos minutos."]
            else:
                best = rows[0] if rows else None
                if best and best[1] > 0:
                    lines += ["", f"🏆 Mejor estrategia: <b>{best[0]}</b> (${best[3]:.2f} revenue)"]

            lines += [
                "",
                f"<i>Datos en tiempo real desde Redis. Ciclo cada {INTERVAL_SECONDS//60} min.</i>",
            ]
            return "\n".join(lines)

        except Exception as exc:
            logger.error("[IncomeLoop] analytics_report: %s", exc)
            return f"⚠️ Error al generar reporte: {exc}"


# ── Singleton ──────────────────────────────────────────────────────

_loop: Optional[IncomeLoop] = None

def get_income_loop() -> IncomeLoop:
    global _loop
    if _loop is None:
        _loop = IncomeLoop()
    return _loop
