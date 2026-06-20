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
    ("content_pipeline",         5),
    ("niche_rotator",            4),
    ("product_factory",          5),
    ("course_builder",           3),   # mini-course with syllabus + pricing (avg $79-$127/sale)
    ("affiliate_network",        3),   # build own affiliate program, recruit promoters
    ("opportunity_scan",         5),
    ("github_publish",           5),   # works with only GITHUB_TOKEN — always active
    ("content_repurposer",       4),   # 3x reach: LinkedIn + Twitter thread + email from 1 post
    ("micro_saas",               4),   # full micro-SaaS product launch: README + API docs + pricing
    ("shopify_listing",          2),
    ("email_campaign",           2),
    ("affiliate_content",        4),   # review/comparison articles with affiliate links
    ("ebook_factory",            4),
    ("lead_magnet",              3),   # free resource funnel → email capture → upsell
    ("hf_spaces_demo",           2),   # live AI demo on HuggingFace Spaces (free, massive community)
    ("seo_optimizer",            4),   # improve existing posts for compounding organic traffic
    ("gist_blitz",               2),   # code snippet Gists with product CTAs (dev discovery)
    ("product_bundle",           4),   # bundle 2-3 existing products at a discount → higher AOV
    ("waitlist_builder",         2),   # waitlist landing page → email capture → launch pipeline
    ("challenge_campaign",       4),   # 7-day challenge series → sustained traffic + lead capture
    ("partner_outreach",         2),   # B2B collaboration pitches → cross-promotion + co-sells
    ("newsletter_issue",         4),   # full newsletter edition → recurring reader monetization
    ("job_board_listing",        2),   # B2B service listings → consulting leads
    ("github_sponsors_setup",    1),   # passive income via GitHub Sponsors + FUNDING.yml
    ("social_blitz",             1),
    ("premium_offer",            1),
    ("viral_thread",             1),   # Twitter/X thread optimized for virality
    ("twitter_thread",           3),   # direct Twitter API thread via api_publisher (real posts)
    ("linkedin_post",            3),   # direct LinkedIn API post via api_publisher (real posts)
    ("reddit_organic",           3),   # subreddit posts → massive organic traffic → affiliate rev
    ("stripe_checkout",          3),   # real Stripe payment link for instant revenue
    ("tiktok_script",            3),   # TikTok/Reels/YouTube Shorts viral scripts → massive reach
    ("linkedin_outreach",        2),   # B2B prospect messages → consulting/partnership leads
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
        self._running         = False
        self._task            = None
        self._cycle           = 0
        self._niche_idx       = 0    # Round-robin through niche catalog (loaded from Redis in first cycle)
        self._adaptive_weights: dict[str, float] = {}   # updated from Redis every 10 cycles
        self._weights_refresh_cycle = 0

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

        # Refresh adaptive weights every 10 cycles
        if self._cycle - self._weights_refresh_cycle >= 10:
            self._weights_refresh_cycle = self._cycle
            asyncio.create_task(self._refresh_adaptive_weights())

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
        """Weighted random strategy selection — uses adaptive weights when available."""
        names   = [s[0] for s in STRATEGIES]
        if self._adaptive_weights:
            # Merge: adaptive weights override defaults where available
            weights = [self._adaptive_weights.get(n, w) for n, w in STRATEGIES]
        else:
            weights = [s[1] for s in STRATEGIES]
        return random.choices(names, weights=weights, k=1)[0]

    async def _refresh_adaptive_weights(self) -> None:
        """Load optimizer weights from Redis (written by strategy_optimizer objective)."""
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                raw = await cache.get("aria:income:adaptive_weights")
                if raw and isinstance(raw, dict):
                    self._adaptive_weights = {k: float(v) for k, v in raw.items()}
                    logger.info("[IncomeLoop] Adaptive weights loaded (%d strategies)", len(self._adaptive_weights))
        except Exception:
            pass

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
        elif strategy == "seo_optimizer":
            return await self._exec_seo_optimizer()
        elif strategy == "content_repurposer":
            return await self._exec_content_repurposer()
        elif strategy == "course_builder":
            return await self._exec_course_builder()
        elif strategy == "affiliate_network":
            return await self._exec_affiliate_network_builder()
        elif strategy == "micro_saas":
            return await self._exec_micro_saas()
        elif strategy == "gist_blitz":
            return await self._exec_gist_blitz()
        elif strategy == "github_sponsors_setup":
            return await self._exec_github_sponsors_setup()
        elif strategy == "product_bundle":
            return await self._exec_product_bundle()
        elif strategy == "waitlist_builder":
            return await self._exec_waitlist_builder()
        elif strategy == "challenge_campaign":
            return await self._exec_challenge_campaign()
        elif strategy == "partner_outreach":
            return await self._exec_partner_outreach()
        elif strategy == "newsletter_issue":
            return await self._exec_newsletter_issue()
        elif strategy == "job_board_listing":
            return await self._exec_job_board_listing()
        elif strategy == "viral_thread":
            return await self._exec_viral_thread()
        elif strategy == "twitter_thread":
            return await self._exec_twitter_thread()
        elif strategy == "linkedin_post":
            return await self._exec_linkedin_post()
        elif strategy == "reddit_organic":
            return await self._exec_reddit_organic()
        elif strategy == "stripe_checkout":
            return await self._exec_stripe_checkout()
        elif strategy == "tiktok_script":
            return await self._exec_tiktok_script()
        elif strategy == "linkedin_outreach":
            return await self._exec_linkedin_outreach()
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

    async def _exec_micro_saas(self) -> dict:
        """
        Create a micro-SaaS concept as a GitHub repo with full README, pricing table,
        API docs, and a demo script. Positions ARIA as a software company with
        licensable products. GitHub SEO drives organic discovery.
        Requires: GITHUB_TOKEN
        """
        if not settings.GITHUB_TOKEN:
            return {"success": False, "summary": "micro_saas: needs GITHUB_TOKEN"}
        try:
            from apps.core.llm.llm_client import complete_json
            from apps.core.tools.github_client import AriaGitHubClient
            import base64 as _b64

            gh    = AriaGitHubClient()
            owner = settings.GITHUB_USERNAME or "Geremypolanco"

            saas_concepts = [
                ("AI Email Writer API", "email-writer-api", "REST API that writes personalized cold emails using AI"),
                ("Content Calendar AI", "content-calendar-ai", "Auto-generate 30-day content calendar for any brand"),
                ("SEO Audit Bot", "seo-audit-bot", "Automated SEO scoring and fix recommendations via API"),
                ("AI Product Description Generator", "product-desc-gen", "Generate Shopify/Amazon product descriptions at scale"),
                ("Competitor Monitor", "competitor-monitor", "Track competitor pricing, content, and social updates daily"),
                ("AI Blog Factory", "blog-factory-api", "Generate SEO blog posts programmatically via REST API"),
                ("Lead Qualifier AI", "lead-qualifier-ai", "Score and qualify leads using behavior + demographics"),
            ]

            concept = saas_concepts[self._niche_idx % len(saas_concepts)]
            name, slug, desc = concept

            saas_data = await complete_json(
                f"""Create a compelling micro-SaaS product concept.

Product: {name}
Slug: {slug}
Description: {desc}

Generate complete product documentation. Return JSON:
{{
  "tagline": "one-line value proposition (under 80 chars)",
  "pain_points": ["problem 1", "problem 2", "problem 3"],
  "features": ["feature 1", "feature 2", "feature 3", "feature 4"],
  "pricing_tiers": [
    {{"name": "Starter", "price_monthly": 29, "limits": "1,000 requests/month", "features": ["core feature 1"]}},
    {{"name": "Pro", "price_monthly": 79, "limits": "10,000 requests/month", "features": ["everything in Starter", "feature 2"]}},
    {{"name": "Enterprise", "price_monthly": 299, "limits": "Unlimited", "features": ["everything in Pro", "SLA", "dedicated support"]}}
  ],
  "demo_code": "import requests\\n\\n# Quick start demo\\nresponse = requests.post('https://api.example.com/v1/generate', ...)\\nprint(response.json())",
  "use_cases": ["use case 1", "use case 2"],
  "target_customers": "who buys this"
}}""",
                model="fast",
            )

            tagline     = saas_data.get("tagline", desc)
            features    = saas_data.get("features", [])
            pricing     = saas_data.get("pricing_tiers", [])
            pain_points = saas_data.get("pain_points", [])
            demo_code   = saas_data.get("demo_code", "")
            use_cases   = saas_data.get("use_cases", [])
            target      = saas_data.get("target_customers", "")

            # Build pricing table markdown
            pricing_md = "| Plan | Price | Requests | Features |\n|------|-------|----------|----------|\n"
            for tier in pricing:
                feats = ", ".join(tier.get("features", [])[:2])
                pricing_md += f"| {tier.get('name','')} | ${tier.get('price_monthly',0)}/mo | {tier.get('limits','')} | {feats} |\n"

            readme = f"""# {name}

> {tagline}

[![GitHub Stars](https://img.shields.io/github/stars/{owner}/{slug}?style=social)](https://github.com/{owner}/{slug})
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 🎯 The Problem

{chr(10).join(f'- {p}' for p in pain_points)}

## ✨ Features

{chr(10).join(f'- {f}' for f in features)}

## 💰 Pricing

{pricing_md}

## 🚀 Quick Start

```python
{demo_code}
```

## 📦 Use Cases

{chr(10).join(f'- {u}' for u in use_cases)}

## 👥 Who Is This For?

{target}

## 🔗 Links

- [Documentation](https://github.com/{owner}/{slug}/wiki)
- [API Reference](https://github.com/{owner}/{slug}/blob/main/API.md)
- [Portfolio](https://github.com/{owner}/aria-portfolio)

---

*Built by [ARIA AI](https://github.com/{owner}/aria-ai) — autonomous business intelligence*

⭐ **Star this repo** if it solves a problem you have!
"""

            api_md = f"""# {name} — API Reference

## Base URL

```
https://api.{slug}.io/v1
```

## Authentication

All requests require an API key in the `Authorization` header:

```
Authorization: Bearer YOUR_API_KEY
```

## Endpoints

### POST /generate

Generate output using AI.

**Request:**
```json
{{
  "input": "your text here",
  "options": {{
    "tone": "professional",
    "length": "medium"
  }}
}}
```

**Response:**
```json
{{
  "result": "generated output",
  "tokens_used": 150,
  "cost_usd": 0.0015
}}
```

## Rate Limits

| Plan | Requests/month | RPM |
|------|---------------|-----|
| Starter | 1,000 | 10 |
| Pro | 10,000 | 60 |
| Enterprise | Unlimited | 1,000 |

## SDKs

- Python: `pip install {slug}-python`
- Node.js: `npm install {slug}-client`
"""

            repo_name = slug
            r_create = await gh._post("/user/repos", {
                "name": repo_name,
                "description": f"{tagline} | {desc}",
                "private": False, "auto_init": False,
                "topics": ["ai", "saas", "api", "automation"],
            })

            if "html_url" in r_create or r_create.get("status") == 422:
                files = {
                    "README.md":  readme,
                    "API.md":     api_md,
                }
                for fname, content in files.items():
                    await gh._put(f"/repos/{owner}/{repo_name}/contents/{fname}", {
                        "message": f"feat: {name} micro-SaaS launch",
                        "content": _b64.b64encode(content.encode()).decode(),
                    })

                repo_url = f"https://github.com/{owner}/{repo_name}"
                logger.info("[IncomeLoop] Micro-SaaS published: %s", repo_url)

                # Announce on blog
                asyncio.create_task(self._exec_github_blog([{
                    "title": f"Introducing {name}: {tagline}",
                    "slug": f"introducing-{slug}",
                    "description": tagline,
                    "content": f"# Introducing {name}\n\n{tagline}\n\n{desc}\n\n[View on GitHub →]({repo_url})\n\n## Pricing\n\n{pricing_md}",
                    "tags": ["saas", "product", "ai", "launch"],
                }]))

                min_price = min(t.get("price_monthly", 0) for t in pricing) if pricing else 0
                return {
                    "success": True,
                    "summary": f"Micro-SaaS '{name}' launched at ${min_price}/mo starting — {repo_url}",
                    "revenue_potential": float(min_price),
                    "urls": [repo_url],
                }

            return {"success": False, "summary": "micro_saas: could not create repo"}

        except Exception as exc:
            logger.error("[IncomeLoop] micro_saas: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_affiliate_network_builder(self) -> dict:
        """
        Create a public affiliate program for ARIA's products on GitHub.
        Publishes an AFFILIATE.md and a referral tracking repo that:
        - Explains commission structure (30% recurring)
        - Lists all ARIA products available for promotion
        - Provides referral link generation instructions
        - Positions ARIA as a vendor with a real partner program
        Requires: GITHUB_TOKEN
        """
        if not settings.GITHUB_TOKEN:
            return {"success": False, "summary": "affiliate_network: needs GITHUB_TOKEN"}
        try:
            from apps.core.llm.llm_client import complete_json
            from apps.core.tools.github_client import AriaGitHubClient
            from apps.core.memory.redis_client import get_cache
            import base64 as _b64

            gh    = AriaGitHubClient()
            owner = settings.GITHUB_USERNAME or "Geremypolanco"
            cache = get_cache()

            # Load product catalog for the affiliate program
            catalog_items: list = []
            if cache:
                raw_items = await cache.lrange("aria:products:catalog", -20, -1)
                for raw in (raw_items or []):
                    try:
                        item = json.loads(raw) if isinstance(raw, str) else raw
                        if item.get("urls"):
                            catalog_items.append(item)
                    except Exception:
                        pass

            product_list_md = ""
            if catalog_items:
                product_list_md = "## 🛒 Products Available for Promotion\n\n"
                for item in catalog_items[-8:]:
                    title   = item.get("title", "")[:70]
                    rev     = item.get("revenue", 0)
                    urls    = item.get("urls", [])
                    link    = urls[0] if urls else ""
                    commission = round(rev * 0.30, 2)
                    product_list_md += f"| [{title}]({link}) | ${rev:.0f} | ${commission:.2f}/sale |\n"
                product_list_md = "| Product | Price | Your Commission |\n|---------|-------|-----------------|\n" + product_list_md
            else:
                product_list_md = "*(Products will be listed here as they are created)*"

            affiliate_md = f"""# ARIA AI — Affiliate Partner Program

> Earn 30% commission on every sale you refer. Recurring commissions on subscriptions.

## 💰 Commission Structure

| Tier | Commission | Threshold |
|------|-----------|-----------|
| **Starter** | 20% per sale | $0 — first sale |
| **Pro** | 30% per sale | $500 referred |
| **Elite** | 40% per sale | $2,000 referred |

All commissions are **recurring** on subscription products.
One-time products pay on first purchase.

## 🚀 How to Join

1. **Star this repo** to show intent
2. Open an **Issue** with title: `[AFFILIATE] Your Name — Your Channel`
3. Describe your audience (blog, YouTube, newsletter, Twitter, etc.)
4. We'll send you a personalized referral link within 24h

## 📊 Promotional Materials

We provide:
- ✅ Product descriptions and screenshots
- ✅ Email swipe copy (3 variations per product)
- ✅ Social media captions
- ✅ Video script outlines
- ✅ Banner images

## {product_list_md}

## 💳 Payment

- Minimum payout: **$50**
- Payment method: PayPal, Wise, or crypto
- Payment cycle: Monthly (1st of each month)
- Cookie duration: **90 days**

## 📧 Contact

Open an issue or reach out at the portfolio: https://github.com/{owner}/aria-portfolio

---

*Program managed by [ARIA AI](https://github.com/{owner}/aria-ai) — autonomous AI business platform*

⭐ **Star this repo** to stay updated on new products and commission increases!
"""

            # Add AFFILIATE.md to the portfolio repo too
            repos_to_update = ["aria-portfolio", "aria-ai"]
            published_urls  = []

            # Create dedicated affiliate program repo
            affiliate_repo = "aria-affiliate-program"
            r_create = await gh._post("/user/repos", {
                "name": affiliate_repo,
                "description": "ARIA AI Affiliate Program — Earn 30% commissions promoting AI products",
                "private": False, "auto_init": False,
            })
            if "html_url" in r_create or r_create.get("status") == 422:
                await gh._put(f"/repos/{owner}/{affiliate_repo}/contents/README.md", {
                    "message": "launch: ARIA affiliate program",
                    "content": _b64.b64encode(affiliate_md.encode()).decode(),
                })
                published_urls.append(f"https://github.com/{owner}/{affiliate_repo}")

            # Also put AFFILIATE.md in main aria-ai repo
            for repo in repos_to_update:
                try:
                    existing = await gh._get(f"/repos/{owner}/{repo}/contents/AFFILIATE.md")
                    sha = existing.get("sha") if "error" not in existing else None
                    body: dict = {
                        "message": "chore: add affiliate program link",
                        "content": _b64.b64encode(affiliate_md.encode()).decode(),
                    }
                    if sha:
                        body["sha"] = sha
                    await gh._put(f"/repos/{owner}/{repo}/contents/AFFILIATE.md", body)
                except Exception:
                    pass

            if published_urls:
                logger.info("[IncomeLoop] Affiliate program published: %s", published_urls[0])
                return {
                    "success": True,
                    "summary": f"Affiliate program launched: 30% commissions, {len(catalog_items)} products available",
                    "revenue_potential": 15.0,
                    "urls": published_urls,
                }
            return {"success": False, "summary": "affiliate_network: could not publish"}

        except Exception as exc:
            logger.error("[IncomeLoop] affiliate_network: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_course_builder(self) -> dict:
        """
        Build a complete mini-course outline and publish it as a GitHub repo.
        Includes: course overview, module breakdowns, pricing, sales page copy.
        Sellable on Gumroad/LemonSqueezy. GitHub version acts as a free preview.
        Requires: GITHUB_TOKEN
        """
        if not settings.GITHUB_TOKEN:
            return {"success": False, "summary": "course_builder: needs GITHUB_TOKEN"}
        try:
            from apps.core.llm.llm_client import complete_json
            from apps.core.tools.github_client import AriaGitHubClient
            import base64 as _b64

            gh    = AriaGitHubClient()
            owner = settings.GITHUB_USERNAME or "Geremypolanco"

            course_topics = [
                ("AI Automation for Business Owners", "ai-automation-course", 97),
                ("Build Your First SaaS in 30 Days", "saas-30days-course", 127),
                ("Freelancing with AI Tools", "ai-freelance-course", 79),
                ("SEO Mastery with AI in 2025", "ai-seo-course", 97),
                ("No-Code AI Business Blueprint", "nocode-ai-course", 89),
                ("Digital Products That Sell Themselves", "digital-products-course", 67),
                ("Content Marketing Machine: AI Edition", "ai-content-course", 87),
            ]

            pick = course_topics[self._niche_idx % len(course_topics)]
            title, slug, price = pick

            course_data = await complete_json(
                f"""Create a complete mini-course for: "{title}"
Price: ${price}

Return JSON:
{{
  "subtitle": "compelling subtitle under 80 chars",
  "promise": "the ONE transformation this course delivers (under 30 words)",
  "target_audience": "who exactly should buy this",
  "modules": [
    {{"number": 1, "title": "Module 1 Title", "duration": "45 min", "lessons": ["Lesson 1.1", "Lesson 1.2", "Lesson 1.3"]}},
    {{"number": 2, "title": "Module 2 Title", "duration": "60 min", "lessons": ["Lesson 2.1", "Lesson 2.2"]}},
    {{"number": 3, "title": "Module 3 Title", "duration": "50 min", "lessons": ["Lesson 3.1", "Lesson 3.2", "Lesson 3.3"]}},
    {{"number": 4, "title": "Module 4 Title", "duration": "45 min", "lessons": ["Lesson 4.1", "Lesson 4.2"]}},
    {{"number": 5, "title": "Module 5 Title", "duration": "30 min", "lessons": ["Lesson 5.1", "Lesson 5.2"]}}
  ],
  "bonuses": ["Bonus 1: description", "Bonus 2: description"],
  "testimonial_placeholder": "This course changed the way I... [Student Name, Role]",
  "faq": [
    {{"q": "How long do I have access?", "a": "Lifetime access with all future updates."}},
    {{"q": "Is there a money-back guarantee?", "a": "Yes, 30-day full refund, no questions asked."}}
  ]
}}""",
                model="fast",
            )

            subtitle   = course_data.get("subtitle", "")
            promise    = course_data.get("promise", "")
            audience   = course_data.get("target_audience", "")
            modules    = course_data.get("modules", [])
            bonuses    = course_data.get("bonuses", [])
            faq        = course_data.get("faq", [])

            total_duration = sum(
                int(m.get("duration", "0 min").split()[0]) for m in modules if m.get("duration")
            )

            # Course syllabus markdown
            modules_md = ""
            for m in modules:
                lessons = "\n".join(f"  - {l}" for l in m.get("lessons", []))
                modules_md += f"\n### Module {m.get('number', '')}: {m.get('title', '')}\n⏱ {m.get('duration', '')}\n\n{lessons}\n"

            faq_md = "\n".join(f"**Q: {f['q']}**\n\nA: {f['a']}\n" for f in faq)
            bonuses_md = "\n".join(f"- 🎁 {b}" for b in bonuses)

            readme = f"""# {title}

### {subtitle}

> **{promise}**

[![Price](https://img.shields.io/badge/Price-${price}-brightgreen)](https://github.com/{owner}/aria-portfolio)
[![Duration](https://img.shields.io/badge/Duration-{total_duration}%20min-blue)](#curriculum)
[![Modules](https://img.shields.io/badge/Modules-{len(modules)}-orange)](#curriculum)

---

## 👥 Who Is This For?

{audience}

---

## 📚 Curriculum ({len(modules)} modules · {total_duration} min)
{modules_md}

---

## 🎁 Bonuses

{bonuses_md}

---

## 💰 Investment

**${price}** (one-time) — Lifetime access + all future updates

[**→ Enroll Now**](https://github.com/{owner}/aria-portfolio)

---

## ❓ FAQ

{faq_md}

---

*Course content generated by [ARIA AI](https://github.com/{owner}/aria-ai) — autonomous business agent*

⭐ **Star this repo** to stay updated on course launches!
"""

            repo_name = slug
            r_create = await gh._post("/user/repos", {
                "name": repo_name,
                "description": f"{subtitle} | {promise}",
                "private": False, "auto_init": False,
            })

            if "html_url" in r_create or r_create.get("status") == 422:
                await gh._put(f"/repos/{owner}/{repo_name}/contents/README.md", {
                    "message": f"launch: {title} course",
                    "content": _b64.b64encode(readme.encode()).decode(),
                })
                repo_url = f"https://github.com/{owner}/{repo_name}"
                logger.info("[IncomeLoop] Course published: %s", repo_url)

                # Try to sell on Gumroad/LemonSqueezy
                sale_url = repo_url
                try:
                    if settings.GUMROAD_TOKEN:
                        from apps.core.tools.gumroad_tools import GumroadTools
                        gt = GumroadTools()
                        gr = await gt.create_product(
                            name=title, description=f"{promise}\n\n{subtitle}",
                            price_cents=price * 100,
                        )
                        if gr.get("success") and gr.get("url"):
                            sale_url = gr["url"]
                    elif getattr(settings, "LEMONSQUEEZY_API_KEY", None):
                        from apps.core.tools.lemon_squeezy_tools import LemonSqueezyTools
                        ls = LemonSqueezyTools()
                        lr = await ls.create_product(
                            name=title, description=promise,
                            price_cents=price * 100,
                        )
                        if lr.get("success") and lr.get("url"):
                            sale_url = lr["url"]
                except Exception:
                    pass

                return {
                    "success": True,
                    "summary": f"Course '{title}' at ${price} — {sale_url}",
                    "revenue_potential": float(price),
                    "urls": [sale_url],
                }

            return {"success": False, "summary": "course_builder: could not create repo"}

        except Exception as exc:
            logger.error("[IncomeLoop] course_builder: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_gist_blitz(self) -> dict:
        """
        Create 3 useful code snippets as public GitHub Gists.
        Each Gist includes a product CTA comment linking back to ARIA's tools.
        Gists appear in GitHub search, Google snippets, and developer feeds.
        Requires: GITHUB_TOKEN
        """
        if not settings.GITHUB_TOKEN:
            return {"success": False, "summary": "gist_blitz: needs GITHUB_TOKEN"}
        try:
            from apps.core.llm.llm_client import complete_json
            import httpx as _hx

            owner = settings.GITHUB_USERNAME or "Geremypolanco"
            portfolio_url = f"https://github.com/{owner}/aria-portfolio"

            topics = [
                ("python-productivity", "Python", "10 Python one-liners that will save you hours every week"),
                ("ai-prompts-cheatsheet", "Markdown", "The ultimate AI prompts cheatsheet for developers (2025)"),
                ("bash-automation", "Shell", "20 Bash aliases every developer should have"),
                ("async-patterns", "Python", "Async/await patterns every Python dev should know"),
                ("git-shortcuts", "Shell", "Git commands that make you look like a senior developer"),
            ]
            # Pick 2 topics randomly
            picks = random.sample(topics, min(2, len(topics)))

            published_gist_urls: list[str] = []
            gh_token = settings.GITHUB_TOKEN

            for slug, lang, topic in picks:
                snippet_data = await complete_json(
                    f"""Create a highly useful, complete code snippet for this topic:
"{topic}"

Requirements:
- Language: {lang}
- Length: 30-80 lines (complete and useful, not truncated)
- Practical, copy-paste ready
- Professional but accessible
- Start with a 3-line comment header: title, description, by ARIA AI

Return JSON:
{{
  "filename": "{slug}.{('py' if lang=='Python' else 'sh' if lang=='Shell' else 'md')}",
  "code": "# full code here",
  "description": "one-line description for the Gist"
}}""",
                    model="fast",
                )
                code     = snippet_data.get("code", "")
                filename = snippet_data.get("filename", f"{slug}.txt")
                desc     = snippet_data.get("description", topic)

                if not code:
                    continue

                # Append CTA comment at the end
                cta_sep  = "#" if lang in ("Python", "Shell") else "---"
                cta_lang = "# " if lang != "Markdown" else ""
                cta = (
                    f"\n\n{cta_sep}{cta_sep}{cta_sep}\n"
                    f"{cta_lang}🤖 Generated by ARIA AI — autonomous business agent\n"
                    f"{cta_lang}More tools & resources: {portfolio_url}\n"
                    f"{cta_lang}⭐ Star to support open-source AI tools\n"
                )
                full_code = code + cta

                try:
                    async with _hx.AsyncClient(timeout=20) as client:
                        r = await client.post(
                            "https://api.github.com/gists",
                            json={
                                "description": f"{desc} | by ARIA AI",
                                "public": True,
                                "files": {filename: {"content": full_code}},
                            },
                            headers={
                                "Authorization": f"Bearer {gh_token}",
                                "Accept": "application/vnd.github+json",
                            },
                        )
                        if r.status_code == 201:
                            gist_url = r.json().get("html_url", "")
                            if gist_url:
                                published_gist_urls.append(gist_url)
                                logger.info("[IncomeLoop] Gist published: %s", gist_url)
                except Exception as gist_exc:
                    logger.debug("[IncomeLoop] gist create: %s", gist_exc)

            if published_gist_urls:
                return {
                    "success": True,
                    "summary": f"Gist blitz: {len(published_gist_urls)} code snippets published with product CTAs",
                    "revenue_potential": len(published_gist_urls) * 1.0,
                    "urls": published_gist_urls,
                }
            return {"success": False, "summary": "gist_blitz: no Gists created"}

        except Exception as exc:
            logger.error("[IncomeLoop] gist_blitz: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_github_sponsors_setup(self) -> dict:
        """
        Set up FUNDING.yml in all ARIA repos to enable GitHub Sponsors.
        Also pins aria-portfolio and aria-insights repos on the profile.
        Passive income from supporters who find the repos.
        Requires: GITHUB_TOKEN
        """
        if not settings.GITHUB_TOKEN:
            return {"success": False, "summary": "sponsors_setup: needs GITHUB_TOKEN"}
        try:
            from apps.core.tools.github_client import AriaGitHubClient
            import base64 as _b64
            gh    = AriaGitHubClient()
            owner = settings.GITHUB_USERNAME or "Geremypolanco"

            # FUNDING.yml content for GitHub Sponsors
            funding_yml = (
                "# ARIA AI — Support open-source AI automation\n"
                "# These links appear as sponsor buttons on every repo\n\n"
                f"github: [{owner}]\n"
                "ko_fi: aria_ai\n"
                "buy_me_a_coffee: aria_ai\n"
                "custom:\n"
                f"  - https://github.com/{owner}/aria-portfolio\n"
            )

            target_repos = ["aria-insights", "aria-portfolio", "aria-free-resources", "aria-ai"]
            updated = []
            for repo in target_repos:
                try:
                    path = ".github/FUNDING.yml"
                    existing = await gh._get(f"/repos/{owner}/{repo}/contents/{path}")
                    sha = existing.get("sha") if "error" not in existing else None

                    body: dict = {
                        "message": "chore: enable GitHub Sponsors button",
                        "content": _b64.b64encode(funding_yml.encode()).decode(),
                    }
                    if sha:
                        body["sha"] = sha

                    r = await gh._put(f"/repos/{owner}/{repo}/contents/{path}", body)
                    if "error" not in r:
                        updated.append(repo)
                except Exception:
                    pass

            if updated:
                logger.info("[IncomeLoop] FUNDING.yml set on: %s", updated)
                return {
                    "success": True,
                    "summary": f"GitHub Sponsors enabled on {len(updated)} repos: {', '.join(updated)}",
                    "revenue_potential": 5.0,
                    "urls": [f"https://github.com/{owner}/{r}" for r in updated],
                }
            return {"success": False, "summary": "sponsors_setup: no repos updated (create repos first)"}

        except Exception as exc:
            logger.error("[IncomeLoop] sponsors_setup: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_content_repurposer(self) -> dict:
        """
        Take ONE existing blog post and repurpose it into:
        1. LinkedIn long-form article (aria-linkedin-content repo)
        2. Twitter/X thread via Zapier or aria-insights/threads/
        3. Email newsletter snippet (aria-newsletter repo)
        Triples the reach of each content piece with zero extra research.
        """
        if not settings.GITHUB_TOKEN:
            return {"success": False, "summary": "content_repurposer: needs GITHUB_TOKEN"}
        try:
            from apps.core.llm.llm_client import complete_json
            from apps.core.tools.github_client import AriaGitHubClient
            from apps.core.memory.redis_client import get_cache
            import base64 as _b64

            cache    = get_cache()
            gh       = AriaGitHubClient()
            owner    = settings.GITHUB_USERNAME or "Geremypolanco"

            # Get a recent blog post to repurpose
            raw_links = await cache.get("aria:blog:links") if cache else None
            existing_links: list = json.loads(raw_links) if raw_links else []

            if not existing_links:
                # Nothing to repurpose yet — generate fresh content first
                return await self._exec_github_blog([], cp=None)

            # Pick the most recent post not yet repurposed
            repurposed_key = "aria:income:repurposed_slugs"
            repurposed_set: set = set()
            if cache:
                raw_rep = await cache.get(repurposed_key)
                if raw_rep:
                    repurposed_set = set(json.loads(raw_rep) if isinstance(raw_rep, str) else raw_rep)

            candidates = [l for l in existing_links if l.get("slug") not in repurposed_set]
            if not candidates:
                repurposed_set = set()
                candidates = existing_links

            source = candidates[-1]  # most recent
            title  = source.get("title", "")
            slug   = source.get("slug", "")
            url    = source.get("url", "")

            # Read the source post
            file_data = await gh._get(f"/repos/{owner}/aria-insights/contents/posts/{slug}.md")
            source_content = ""
            if "content" in file_data:
                source_content = _b64.b64decode(
                    file_data["content"].replace("\n", "")
                ).decode("utf-8", errors="replace")[:4000]

            # Generate all repurposed formats
            repurposed = await complete_json(
                f"""Repurpose this blog post into 3 formats:

Title: {title}
URL: {url}
Content:
{source_content or title}

Return JSON:
{{
  "linkedin_article": "LinkedIn long-form post (300-500 words, professional tone, starts with hook, ends with question for engagement, includes link back to original)",
  "twitter_thread": "10-tweet thread. Format as tweet1\\n---\\ntweet2\\n---\\n... each under 280 chars. First tweet is the hook, last is CTA with link",
  "email_snippet": "Email newsletter paragraph (150 words). Engaging, conversational, includes link",
  "hashtags": ["#ai", "#productivity"]
}}""",
                model="fast",
            )

            published_urls  = []
            platforms_used  = []

            # 1. Publish LinkedIn content to GitHub repo
            linkedin_content = repurposed.get("linkedin_article", "")
            if linkedin_content:
                li_repo = "aria-linkedin-content"
                li_fname = f"posts/{slug}-linkedin.md"
                li_md = f"# {title}\n\n*Source: {url}*\n\n---\n\n{linkedin_content}\n\n---\n*Published by ARIA AI*"

                # Create repo if needed
                await gh._post("/user/repos", {
                    "name": li_repo, "description": "ARIA LinkedIn content — professional AI business insights",
                    "private": False, "auto_init": False,
                })
                li_sha = None
                existing = await gh._get(f"/repos/{owner}/{li_repo}/contents/{li_fname}")
                if "sha" in existing:
                    li_sha = existing["sha"]

                push_body: dict = {
                    "message": f"repurpose: LinkedIn — {title[:50]}",
                    "content": _b64.b64encode(li_md.encode()).decode(),
                }
                if li_sha:
                    push_body["sha"] = li_sha
                li_r = await gh._put(f"/repos/{owner}/{li_repo}/contents/{li_fname}", push_body)
                if "error" not in li_r:
                    li_url = f"https://github.com/{owner}/{li_repo}/blob/main/{li_fname}"
                    published_urls.append(li_url)
                    platforms_used.append("LinkedIn/GitHub")

            # 2. Post Twitter thread via Zapier or to GitHub threads/
            thread_content = repurposed.get("twitter_thread", "")
            hashtags       = " ".join(repurposed.get("hashtags", ["#ai"])[:3])
            if thread_content:
                zapier_url = getattr(settings, "ZAPIER_WEBHOOK_URL", None)
                if zapier_url:
                    try:
                        import httpx as _hx
                        async with _hx.AsyncClient(timeout=10) as _zap:
                            tweets = thread_content.split("---")
                            first_tweet = tweets[0].strip()[:280] if tweets else f"🧵 {title}\n\n{hashtags}"
                            await _zap.post(zapier_url, json={
                                "action": "tweet",
                                "text": first_tweet + f"\n\n{hashtags}",
                                "thread": [t.strip()[:280] for t in tweets[1:5]],
                            })
                        platforms_used.append("Twitter/Zapier")
                    except Exception:
                        pass

                # Always save thread to GitHub as fallback
                thread_repo  = "aria-insights"
                thread_fname = f"threads/{slug}-thread.md"
                thread_md    = f"# 🧵 Thread: {title}\n\n*Source: {url}*\n\n---\n\n" + "\n\n---\n\n".join(
                    f"**Tweet {i+1}:** {t.strip()}" for i, t in enumerate(thread_content.split("---")[:10])
                )
                t_sha = None
                existing_t = await gh._get(f"/repos/{owner}/{thread_repo}/contents/{thread_fname}")
                if "sha" in existing_t:
                    t_sha = existing_t["sha"]
                tb: dict = {
                    "message": f"thread: {title[:50]}",
                    "content": _b64.b64encode(thread_md.encode()).decode(),
                }
                if t_sha:
                    tb["sha"] = t_sha
                t_r = await gh._put(f"/repos/{owner}/{thread_repo}/contents/{thread_fname}", tb)
                if "error" not in t_r:
                    published_urls.append(f"https://github.com/{owner}/{thread_repo}/blob/main/{thread_fname}")
                    if "Twitter/Zapier" not in platforms_used:
                        platforms_used.append("Twitter/GitHub")

            # 3. Add email snippet to newsletter
            email_snippet = repurposed.get("email_snippet", "")
            if email_snippet:
                from datetime import datetime as _dt
                month_key  = _dt.now().strftime("%Y-%m")
                nl_repo    = "aria-newsletter"
                nl_fname   = f"editions/{month_key}.md"

                await gh._post("/user/repos", {
                    "name": nl_repo, "description": "ARIA monthly newsletter editions",
                    "private": False, "auto_init": False,
                })
                existing_nl = await gh._get(f"/repos/{owner}/{nl_repo}/contents/{nl_fname}")
                current_nl  = ""
                nl_sha      = None
                if "content" in existing_nl:
                    current_nl = _b64.b64decode(existing_nl["content"].replace("\n", "")).decode("utf-8", errors="replace")
                    nl_sha     = existing_nl.get("sha")
                else:
                    current_nl = f"# ARIA Newsletter — {month_key}\n\n*AI business insights, products, and tools*\n\n"

                current_nl += f"\n\n## 📝 {title}\n\n{email_snippet}\n\n[Read full article →]({url})\n"
                nl_body: dict = {
                    "message": f"newsletter: add '{title[:50]}'",
                    "content": _b64.b64encode(current_nl.encode()).decode(),
                }
                if nl_sha:
                    nl_body["sha"] = nl_sha
                nl_r = await gh._put(f"/repos/{owner}/{nl_repo}/contents/{nl_fname}", nl_body)
                if "error" not in nl_r:
                    published_urls.append(f"https://github.com/{owner}/{nl_repo}/blob/main/{nl_fname}")
                    platforms_used.append("Newsletter/GitHub")

            if published_urls:
                # Mark as repurposed
                repurposed_set.add(slug)
                if cache:
                    await cache.set(repurposed_key, json.dumps(list(repurposed_set)), ttl_seconds=86400 * 60)

                logger.info("[IncomeLoop] Repurposed '%s' → %s", title[:50], ", ".join(platforms_used))
                return {
                    "success": True,
                    "summary": f"Repurposed '{title[:50]}' → {', '.join(platforms_used)}",
                    "revenue_potential": len(published_urls) * 1.5,
                    "urls": published_urls,
                }

            return {"success": False, "summary": "content_repurposer: no content published"}

        except Exception as exc:
            logger.error("[IncomeLoop] content_repurposer: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_seo_optimizer(self) -> dict:
        """
        Revisit and improve existing GitHub blog posts:
        - Expand thin content to 800+ words
        - Add more SEO keywords, internal links, and call-to-action
        - Update publication date to keep content fresh
        Requires: GITHUB_TOKEN
        """
        if not settings.GITHUB_TOKEN:
            return {"success": False, "summary": "seo_optimizer: needs GITHUB_TOKEN"}
        try:
            from apps.core.llm.llm_client import complete_json
            from apps.core.tools.github_client import AriaGitHubClient
            from apps.core.memory.redis_client import get_cache
            import base64 as _b64

            cache    = get_cache()
            gh       = AriaGitHubClient()
            owner    = settings.GITHUB_USERNAME or "Geremypolanco"
            blog_repo = "aria-insights"

            # Get existing articles from Redis
            raw_links = await cache.get("aria:blog:links") if cache else None
            existing_links: list = json.loads(raw_links) if raw_links else []

            if not existing_links:
                return {"success": False, "summary": "seo_optimizer: no existing articles to optimize"}

            # Pick an article to optimize (oldest that hasn't been optimized recently)
            opt_set_key = "aria:income:seo_optimized"
            optimized_slugs: set = set()
            if cache:
                raw_opt = await cache.get(opt_set_key)
                if raw_opt:
                    optimized_slugs = set(json.loads(raw_opt) if isinstance(raw_opt, str) else raw_opt)

            candidates = [l for l in existing_links if l.get("slug") not in optimized_slugs]
            if not candidates:
                # Reset if all optimized — start fresh cycle
                optimized_slugs = set()
                candidates = existing_links

            target = candidates[0]
            target_slug = target.get("slug", "")
            target_title = target.get("title", "")
            target_path  = f"posts/{target_slug}.md"

            # Read the current file
            file_data = await gh._get(f"/repos/{owner}/{blog_repo}/contents/{target_path}")
            if "error" in file_data or "content" not in file_data:
                return {"success": False, "summary": f"seo_optimizer: could not read {target_path}"}

            current_content = _b64.b64decode(
                file_data["content"].replace("\n", "")
            ).decode("utf-8", errors="replace")

            current_sha = file_data.get("sha", "")
            word_count  = len(current_content.split())

            # Generate improved version
            improved = await complete_json(
                f"""Improve this existing blog post for better SEO and reader value.

Current post ({word_count} words):
{current_content[:3000]}

Requirements:
1. Expand to at least 900 words if currently shorter
2. Add 3-5 semantic SEO keywords naturally
3. Add a "Key Takeaways" section at the top
4. Add 2 internal CTA: "Want more AI tips? Follow ARIA Insights on GitHub"
5. Add a FAQ section with 3 Q&A at the bottom
6. Keep all existing links and affiliate tags
7. Return full improved markdown

Return JSON:
{{
  "improved_content": "# Title\\n\\n...",
  "seo_score_estimate": 85,
  "added_keywords": ["kw1", "kw2"],
  "word_count": 950
}}""",
                model="fast",
            )

            new_content  = improved.get("improved_content", "")
            seo_score    = improved.get("seo_score_estimate", 0)
            new_word_count = improved.get("word_count", 0)

            if not new_content or len(new_content) < len(current_content) * 0.8:
                return {"success": False, "summary": "seo_optimizer: LLM returned degraded content — skipping"}

            # Push updated file
            update_r = await gh._put(
                f"/repos/{owner}/{blog_repo}/contents/{target_path}",
                {
                    "message": f"seo: improve '{target_title[:50]}' (+{max(0, new_word_count - word_count)} words, SEO {seo_score}%)",
                    "content": _b64.b64encode(new_content.encode()).decode(),
                    "sha": current_sha,
                },
            )

            if "error" not in update_r:
                # Mark as optimized
                optimized_slugs.add(target_slug)
                if cache:
                    await cache.set(opt_set_key, json.dumps(list(optimized_slugs)), ttl_seconds=86400 * 30)

                logger.info("[IncomeLoop] SEO optimized: '%s' → %d words, SEO %d%%",
                            target_title[:50], new_word_count, seo_score)
                return {
                    "success": True,
                    "summary": f"SEO optimized: '{target_title[:50]}' ({word_count}→{new_word_count} words, SEO {seo_score}%)",
                    "revenue_potential": 2.0,
                    "urls": [target.get("url", "")],
                }

            return {"success": False, "summary": "seo_optimizer: GitHub push failed"}

        except Exception as exc:
            logger.error("[IncomeLoop] seo_optimizer: %s", exc)
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

    async def _exec_product_bundle(self) -> dict:
        """
        Bundle 2-3 existing ARIA products into a discounted package offer.
        Higher average order value (AOV) from same traffic.
        Publishes bundle page on GitHub + announces on blog.
        """
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.github_client import AriaGitHubClient
            from apps.core.memory.redis_client import get_cache
            import base64 as _b64

            ai    = get_ai_client()
            gh    = AriaGitHubClient()
            cache = get_cache()
            owner = settings.GITHUB_USERNAME or "Geremypolanco"

            if not ai:
                return {"success": False, "summary": "product_bundle: no AI client"}

            # Load recent products from catalog
            existing_products = []
            if cache:
                raw_items = await cache.lrange("aria:products:catalog", -30, -1)
                for raw in (raw_items or []):
                    try:
                        item = json.loads(raw) if isinstance(raw, str) else raw
                        if item.get("revenue", 0) > 0 and item.get("urls"):
                            existing_products.append(item)
                    except Exception:
                        pass

            # AI generates bundle concept (works even if no catalog yet)
            catalog_summary = "\n".join(
                f"- {p.get('title','')[:80]} (${p.get('revenue',0):.0f}, {p.get('strategy','')})"
                for p in existing_products[-6:]
            ) if existing_products else "No products yet — generate a hypothetical bundle for a trending niche"

            bundle_data = await ai.complete_json(
                system="You are a digital product bundling expert. Create irresistible value bundles. Output JSON only.",
                user=f"""Create a product bundle offer combining existing digital products.

Existing products:
{catalog_summary}

Design a bundle that:
- Combines 2-4 complementary products/topics
- Offers 40-60% discount vs. buying separately
- Has a compelling theme/transformation promise
- Targets a specific buyer persona

JSON:
{{
  "bundle_name": "Name of the bundle (60 chars max)",
  "tagline": "One sentence value proposition",
  "theme": "Core theme (e.g., 'Python Mastery', 'Freelance Toolkit')",
  "included_items": [
    {{"title": "Product 1 name", "value": 47}},
    {{"title": "Product 2 name", "value": 37}},
    {{"title": "Product 3 name", "value": 27}}
  ],
  "total_value": 111,
  "bundle_price": 47,
  "discount_pct": 58,
  "buyer_persona": "Who this is for (2 sentences)",
  "transformation": "What the buyer achieves after using this bundle",
  "bonuses": ["Bonus 1", "Bonus 2"],
  "urgency": "Time/quantity scarcity reason",
  "slug": "url-friendly-slug",
  "description_md": "Full bundle sales page (600+ words, markdown). Include: headline, problem, solution, what's included table, bonuses, testimonial placeholders, FAQ, CTA."
}}""",
                model=AIModel.FAST,
                max_tokens=3000,
            )

            if not bundle_data:
                return {"success": False, "summary": "product_bundle: AI generation failed"}

            bundle_name = bundle_data.get("bundle_name", "Ultimate AI Toolkit Bundle")
            slug        = bundle_data.get("slug", "ultimate-bundle")
            price       = bundle_data.get("bundle_price", 47)
            discount    = bundle_data.get("discount_pct", 50)
            total_val   = bundle_data.get("total_value", 100)
            desc_md     = bundle_data.get("description_md", "")
            items       = bundle_data.get("included_items", [])

            if not desc_md:
                return {"success": False, "summary": "product_bundle: empty description"}

            # Build full bundle page
            from datetime import datetime, timezone
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            portfolio_url = f"https://github.com/{owner}/aria-portfolio"

            full_page = f"""# {bundle_name}

> {bundle_data.get('tagline', '')}

**Bundle Price: ${price}** ~~${total_val}~~ — Save {discount}%!

{desc_md}

---

## 📦 What's Included

| Product | Individual Value |
|---------|-----------------|
""" + "\n".join(
    f"| {item.get('title', '')} | ${item.get('value', 0)} |"
    for item in items
) + f"""

**TOTAL VALUE: ${total_val}**
**YOUR PRICE: ${price}** (Save {discount}%!)

---

*Bundle curated by [ARIA AI]({portfolio_url}) | {today}*
"""

            urls_created = []

            # Publish to GitHub aria-insights/bundles/
            if settings.GITHUB_TOKEN:
                repo     = "aria-insights"
                filename = f"bundles/{today}-{slug}.md"
                encoded  = _b64.b64encode(full_page.encode()).decode()
                file_r   = await gh._put(f"/repos/{owner}/{repo}/contents/{filename}", {
                    "message": f"bundle: {bundle_name[:60]}",
                    "content": encoded,
                })
                if "error" not in file_r:
                    url = f"https://github.com/{owner}/{repo}/blob/main/{filename}"
                    urls_created.append(url)

            # Try Gumroad
            if settings.GUMROAD_TOKEN and urls_created:
                try:
                    from apps.core.tools.gumroad_tools import GumroadTools
                    gr = GumroadTools()
                    gr_result = await gr.create_product(
                        name=bundle_name,
                        description=bundle_data.get("tagline", "") + f"\n\nIncludes: {', '.join(i.get('title','') for i in items[:3])}",
                        price_cents=int(price * 100),
                        product_type="bundle",
                    )
                    if gr_result and gr_result.get("id"):
                        gumroad_url = gr_result.get("short_url") or gr_result.get("url") or ""
                        if gumroad_url:
                            urls_created.insert(0, gumroad_url)
                except Exception:
                    pass

            if not urls_created:
                return {"success": False, "summary": "product_bundle: no GitHub token to publish"}

            # Throttle-protect: track bundle slugs to avoid duplicates
            if cache:
                bundle_key = "aria:income:bundle_slugs"
                existing_slugs_raw = await cache.get(bundle_key)
                existing_slugs = json.loads(existing_slugs_raw) if existing_slugs_raw else []
                if slug in existing_slugs:
                    return {"success": False, "summary": f"product_bundle: bundle '{slug}' already published"}
                existing_slugs.append(slug)
                await cache.set(bundle_key, json.dumps(existing_slugs[-100:]), ttl_seconds=86400 * 90)

            logger.info("[IncomeLoop] Bundle published: %s ($%s, %s%% off)", bundle_name, price, discount)
            return {
                "success": True,
                "summary": f"Bundle '{bundle_name}' — ${price} (save {discount}%) | {len(items)} products included",
                "revenue_potential": float(price) * 2,  # conservative estimate: 2 sales
                "urls": urls_created,
            }

        except Exception as exc:
            logger.error("[IncomeLoop] product_bundle: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_waitlist_builder(self) -> dict:
        """
        Build an email waitlist for an upcoming product or service.
        Creates a landing page, GitHub-hosted signup form,
        and seeds future launch pipeline.
        Converts cold traffic into warm leads before the product exists.
        """
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.github_client import AriaGitHubClient
            from apps.core.memory.redis_client import get_cache
            import base64 as _b64

            ai    = get_ai_client()
            gh    = AriaGitHubClient()
            cache = get_cache()
            owner = settings.GITHUB_USERNAME or "Geremypolanco"

            if not ai or not settings.GITHUB_TOKEN:
                return {"success": False, "summary": "waitlist_builder: need AI + GITHUB_TOKEN"}

            # Deduplicate waitlist topics
            existing_topics: list = []
            if cache:
                raw = await cache.get("aria:income:waitlist_topics")
                existing_topics = json.loads(raw) if raw else []

            avoid_str = ", ".join(existing_topics[-10:]) if existing_topics else "none yet"

            waitlist_data = await ai.complete_json(
                system="You build high-converting pre-launch waitlist pages. Output JSON only.",
                user=f"""Create a waitlist landing page for an upcoming digital product/service.

Topics already used: {avoid_str}
Choose a fresh angle in: AI tools, productivity, business automation, developer tools, online income, no-code apps, personal finance, content creation.

JSON:
{{
  "product_name": "Name of the upcoming product (6 words max)",
  "tagline": "One sentence hook (max 100 chars)",
  "problem": "Specific pain point this solves (2-3 sentences)",
  "solution_teaser": "What this product will do WITHOUT revealing too much (2-3 sentences)",
  "target_audience": "Exactly who this is for",
  "launch_eta": "Expected launch timeframe (e.g., 'Q3 2025', 'in 8 weeks')",
  "early_bird_offer": "Exclusive deal for waitlist signups (e.g., '50% off + bonus module')",
  "benefits": ["Benefit 1", "Benefit 2", "Benefit 3", "Benefit 4"],
  "faq": [
    {{"q": "Question", "a": "Answer"}},
    {{"q": "Question", "a": "Answer"}}
  ],
  "slug": "url-friendly-slug",
  "topic_tag": "single keyword tag",
  "landing_page_md": "Full waitlist landing page in markdown (500+ words). Include: compelling headline, problem section, solution teaser, benefits list, FAQ, waitlist signup CTA with instructions for GitHub Issues-based waitlist, social proof placeholders."
}}""",
                model=AIModel.FAST,
                max_tokens=3000,
            )

            if not waitlist_data:
                return {"success": False, "summary": "waitlist_builder: AI generation failed"}

            product_name = waitlist_data.get("product_name", "Upcoming AI Tool")
            slug         = waitlist_data.get("slug", "upcoming-product")
            tagline      = waitlist_data.get("tagline", "")
            early_bird   = waitlist_data.get("early_bird_offer", "50% early bird discount")
            landing_md   = waitlist_data.get("landing_page_md", "")

            if not landing_md:
                return {"success": False, "summary": "waitlist_builder: empty landing page"}

            from datetime import datetime, timezone
            today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            topic    = waitlist_data.get("topic_tag", slug)

            # Check deduplication
            if topic in existing_topics:
                return {"success": False, "summary": f"waitlist_builder: topic '{topic}' already has a waitlist"}

            # Build the full page with signup instructions
            portfolio_url = f"https://github.com/{owner}/aria-portfolio"
            waitlist_repo = "aria-waitlists"

            full_page = f"""# {product_name}

> {tagline}

**🚀 Join the Waitlist → Get {early_bird}**

{landing_md}

---

## ✉️ How to Join the Waitlist

1. **[Open a GitHub Issue](https://github.com/{owner}/{waitlist_repo}/issues/new?title=Waitlist%3A+{product_name.replace(' ', '+')}&body=I+want+early+access+to+{product_name.replace(' ', '+')})** with subject: `Waitlist: {product_name}`
2. You'll receive an email when we launch
3. **Early bird members get: {early_bird}**

---

*Built by [ARIA AI]({portfolio_url}) | Waitlist opened {today}*
"""

            urls_created = []

            # Ensure aria-waitlists repo exists
            existing = await gh._get(f"/repos/{owner}/{waitlist_repo}")
            if "error" in existing:
                create_r = await gh._post("/user/repos", {
                    "name": waitlist_repo,
                    "description": "Product waitlists — join early to get exclusive discounts",
                    "private": False,
                    "auto_init": True,
                    "has_issues": True,
                })
                if "error" not in create_r:
                    await asyncio.sleep(2)
                    # Enable issues (for waitlist signups via GitHub Issues)
                    try:
                        await gh._patch(f"/repos/{owner}/{waitlist_repo}", {"has_issues": True})
                    except Exception:
                        pass

            # Publish landing page
            filename = f"waitlists/{today}-{slug}.md"
            encoded  = _b64.b64encode(full_page.encode()).decode()
            file_r   = await gh._put(f"/repos/{owner}/{waitlist_repo}/contents/{filename}", {
                "message": f"waitlist: {product_name[:60]}",
                "content": encoded,
            })
            if "error" not in file_r:
                url = f"https://github.com/{owner}/{waitlist_repo}/blob/main/{filename}"
                urls_created.append(url)

            # Also cross-post to aria-insights as a "coming soon" teaser
            teaser = f"""# Coming Soon: {product_name}

> {tagline}

We're building something new. **[Join the waitlist]({urls_created[0] if urls_created else '#'})** to get early access and {early_bird}.

**What to expect:**
{chr(10).join(f'- {b}' for b in waitlist_data.get('benefits', [])[:4])}

**Launch:** {waitlist_data.get('launch_eta', 'Soon')}

*[Join the waitlist →]({urls_created[0] if urls_created else '#'})*
"""
            teaser_file = f"coming-soon/{today}-{slug}-teaser.md"
            teaser_enc  = _b64.b64encode(teaser.encode()).decode()
            await gh._put(f"/repos/{owner}/aria-insights/contents/{teaser_file}", {
                "message": f"teaser: {product_name[:60]} waitlist",
                "content": teaser_enc,
            })
            if urls_created:
                teaser_url = f"https://github.com/{owner}/aria-insights/blob/main/{teaser_file}"
                urls_created.append(teaser_url)

            if not urls_created:
                return {"success": False, "summary": "waitlist_builder: failed to publish"}

            # Track topic
            if cache:
                existing_topics.append(topic)
                await cache.set("aria:income:waitlist_topics", json.dumps(existing_topics[-50:]), ttl_seconds=86400 * 90)

                # Store waitlist info for future launch pipeline
                waitlist_entry = {
                    "product": product_name,
                    "slug": slug,
                    "url": urls_created[0],
                    "early_bird": early_bird,
                    "launch_eta": waitlist_data.get("launch_eta", ""),
                    "created_at": today,
                }
                await cache.rpush("aria:income:waitlist_pipeline", json.dumps(waitlist_entry))
                await cache.ltrim("aria:income:waitlist_pipeline", -50, -1)

            logger.info("[IncomeLoop] Waitlist created: %s", product_name)
            return {
                "success": True,
                "summary": f"Waitlist for '{product_name}' — early bird: {early_bird}",
                "revenue_potential": 8.0,  # modest (lead capture, not direct sale)
                "urls": urls_created,
            }

        except Exception as exc:
            logger.error("[IncomeLoop] waitlist_builder: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_challenge_campaign(self) -> dict:
        """
        Create a 7-day challenge series: one content piece per day for a week.
        Each challenge day = one GitHub article + cross-post.
        Sustained organic traffic over 7+ days + email list growth via GitHub Issues.
        Converts browsers into community members who become buyers.
        """
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.github_client import AriaGitHubClient
            from apps.core.memory.redis_client import get_cache
            import base64 as _b64

            ai    = get_ai_client()
            gh    = AriaGitHubClient()
            cache = get_cache()
            owner = settings.GITHUB_USERNAME or "Geremypolanco"

            if not ai or not settings.GITHUB_TOKEN:
                return {"success": False, "summary": "challenge_campaign: need AI + GITHUB_TOKEN"}

            # Avoid duplicate challenge topics
            existing_challenges: list = []
            if cache:
                raw = await cache.get("aria:income:challenge_topics")
                existing_challenges = json.loads(raw) if raw else []

            avoid_str = ", ".join(existing_challenges[-8:]) if existing_challenges else "none yet"

            challenge_data = await ai.complete_json(
                system="You create viral 7-day challenge campaigns that build audiences and drive sales. Output JSON only.",
                user=f"""Design a 7-day challenge campaign with daily content.

Already done: {avoid_str}
Pick a fresh skill/goal in: productivity, Python, AI tools, freelancing, content creation, no-code, personal finance, entrepreneurship.

The challenge should:
- Have a clear transformation (where participants start vs. where they finish)
- Each day = one actionable task (15-30 minutes max)
- Build a community around ARIA's brand
- Lead naturally to a paid product at the end

JSON:
{{
  "challenge_name": "7-Day [Name] Challenge",
  "tagline": "One sentence hook",
  "transformation": "From X to Y in 7 days",
  "target_audience": "Who this is for",
  "slug": "url-friendly-slug",
  "topic": "single keyword",
  "upsell_product": "What paid product this leads to (e.g., full course, ebook, toolkit)",
  "upsell_price": 47,
  "days": [
    {{
      "day": 1,
      "title": "Day 1 title",
      "task": "Specific actionable task (2-3 sentences)",
      "outcome": "What participants achieve today",
      "content_md": "Full day content (300+ words markdown). Include: why this matters, step-by-step task, expected result, teaser for day 2."
    }}
  ],
  "landing_page_md": "Full challenge landing page (400+ words). Include: headline, what you'll achieve, day-by-day overview table, how to join (GitHub Issues), upsell CTA at bottom."
}}""",
                model=AIModel.FAST,
                max_tokens=4000,
            )

            if not challenge_data or "days" not in challenge_data:
                return {"success": False, "summary": "challenge_campaign: AI generation failed"}

            challenge_name = challenge_data.get("challenge_name", "7-Day Challenge")
            slug           = challenge_data.get("slug", "7-day-challenge")
            topic          = challenge_data.get("topic", slug)
            days           = challenge_data.get("days", [])
            upsell_product = challenge_data.get("upsell_product", "Full Course")
            upsell_price   = challenge_data.get("upsell_price", 47)
            landing_md     = challenge_data.get("landing_page_md", "")

            if topic in existing_challenges:
                return {"success": False, "summary": f"challenge_campaign: '{topic}' already done"}

            if not days:
                return {"success": False, "summary": "challenge_campaign: no days generated"}

            from datetime import datetime, timezone
            today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            repo     = "aria-insights"
            urls_created = []

            # Publish landing page
            portfolio_url = f"https://github.com/{owner}/aria-portfolio"
            full_landing  = f"""# {challenge_name}

> {challenge_data.get('tagline', '')}

**Transformation:** {challenge_data.get('transformation', '')}

{landing_md}

---

## 📅 Day-by-Day Overview

| Day | Title | Task |
|-----|-------|------|
""" + "\n".join(
    f"| Day {d.get('day',i+1)} | {d.get('title','')} | {d.get('task','')[:80]} |"
    for i, d in enumerate(days[:7])
) + f"""

---

## ✉️ How to Join

1. **[Click here to join](https://github.com/{owner}/aria-waitlists/issues/new?title=Join+{challenge_name.replace(' ', '+')}&body=I+want+to+join+the+challenge!)** — open a GitHub Issue
2. You'll get Day 1 in your email / GitHub notifications
3. Complete each day's task and share your progress

## 🎯 Finish Strong → Get {upsell_product}

Challenge completers get **50% off** [{upsell_product}](https://github.com/{owner}/aria-portfolio) — normally ${upsell_price}. Your price: **${int(upsell_price * 0.5)}**.

---

*Challenge by [ARIA AI]({portfolio_url}) | Started {today}*
"""

            landing_filename = f"challenges/{today}-{slug}-landing.md"
            encoded          = _b64.b64encode(full_landing.encode()).decode()
            file_r           = await gh._put(f"/repos/{owner}/{repo}/contents/{landing_filename}", {
                "message": f"challenge: {challenge_name[:60]}",
                "content": encoded,
            })
            if "error" not in file_r:
                landing_url = f"https://github.com/{owner}/{repo}/blob/main/{landing_filename}"
                urls_created.append(landing_url)

            # Publish Day 1 immediately (start the challenge)
            if days:
                day1 = days[0]
                day1_content = f"""# {challenge_name}: {day1.get('title', 'Day 1')}

> Day 1 of 7 | [{challenge_name}]({urls_created[0] if urls_created else '#'})

{day1.get('content_md', '')}

---

**Tomorrow:** Day 2 of the challenge drops tomorrow — [subscribe to the challenge]({urls_created[0] if urls_created else '#'}) to get notified.

**After 7 days:** Get 50% off [{upsell_product}](https://github.com/{owner}/aria-portfolio) — normally ${upsell_price}.

*[ARIA AI](https://github.com/{owner}/aria-portfolio)*
"""
                day1_filename = f"challenges/{today}-{slug}-day1.md"
                day1_encoded  = _b64.b64encode(day1_content.encode()).decode()
                day1_r        = await gh._put(f"/repos/{owner}/{repo}/contents/{day1_filename}", {
                    "message": f"challenge day 1: {day1.get('title', '')[:60]}",
                    "content": day1_encoded,
                })
                if "error" not in day1_r:
                    day1_url = f"https://github.com/{owner}/{repo}/blob/main/{day1_filename}"
                    urls_created.append(day1_url)

            if not urls_created:
                return {"success": False, "summary": "challenge_campaign: publish failed"}

            # Track topic
            if cache:
                existing_challenges.append(topic)
                await cache.set("aria:income:challenge_topics", json.dumps(existing_challenges[-30:]), ttl_seconds=86400 * 90)

                # Store challenge metadata for future days
                challenge_meta = {
                    "name": challenge_name,
                    "slug": slug,
                    "topic": topic,
                    "url": urls_created[0],
                    "days_total": len(days),
                    "days_published": 1,
                    "upsell_product": upsell_product,
                    "upsell_price": upsell_price,
                    "started_at": today,
                    "remaining_days": json.dumps(days[1:]),  # save for future cycles
                }
                await cache.rpush("aria:income:challenges_active", json.dumps(challenge_meta))
                await cache.ltrim("aria:income:challenges_active", -20, -1)

            logger.info("[IncomeLoop] Challenge launched: %s (%d days)", challenge_name, len(days))
            return {
                "success": True,
                "summary": f"'{challenge_name}' launched — Day 1 published, {len(days)} days planned → upsell: {upsell_product} at ${upsell_price}",
                "revenue_potential": float(upsell_price) * 3,  # 3 expected conversions
                "urls": urls_created,
            }

        except Exception as exc:
            logger.error("[IncomeLoop] challenge_campaign: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_partner_outreach(self) -> dict:
        """
        Generate B2B collaboration proposals for cross-promotion and co-selling.
        Creates partnership pitch templates targeting newsletter writers,
        YouTubers, course creators, and software companies in adjacent niches.
        Published to GitHub for discoverability; potential for exponential reach.
        """
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.github_client import AriaGitHubClient
            from apps.core.memory.redis_client import get_cache
            import base64 as _b64

            ai    = get_ai_client()
            gh    = AriaGitHubClient()
            cache = get_cache()
            owner = settings.GITHUB_USERNAME or "Geremypolanco"

            if not ai or not settings.GITHUB_TOKEN:
                return {"success": False, "summary": "partner_outreach: need AI + GITHUB_TOKEN"}

            # Avoid repeating the same niche outreach
            existing_niches: list = []
            if cache:
                raw = await cache.get("aria:income:outreach_niches")
                existing_niches = json.loads(raw) if raw else []

            avoid_str = ", ".join(existing_niches[-6:]) if existing_niches else "none yet"

            outreach_data = await ai.complete_json(
                system="You craft irresistible B2B partnership proposals that benefit both parties. Output JSON only.",
                user=f"""Create a partnership outreach campaign for ARIA AI.

ARIA is an autonomous AI platform that generates income through digital products, content, and SaaS.
Already targeted: {avoid_str}

Identify a new niche and create 3-4 personalized partnership pitches targeting:
- Newsletter writers/bloggers
- YouTube creators
- Course creators/educators
- Tool/SaaS companies

Each pitch should propose mutual value: ARIA promotes their product, they promote ARIA's tools.

JSON:
{{
  "niche": "single keyword for this outreach batch",
  "partnership_angle": "Core value exchange (2 sentences)",
  "pitches": [
    {{
      "partner_type": "Newsletter writer | YouTuber | Course creator | SaaS company",
      "subject_line": "Email subject (8 words max)",
      "pitch": "Cold outreach email (150-200 words). Personalized, specific benefits for THEM, clear CTA. Mention ARIA's audience/products.",
      "mutual_benefit": "What ARIA gives | What ARIA receives",
      "commission_offer": "Percentage or flat fee offered"
    }}
  ],
  "slug": "url-friendly-slug",
  "outreach_kit_md": "Full partnership kit in markdown (500+ words). Include: who ARIA is, current products/audience, partnership tiers (Bronze/Silver/Gold), commission structure, example collaboration ideas, how to apply."
}}""",
                model=AIModel.FAST,
                max_tokens=3000,
            )

            if not outreach_data or "pitches" not in outreach_data:
                return {"success": False, "summary": "partner_outreach: AI generation failed"}

            niche        = outreach_data.get("niche", "tech")
            slug         = outreach_data.get("slug", "partner-outreach")
            pitches      = outreach_data.get("pitches", [])
            kit_md       = outreach_data.get("outreach_kit_md", "")
            partnership_angle = outreach_data.get("partnership_angle", "")

            if niche in existing_niches:
                return {"success": False, "summary": f"partner_outreach: niche '{niche}' already covered"}

            from datetime import datetime, timezone
            today        = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            repo_name    = "aria-partnerships"
            portfolio_url = f"https://github.com/{owner}/aria-portfolio"

            # Build the outreach kit page
            pitches_section = ""
            for i, pitch in enumerate(pitches[:4], 1):
                pitches_section += f"""
### Template {i}: {pitch.get('partner_type', 'Partner')}

**Subject:** {pitch.get('subject_line', '')}

**Email:**

{pitch.get('pitch', '')}

**Mutual benefit:** {pitch.get('mutual_benefit', '')}
**Commission offered:** {pitch.get('commission_offer', '30%')}

---
"""

            full_kit = f"""# ARIA Partnership Kit — {niche.title()} Niche

> {partnership_angle}

{kit_md}

---

## 📧 Outreach Templates

{pitches_section}

---

## 🤝 Apply for Partnership

Open a GitHub Issue: [Apply Here](https://github.com/{owner}/{repo_name}/issues/new?title=Partnership+Application&body=Partner+type%3A%0AYour+website%3A%0AYour+audience+size%3A%0AWhy+this+works%3A)

*ARIA Portfolio: [{portfolio_url}]({portfolio_url}) | Outreach batch: {today}*
"""

            urls_created = []

            # Ensure aria-partnerships repo exists
            existing = await gh._get(f"/repos/{owner}/{repo_name}")
            if "error" in existing:
                create_r = await gh._post("/user/repos", {
                    "name": repo_name,
                    "description": "ARIA partnership program — collaborate, cross-promote, earn together",
                    "private": False,
                    "auto_init": True,
                    "has_issues": True,
                })
                if "error" not in create_r:
                    await asyncio.sleep(2)

            # Publish outreach kit
            filename = f"outreach/{today}-{slug}.md"
            encoded  = _b64.b64encode(full_kit.encode()).decode()
            file_r   = await gh._put(f"/repos/{owner}/{repo_name}/contents/{filename}", {
                "message": f"outreach: {niche} partnership batch",
                "content": encoded,
            })
            if "error" not in file_r:
                url = f"https://github.com/{owner}/{repo_name}/blob/main/{filename}"
                urls_created.append(url)

            # Also add a "Partner with ARIA" section to aria-portfolio
            try:
                partner_blurb = f"""## 🤝 Partner with ARIA

We're actively seeking collaborators in the {niche} space.

**What we offer:** Revenue share, co-marketing, content collaboration, product integrations.

**Apply:** [Open a partnership proposal]({urls_created[0] if urls_created else '#'})

*[View partnership kit →]({urls_created[0] if urls_created else '#'})*
"""
                portfolio_readme = await gh._get(f"/repos/{owner}/aria-portfolio/contents/README.md")
                if "content" in portfolio_readme:
                    import base64 as _b64p
                    current = _b64p.b64decode(portfolio_readme["content"].replace("\n", "")).decode("utf-8", errors="replace")
                    sha = portfolio_readme.get("sha", "")
                    marker = "## 🤝 Partner with ARIA"
                    if marker not in current:
                        new_readme = current.rstrip() + "\n\n" + partner_blurb
                        await gh._put(f"/repos/{owner}/aria-portfolio/contents/README.md", {
                            "message": "add: partnership section to portfolio",
                            "content": _b64p.b64encode(new_readme.encode()).decode(),
                            "sha": sha,
                        })
            except Exception:
                pass

            if not urls_created:
                return {"success": False, "summary": "partner_outreach: publish failed"}

            # Track niche
            if cache:
                existing_niches.append(niche)
                await cache.set("aria:income:outreach_niches", json.dumps(existing_niches[-30:]), ttl_seconds=86400 * 90)

            logger.info("[IncomeLoop] Partner outreach kit published for niche: %s (%d pitches)", niche, len(pitches))
            return {
                "success": True,
                "summary": f"Partner outreach kit published ({niche} niche, {len(pitches)} email templates) → cross-promotion pipeline",
                "revenue_potential": 15.0,  # conservative: 1 partnership deal
                "urls": urls_created,
            }

        except Exception as exc:
            logger.error("[IncomeLoop] partner_outreach: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_newsletter_issue(self) -> dict:
        """
        Publish a full newsletter edition: curated insights + product recommendations.
        Posted to aria-newsletter repo on GitHub and cross-posted to aria-insights.
        Recurring readers = recurring revenue through embedded affiliate + product CTAs.
        """
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.github_client import AriaGitHubClient
            from apps.core.memory.redis_client import get_cache
            import base64 as _b64

            ai    = get_ai_client()
            gh    = AriaGitHubClient()
            cache = get_cache()
            owner = settings.GITHUB_USERNAME or "Geremypolanco"

            if not ai or not settings.GITHUB_TOKEN:
                return {"success": False, "summary": "newsletter_issue: need AI + GITHUB_TOKEN"}

            from datetime import datetime, timezone
            now   = datetime.now(timezone.utc)
            today = now.strftime("%Y-%m-%d")
            month = now.strftime("%B %Y")

            # Track issue numbers
            issue_num = 1
            if cache:
                raw_num = await cache.get("aria:income:newsletter_issue_count")
                issue_num = int(raw_num) + 1 if raw_num else 1

            newsletter_data = await ai.complete_json(
                system="You write premium newsletters that people look forward to. Concise, actionable, monetized. Output JSON only.",
                user=f"""Write a newsletter issue for ARIA's weekly digest.

Theme: Tech + business + AI productivity for entrepreneurs and developers.
Issue number: #{issue_num}
Month: {month}

JSON:
{{
  "subject_line": "Newsletter subject (10 words max, curiosity-driven)",
  "preview_text": "Email preview text (20 words)",
  "big_idea": "The main insight or takeaway this week (1-2 sentences)",
  "sections": [
    {{
      "title": "📊 This Week's Insight",
      "content": "3-4 paragraphs of valuable, specific insight. Include real-world examples."
    }},
    {{
      "title": "🛠️ Tool of the Week",
      "content": "Short review of a specific tool/resource with pros, cons, and use case. Include affiliate CTA placeholder."
    }},
    {{
      "title": "💡 Quick Win",
      "content": "One immediately actionable tip (100 words max). Something readers can do TODAY."
    }},
    {{
      "title": "📈 ARIA's Pick",
      "content": "Recommend one ARIA product or resource relevant to this week's theme. Include price and value proposition."
    }}
  ],
  "closing": "Warm, personal closing paragraph (80 words max)",
  "ps_line": "P.S. One more value-add or teaser for next issue"
}}""",
                model=AIModel.FAST,
                max_tokens=3000,
            )

            if not newsletter_data:
                return {"success": False, "summary": "newsletter_issue: AI generation failed"}

            subject    = newsletter_data.get("subject_line", f"ARIA Weekly #{issue_num}")
            big_idea   = newsletter_data.get("big_idea", "")
            sections   = newsletter_data.get("sections", [])
            closing    = newsletter_data.get("closing", "")
            ps_line    = newsletter_data.get("ps_line", "")
            portfolio_url = f"https://github.com/{owner}/aria-portfolio"

            # Build full newsletter markdown
            full_issue = f"""# ARIA Weekly — Issue #{issue_num}: {subject}

*{newsletter_data.get('preview_text', '')}*

---

> **{big_idea}**

---

"""
            for section in sections:
                full_issue += f"## {section.get('title', '')}\n\n{section.get('content', '')}\n\n---\n\n"

            full_issue += f"""
{closing}

*P.S. {ps_line}*

---

**[Browse all ARIA tools & resources →]({portfolio_url})**

*You're receiving this because you subscribed to ARIA Weekly. | [Unsubscribe](https://github.com/{owner}/aria-newsletter)*
"""

            urls_created = []

            # Ensure aria-newsletter repo exists
            repo_name = "aria-newsletter"
            existing  = await gh._get(f"/repos/{owner}/{repo_name}")
            if "error" in existing:
                create_r = await gh._post("/user/repos", {
                    "name": repo_name,
                    "description": "ARIA Weekly — tech + business insights for AI-first entrepreneurs",
                    "private": False,
                    "auto_init": True,
                    "has_issues": False,
                })
                if "error" not in create_r:
                    await asyncio.sleep(2)

            # Publish newsletter issue
            filename = f"issues/{today}-issue-{issue_num:03d}.md"
            encoded  = _b64.b64encode(full_issue.encode()).decode()
            file_r   = await gh._put(f"/repos/{owner}/{repo_name}/contents/{filename}", {
                "message": f"newsletter #{issue_num}: {subject[:60]}",
                "content": encoded,
            })
            if "error" not in file_r:
                url = f"https://github.com/{owner}/{repo_name}/blob/main/{filename}"
                urls_created.append(url)

            # Cross-post summary to aria-insights
            teaser = f"""# Newsletter #{issue_num}: {subject}

> {big_idea}

*{newsletter_data.get('preview_text', '')}*

[Read the full issue →]({urls_created[0] if urls_created else portfolio_url})

---

**Subscribe to ARIA Weekly:** [GitHub](https://github.com/{owner}/{repo_name}) | [Portfolio]({portfolio_url})
"""
            teaser_file = f"newsletter-teasers/{today}-issue-{issue_num:03d}.md"
            teaser_enc  = _b64.b64encode(teaser.encode()).decode()
            await gh._put(f"/repos/{owner}/aria-insights/contents/{teaser_file}", {
                "message": f"newsletter teaser #{issue_num}",
                "content": teaser_enc,
            })
            if urls_created:
                urls_created.append(f"https://github.com/{owner}/aria-insights/blob/main/{teaser_file}")

            # Also try Mailchimp
            mailchimp_ok = False
            if getattr(settings, "MAILCHIMP_API_KEY", None):
                try:
                    from apps.core.tools.mailchimp_tools import MailchimpTools
                    mc   = MailchimpTools()
                    mc_r = await mc.create_campaign(
                        subject=f"ARIA Weekly #{issue_num}: {subject}",
                        body=full_issue,
                    )
                    if mc_r and mc_r.get("id"):
                        mailchimp_ok = True
                except Exception:
                    pass

            if not urls_created:
                return {"success": False, "summary": "newsletter_issue: publish failed"}

            if cache:
                await cache.set("aria:income:newsletter_issue_count", str(issue_num), ttl_seconds=86400 * 365)

            platform_str = "GitHub" + (" + Mailchimp" if mailchimp_ok else "")
            logger.info("[IncomeLoop] Newsletter issue #%d published: %s", issue_num, subject)
            return {
                "success": True,
                "summary": f"Newsletter #{issue_num} published to {platform_str}: '{subject}'",
                "revenue_potential": 6.0,  # subscriber growth → product conversions
                "urls": urls_created,
            }

        except Exception as exc:
            logger.error("[IncomeLoop] newsletter_issue: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_job_board_listing(self) -> dict:
        """
        Post ARIA's consulting/service listings to job boards and marketplaces.
        Targets GitHub repos that aggregate freelance AI work, dev communities,
        and service directories. Generates inbound B2B consulting inquiries.
        """
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.github_client import AriaGitHubClient
            from apps.core.memory.redis_client import get_cache
            import base64 as _b64

            ai    = get_ai_client()
            gh    = AriaGitHubClient()
            cache = get_cache()
            owner = settings.GITHUB_USERNAME or "Geremypolanco"

            if not ai or not settings.GITHUB_TOKEN:
                return {"success": False, "summary": "job_board_listing: need AI + GITHUB_TOKEN"}

            # Rotate service categories
            existing_services: list = []
            if cache:
                raw = await cache.get("aria:income:service_listings")
                existing_services = json.loads(raw) if raw else []

            avoid_str = ", ".join(existing_services[-5:]) if existing_services else "none yet"

            listing_data = await ai.complete_json(
                system="You write compelling B2B service listings that attract high-value clients. Output JSON only.",
                user=f"""Create a professional service listing for ARIA AI consulting services.

Already listed: {avoid_str}
Pick a new service angle: AI automation, content strategy, digital product creation, SaaS development, growth hacking, data analysis, prompt engineering, AI integration.

JSON:
{{
  "service_title": "Service name (6 words max)",
  "service_category": "single category keyword",
  "tagline": "One-line value proposition (12 words max)",
  "what_you_get": ["Deliverable 1", "Deliverable 2", "Deliverable 3", "Deliverable 4"],
  "ideal_client": "Who should hire ARIA (2 sentences)",
  "process": ["Step 1", "Step 2", "Step 3"],
  "timeline": "Delivery timeline (e.g., '3-5 business days')",
  "price_range": "Price range (e.g., '$500-$2,000')",
  "guarantee": "Risk reversal / guarantee statement",
  "slug": "url-friendly-slug",
  "listing_md": "Full service listing (500+ words markdown). Professional tone. Include: problem it solves, solution, deliverables table, process, timeline, pricing, FAQ, CTA."
}}""",
                model=AIModel.FAST,
                max_tokens=3000,
            )

            if not listing_data:
                return {"success": False, "summary": "job_board_listing: AI generation failed"}

            service_title    = listing_data.get("service_title", "AI Automation Service")
            service_category = listing_data.get("service_category", "automation")
            slug             = listing_data.get("slug", "ai-service")
            price_range      = listing_data.get("price_range", "$500-$2,000")
            listing_md       = listing_data.get("listing_md", "")

            if service_category in existing_services:
                return {"success": False, "summary": f"job_board_listing: '{service_category}' already listed"}

            from datetime import datetime, timezone
            today         = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            portfolio_url = f"https://github.com/{owner}/aria-portfolio"
            repo_name     = "aria-services"

            full_listing = f"""# {service_title}

> {listing_data.get('tagline', '')}

**Price:** {price_range}
**Timeline:** {listing_data.get('timeline', '3-5 days')}

{listing_md}

---

## 📩 Hire ARIA

To start a project, open a GitHub Issue:
[**Request this service →**](https://github.com/{owner}/{repo_name}/issues/new?title=Service+Request%3A+{service_title.replace(' ', '+')}&body=Project+description%3A%0ABudget+range%3A%0ATimeline+needed%3A)

Or contact via [portfolio]({portfolio_url}).

---

*Service provided by [ARIA AI]({portfolio_url}) | {today}*
"""

            urls_created = []

            # Ensure aria-services repo exists
            existing = await gh._get(f"/repos/{owner}/{repo_name}")
            if "error" in existing:
                create_r = await gh._post("/user/repos", {
                    "name": repo_name,
                    "description": "ARIA AI consulting & automation services — hire ARIA for your projects",
                    "private": False,
                    "auto_init": True,
                    "has_issues": True,
                })
                if "error" not in create_r:
                    await asyncio.sleep(2)

            # Publish service listing
            filename = f"services/{today}-{slug}.md"
            encoded  = _b64.b64encode(full_listing.encode()).decode()
            file_r   = await gh._put(f"/repos/{owner}/{repo_name}/contents/{filename}", {
                "message": f"service: {service_title[:60]}",
                "content": encoded,
            })
            if "error" not in file_r:
                url = f"https://github.com/{owner}/{repo_name}/blob/main/{filename}"
                urls_created.append(url)

            # Add service summary to portfolio
            try:
                service_blurb = f"""### {service_title}

{listing_data.get('tagline', '')} | {price_range}

**[View service →]({urls_created[0] if urls_created else '#'})** | [Hire me](https://github.com/{owner}/{repo_name}/issues/new)
"""
                portfolio_readme = await gh._get(f"/repos/{owner}/aria-portfolio/contents/README.md")
                if "content" in portfolio_readme:
                    import base64 as _b64p
                    current = _b64p.b64decode(portfolio_readme["content"].replace("\n", "")).decode("utf-8", errors="replace")
                    sha = portfolio_readme.get("sha", "")
                    services_marker = "## 💼 Services"
                    if services_marker not in current:
                        new_readme = current.rstrip() + f"\n\n## 💼 Services\n\n{service_blurb}"
                    else:
                        idx = current.index(services_marker)
                        next_h2 = current.find("\n## ", idx + 1)
                        if next_h2 == -1:
                            new_readme = current[:idx] + f"{services_marker}\n\n{service_blurb}"
                        else:
                            new_readme = current[:idx] + f"{services_marker}\n\n{service_blurb}\n" + current[next_h2:]
                    await gh._put(f"/repos/{owner}/aria-portfolio/contents/README.md", {
                        "message": f"add service: {service_title[:50]}",
                        "content": _b64p.b64encode(new_readme.encode()).decode(),
                        "sha": sha,
                    })
            except Exception:
                pass

            if not urls_created:
                return {"success": False, "summary": "job_board_listing: publish failed"}

            if cache:
                existing_services.append(service_category)
                await cache.set("aria:income:service_listings", json.dumps(existing_services[-30:]), ttl_seconds=86400 * 90)

            logger.info("[IncomeLoop] Service listing published: %s (%s)", service_title, price_range)
            return {
                "success": True,
                "summary": f"Service listed: '{service_title}' | {price_range} | aria-services repo",
                "revenue_potential": 20.0,  # one consulting inquiry = potential $500-$2k deal
                "urls": urls_created,
            }

        except Exception as exc:
            logger.error("[IncomeLoop] job_board_listing: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_twitter_thread(self) -> dict:
        """
        Generate a viral Twitter/X thread with TwitterEngine, then post it
        via api_publisher (real Twitter API v2).
        Falls back to GitHub when Twitter credentials aren't set.
        """
        try:
            from apps.core.tools.web_tools import WebTools
            from apps.distribution.twitter.twitter_engine import TwitterEngine
            from apps.distribution.publishers.api_publisher import APIPublisher

            wt = WebTools()
            r = await wt.search_web("trending AI business automation productivity 2025", num_results=5)
            topic = "AI is replacing human work faster than anyone admits"
            if r.get("success") and r.get("results"):
                topic = r["results"][0].get("title", topic)[:100]

            engine = TwitterEngine()
            thread = await engine.create_thread(topic, angle="educational", num_tweets=8)

            tweet_texts = [t.get("content", "") for t in thread.tweets if t.get("content")]
            if not tweet_texts:
                return {"success": False, "summary": "twitter_thread: no tweets generated"}

            pub = APIPublisher()
            results = await pub.publish_thread_to_twitter(tweet_texts)
            successful = [r for r in results if r.success]
            urls_created = [r.url for r in successful if r.url]

            if successful:
                logger.info("[IncomeLoop] Twitter thread posted: %d/%d tweets", len(successful), len(results))
                return {
                    "success": True,
                    "summary": f"Twitter thread: '{topic[:50]}' — {len(successful)}/{len(results)} tweets posted",
                    "revenue_potential": 5.0,
                    "urls": urls_created,
                }

            # Fallback: publish to GitHub aria-insights/threads/
            if settings.GITHUB_TOKEN:
                from apps.core.tools.github_client import AriaGitHubClient
                import base64 as _b64
                from datetime import datetime, timezone
                gh = AriaGitHubClient()
                owner = settings.GITHUB_USERNAME or "Geremypolanco"
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                slug = topic[:35].lower().replace(" ", "-").replace("'", "")
                content = (
                    f"# Twitter Thread: {topic}\n\n"
                    f"*{len(tweet_texts)} tweets — optimized for virality*\n\n"
                    + "\n\n---\n\n".join(f"**Tweet {i+1}:**\n\n{t}" for i, t in enumerate(tweet_texts))
                    + f"\n\n---\n\n*Generated by [ARIA AI](https://github.com/{owner}/aria-portfolio)*\n"
                    + "\n*To post: add TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET to Fly.io secrets*"
                )
                encoded = _b64.b64encode(content.encode()).decode()
                file_r = await gh._put(f"/repos/{owner}/aria-insights/contents/threads/{today}-{slug}.md", {
                    "message": f"thread: {topic[:60]}",
                    "content": encoded,
                })
                if "error" not in file_r:
                    url = f"https://github.com/{owner}/aria-insights/blob/main/threads/{today}-{slug}.md"
                    return {
                        "success": True,
                        "summary": f"Twitter thread archived to GitHub (add Twitter API keys to auto-post): {topic[:50]}",
                        "revenue_potential": 1.5,
                        "urls": [url],
                    }

            return {"success": False, "summary": "twitter_thread: add TWITTER_API_KEY to Fly.io secrets"}

        except Exception as exc:
            logger.error("[IncomeLoop] twitter_thread: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_linkedin_post(self) -> dict:
        """
        Create a LinkedIn thought-leadership post with LinkedInPublisher,
        then publish it via api_publisher (real LinkedIn API v2).
        Falls back to GitHub when LinkedIn credentials aren't set.
        """
        try:
            from apps.core.tools.web_tools import WebTools
            from apps.distribution.linkedin.linkedin_publisher import LinkedInPublisher
            from apps.distribution.publishers.api_publisher import APIPublisher

            wt = WebTools()
            r = await wt.search_web("B2B AI automation business strategy 2025 trending", num_results=5)
            topic = "AI is transforming how companies operate — here's what leaders must know"
            if r.get("success") and r.get("results"):
                topic = r["results"][0].get("title", topic)[:120]

            publisher = LinkedInPublisher()
            post = await publisher.create_post(topic, objective="thought_leadership")

            if not post.content:
                return {"success": False, "summary": "linkedin_post: no content generated"}

            pub = APIPublisher()
            result = await pub.publish_to_linkedin(post.content, visibility="PUBLIC")

            if result.success:
                logger.info("[IncomeLoop] LinkedIn post published: %s", topic[:60])
                return {
                    "success": True,
                    "summary": f"LinkedIn post published: '{topic[:60]}' — ~{post.estimated_impressions:,} impressions",
                    "revenue_potential": 8.0,
                    "urls": [result.url] if result.url else [],
                }

            # Fallback: archive to GitHub aria-insights/linkedin/
            if settings.GITHUB_TOKEN:
                from apps.core.tools.github_client import AriaGitHubClient
                import base64 as _b64
                from datetime import datetime, timezone
                gh = AriaGitHubClient()
                owner = settings.GITHUB_USERNAME or "Geremypolanco"
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                slug = topic[:35].lower().replace(" ", "-").replace("'", "")
                md_content = (
                    f"# LinkedIn Post: {topic}\n\n"
                    f"*Engagement score: {post.engagement_score:.0%} | ~{post.estimated_impressions:,} impressions*\n\n"
                    f"{post.content}\n\n"
                    f"---\n\n*Generated by [ARIA AI](https://github.com/{owner}/aria-portfolio)*\n"
                    f"*To auto-post: add LINKEDIN_ACCESS_TOKEN + LINKEDIN_PERSON_URN to Fly.io secrets*"
                )
                encoded = _b64.b64encode(md_content.encode()).decode()
                file_r = await gh._put(f"/repos/{owner}/aria-insights/contents/linkedin/{today}-{slug}.md", {
                    "message": f"linkedin: {topic[:60]}",
                    "content": encoded,
                })
                if "error" not in file_r:
                    url = f"https://github.com/{owner}/aria-insights/blob/main/linkedin/{today}-{slug}.md"
                    return {
                        "success": True,
                        "summary": f"LinkedIn post archived (add LINKEDIN_ACCESS_TOKEN to auto-post): {topic[:50]}",
                        "revenue_potential": 2.0,
                        "urls": [url],
                    }

            return {"success": False, "summary": f"linkedin_post: {result.error or 'add LINKEDIN_ACCESS_TOKEN + LINKEDIN_PERSON_URN'}"}

        except Exception as exc:
            logger.error("[IncomeLoop] linkedin_post: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_reddit_organic(self) -> dict:
        """
        Generate high-value posts for relevant subreddits.
        Posts via PRAW if REDDIT_CLIENT_ID/SECRET/REFRESH_TOKEN are set.
        Falls back to GitHub archive with full Reddit-formatted content.

        Target subreddits for max organic traffic:
          r/Entrepreneur, r/SideProject, r/passive_income, r/artificial,
          r/MachineLearning, r/learnprogramming, r/digitalnomad
        """
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.web_tools import WebTools
            import os as _os

            ai = get_ai_client()
            if not ai:
                return {"success": False, "summary": "reddit_organic: AI unavailable"}

            wt = WebTools()
            r = await wt.search_web("top Reddit posts r/entrepreneur r/SideProject 2025 AI automation", num_results=5)
            trending_topic = "How I automated my entire business with AI in 30 days (and what actually worked)"
            if r.get("success") and r.get("results"):
                trending_topic = r["results"][0].get("title", trending_topic)[:120]

            # AI generates subreddit-tailored posts
            post_data = await ai.complete_json(
                system=(
                    "You write Reddit posts that get thousands of upvotes. "
                    "Format: value-first storytelling with real numbers, specific steps, "
                    "no self-promotion unless very subtle at the end. "
                    "Write posts that Reddit communities LOVE. Output JSON only."
                ),
                user=f"""Generate 3 Reddit posts on the theme: "{trending_topic}"

Each post tailored to a different subreddit.

JSON:
{{
  "posts": [
    {{
      "subreddit": "Entrepreneur",
      "title": "post title (max 300 chars, compelling)",
      "body": "post body (600-1000 words, first-person story format, real value, subtle CTA at end)",
      "flair": "Story",
      "tags": ["AI", "automation", "business"]
    }},
    {{
      "subreddit": "SideProject",
      "title": "Show r/SideProject: [compelling title]",
      "body": "technical build story with outcomes (400-700 words)",
      "flair": "Built",
      "tags": ["AI", "indie", "saas"]
    }},
    {{
      "subreddit": "passive_income",
      "title": "earnings report title with real numbers",
      "body": "income report format (400-600 words)",
      "flair": "Update",
      "tags": ["AI", "passive", "income"]
    }}
  ]
}}""",
                model=AIModel.CREATIVE,
                max_tokens=3000,
            )

            if not post_data or not post_data.get("posts"):
                return {"success": False, "summary": "reddit_organic: AI failed to generate posts"}

            posts = post_data["posts"]
            urls_created = []
            posted_count = 0

            # Try PRAW first (real Reddit posting)
            reddit_client_id = _os.getenv("REDDIT_CLIENT_ID", "")
            reddit_client_secret = _os.getenv("REDDIT_CLIENT_SECRET", "")
            reddit_refresh_token = _os.getenv("REDDIT_REFRESH_TOKEN", "")
            reddit_username = _os.getenv("REDDIT_USERNAME", "")

            praw_available = all([reddit_client_id, reddit_client_secret, reddit_refresh_token, reddit_username])

            if praw_available:
                try:
                    import asyncpraw  # type: ignore
                    reddit = asyncpraw.Reddit(
                        client_id=reddit_client_id,
                        client_secret=reddit_client_secret,
                        refresh_token=reddit_refresh_token,
                        user_agent=f"ARIA AI Bot by /u/{reddit_username}",
                    )
                    for post in posts[:2]:  # max 2 posts per cycle to avoid spam
                        try:
                            subreddit = await reddit.subreddit(post["subreddit"])
                            submission = await subreddit.submit(
                                title=post["title"][:300],
                                selftext=post["body"][:40000],
                            )
                            post_url = f"https://reddit.com{submission.permalink}"
                            urls_created.append(post_url)
                            posted_count += 1
                            await asyncio.sleep(5)  # rate limit
                        except Exception as _pe:
                            logger.debug("[IncomeLoop] reddit PRAW post failed: %s", _pe)
                    await reddit.close()
                except ImportError:
                    praw_available = False
                except Exception as _re:
                    logger.debug("[IncomeLoop] reddit PRAW: %s", _re)
                    praw_available = False

            # Always archive to GitHub (even if PRAW posted, for SEO + record)
            if settings.GITHUB_TOKEN:
                from apps.core.tools.github_client import AriaGitHubClient
                import base64 as _b64
                from datetime import datetime, timezone
                gh = AriaGitHubClient()
                owner = settings.GITHUB_USERNAME or "Geremypolanco"
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

                for i, post in enumerate(posts):
                    slug = post["title"][:35].lower().replace(" ", "-").replace("'", "").replace("[", "").replace("]", "")
                    md = (
                        f"# r/{post['subreddit']}: {post['title']}\n\n"
                        f"*Subreddit: r/{post['subreddit']} | Flair: {post.get('flair', '')}*\n\n"
                        f"{post['body']}\n\n"
                        f"---\n\n*Generated by [ARIA AI](https://github.com/{owner}/aria-portfolio)*\n"
                    )
                    encoded = _b64.b64encode(md.encode()).decode()
                    file_r = await gh._put(
                        f"/repos/{owner}/aria-insights/contents/reddit/{today}-r-{post['subreddit']}-{i}.md",
                        {"message": f"reddit: r/{post['subreddit']} — {post['title'][:50]}", "content": encoded}
                    )
                    if "error" not in file_r:
                        url = f"https://github.com/{owner}/aria-insights/blob/main/reddit/{today}-r-{post['subreddit']}-{i}.md"
                        urls_created.append(url)

            if not urls_created and not posted_count:
                return {"success": False, "summary": "reddit_organic: no output generated"}

            praw_note = f" ({posted_count} posted to Reddit)" if posted_count else " (archived; add REDDIT_CLIENT_ID to auto-post)"
            logger.info("[IncomeLoop] reddit_organic: %d posts created%s", len(posts), praw_note)
            return {
                "success": True,
                "summary": f"Reddit organic: {len(posts)} posts for r/Entrepreneur, r/SideProject, r/passive_income{praw_note}",
                "revenue_potential": 12.0 if posted_count else 3.0,
                "urls": urls_created[:5],
            }

        except Exception as exc:
            logger.error("[IncomeLoop] reddit_organic: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_stripe_checkout(self) -> dict:
        """
        Create a real Stripe product + payment link for instant revenue.
        Falls back to LemonSqueezy if LEMONSQUEEZY_API_KEY is set.
        Falls back to GitHub product announcement when no payment processor is available.
        """
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.web_tools import WebTools

            ai = get_ai_client()
            if not ai:
                return {"success": False, "summary": "stripe_checkout: AI unavailable"}

            wt = WebTools()
            r = await wt.search_web("best selling digital products entrepreneurs 2025 AI tools", num_results=5)
            inspiration = "AI Automation Blueprint: 10 tools to 10x your output"
            if r.get("success") and r.get("results"):
                inspiration = r["results"][0].get("title", inspiration)[:100]

            # Generate a compelling product
            product_data = await ai.complete_json(
                system=(
                    "You are a digital product expert who creates high-converting offers. "
                    "Create a product that solves a real pain and is priced to sell. "
                    "Output JSON only."
                ),
                user=f"""Create a digital product inspired by: "{inspiration}"

Target: entrepreneurs and small business owners who want to automate and earn more.

JSON:
{{
  "name": "compelling product name (max 60 chars)",
  "tagline": "one-line value proposition (max 100 chars)",
  "description": "product description for payment page (200-300 words). Cover the pain it solves, what's included, and who it's for.",
  "price_cents": 2700,
  "currency": "usd",
  "features": ["feature 1", "feature 2", "feature 3", "feature 4", "feature 5"],
  "category": "automation|productivity|marketing|finance|content"
}}""",
                model=AIModel.FAST,
                max_tokens=1000,
            )

            if not product_data:
                return {"success": False, "summary": "stripe_checkout: AI failed to generate product"}

            product_name = product_data.get("name", "AI Automation Blueprint")
            product_desc = product_data.get("description", "")
            price_cents  = int(product_data.get("price_cents", 2700))
            tagline      = product_data.get("tagline", "")
            features     = product_data.get("features", [])

            urls_created = []
            platform_used = ""

            # Try Stripe first
            stripe_key = getattr(settings, "STRIPE_SECRET_KEY", None)
            if stripe_key:
                try:
                    import httpx as _httpx
                    async with _httpx.AsyncClient(timeout=20.0) as _client:
                        # Create Stripe product
                        prod_r = await _client.post(
                            "https://api.stripe.com/v1/products",
                            data={"name": product_name, "description": product_desc[:500]},
                            auth=(stripe_key, ""),
                        )
                        if prod_r.status_code == 200:
                            stripe_product_id = prod_r.json().get("id", "")
                            # Create price
                            price_r = await _client.post(
                                "https://api.stripe.com/v1/prices",
                                data={
                                    "product": stripe_product_id,
                                    "unit_amount": str(price_cents),
                                    "currency": "usd",
                                },
                                auth=(stripe_key, ""),
                            )
                            if price_r.status_code == 200:
                                stripe_price_id = price_r.json().get("id", "")
                                # Create payment link
                                link_r = await _client.post(
                                    "https://api.stripe.com/v1/payment_links",
                                    data={f"line_items[0][price]": stripe_price_id, "line_items[0][quantity]": "1"},
                                    auth=(stripe_key, ""),
                                )
                                if link_r.status_code == 200:
                                    checkout_url = link_r.json().get("url", "")
                                    if checkout_url:
                                        urls_created.append(checkout_url)
                                        platform_used = "Stripe"
                except Exception as _se:
                    logger.debug("[IncomeLoop] Stripe checkout: %s", _se)

            # Try LemonSqueezy if Stripe failed
            if not urls_created:
                ls_key  = getattr(settings, "LEMONSQUEEZY_API_KEY", None)
                ls_store = getattr(settings, "LEMONSQUEEZY_STORE_ID", None)
                if ls_key and ls_store:
                    try:
                        from apps.core.tools.lemon_squeezy_tools import LemonSqueezyTools
                        ls = LemonSqueezyTools()
                        ls_r = await ls.create_product(
                            name=product_name,
                            description=product_desc,
                            price_cents=price_cents,
                            store_id=ls_store,
                        )
                        if ls_r.get("success") and ls_r.get("url"):
                            urls_created.append(ls_r["url"])
                            platform_used = "LemonSqueezy"
                    except Exception as _le:
                        logger.debug("[IncomeLoop] LemonSqueezy: %s", _le)

            # Try Gumroad as last resort
            if not urls_created:
                if settings.GUMROAD_TOKEN:
                    try:
                        from apps.core.tools.gumroad_tools import GumroadTools
                        gumroad = GumroadTools()
                        gr = await gumroad.create_product(
                            name=product_name,
                            description=product_desc + "\n\n" + "\n".join(f"✅ {f}" for f in features[:5]),
                            price_cents=price_cents,
                            tags=["AI", "automation", "digital", product_data.get("category", "productivity")],
                        )
                        if gr.get("success") and gr.get("url"):
                            urls_created.append(gr["url"])
                            platform_used = "Gumroad"
                    except Exception as _ge:
                        logger.debug("[IncomeLoop] Gumroad: %s", _ge)

            # Always publish product to GitHub with payment link
            if settings.GITHUB_TOKEN:
                try:
                    from apps.core.tools.github_client import AriaGitHubClient
                    import base64 as _b64
                    from datetime import datetime, timezone
                    gh = AriaGitHubClient()
                    owner = settings.GITHUB_USERNAME or "Geremypolanco"
                    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    slug  = product_name[:35].lower().replace(" ", "-").replace("'", "")
                    payment_link = urls_created[0] if urls_created else ""
                    features_md = "\n".join(f"- ✅ {f}" for f in features[:6])
                    md = (
                        f"# {product_name}\n\n"
                        f"*{tagline}*\n\n"
                        f"**Price: ${price_cents/100:.0f}**"
                        + (f" | [Buy Now →]({payment_link})" if payment_link else "")
                        + f"\n\n{product_desc}\n\n"
                        f"## What's Included\n\n{features_md}\n\n"
                        f"---\n\n*[Get instant access]({payment_link if payment_link else '#'})*\n"
                        f"*Created by [ARIA AI](https://github.com/{owner}/aria-portfolio)*\n"
                    )
                    encoded = _b64.b64encode(md.encode()).decode()
                    file_r = await gh._put(f"/repos/{owner}/aria-insights/contents/products/{today}-{slug}.md", {
                        "message": f"product: {product_name[:60]}",
                        "content": encoded,
                    })
                    if "error" not in file_r:
                        gh_url = f"https://github.com/{owner}/aria-insights/blob/main/products/{today}-{slug}.md"
                        urls_created.append(gh_url)
                except Exception:
                    pass

            if not urls_created:
                return {
                    "success": False,
                    "summary": f"stripe_checkout: product '{product_name}' created but no payment processor configured. Add STRIPE_SECRET_KEY, LEMONSQUEEZY_API_KEY, or GUMROAD_TOKEN."
                }

            price_display = f"${price_cents/100:.0f}"
            platform_note = f" via {platform_used}" if platform_used else " (GitHub only — add STRIPE_SECRET_KEY for live checkout)"
            logger.info("[IncomeLoop] stripe_checkout: '%s' %s %s", product_name, price_display, platform_used)
            return {
                "success": True,
                "summary": f"Product created: '{product_name}' at {price_display}{platform_note}",
                "revenue_potential": float(price_cents / 100) * 5,  # estimated 5 sales
                "urls": urls_created[:4],
            }

        except Exception as exc:
            logger.error("[IncomeLoop] stripe_checkout: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_tiktok_script(self) -> dict:
        """
        Generate viral TikTok/Reels/YouTube Shorts scripts for 3 niches.
        Archives scripts to GitHub. If TIKTOK_CLIENT_KEY is configured, also
        queues for TikTok API upload. Drives brand awareness + product clicks.
        """
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.web_tools import WebTools
            from apps.distribution.tiktok.tiktok_engine import TikTokEngine

            ai = get_ai_client()
            if not ai:
                return {"success": False, "summary": "tiktok_script: AI unavailable"}

            wt = WebTools()
            trends_r = await wt.get_hacker_news_trending(limit=5)
            trending_topic = "AI tools that make you 10x more productive"
            if trends_r.get("success") and trends_r.get("stories"):
                trending_topic = trends_r["stories"][0].get("title", trending_topic)[:100]

            engine = TikTokEngine()
            scripts = []
            niches = ["ai_productivity", "passive_income", "side_hustle"]

            for niche in niches:
                try:
                    script = await engine.create_script(
                        niche=niche,
                        trend_topic=trending_topic,
                        platform="tiktok",
                    )
                    scripts.append(script)
                except Exception:
                    pass

            if not scripts:
                return {"success": False, "summary": "tiktok_script: no scripts generated"}

            urls_created = []

            # Archive scripts to GitHub
            if settings.GITHUB_TOKEN:
                from apps.core.tools.github_client import AriaGitHubClient
                import base64 as _b64
                from datetime import datetime, timezone
                gh = AriaGitHubClient()
                owner = settings.GITHUB_USERNAME or "Geremypolanco"
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                owner_url = f"https://github.com/{owner}/aria-portfolio"

                for i, script in enumerate(scripts[:3]):
                    niche = script.niche
                    hook  = script.hook[:60] if script.hook else f"script-{i}"
                    slug  = hook.lower().replace(" ", "-").replace("'", "")[:35]
                    md = (
                        f"# TikTok Script: {hook}\n\n"
                        f"*Niche: {niche} | Platform: {script.platform} | Duration: {script.duration_seconds}s*\n"
                        f"*Viral potential: {script.viral_potential:.0%} | Est. views: {script.estimated_views:,}*\n\n"
                        f"## HOOK (first 3 seconds)\n\n{script.hook}\n\n"
                        f"## SCRIPT\n\n{script.main_content}\n\n"
                        f"## CTA\n\n{script.cta}\n\n"
                        f"## HASHTAGS\n\n{' '.join(script.hashtags[:8])}\n\n"
                        f"## SOUND SUGGESTION\n\n{script.sound_suggestion}\n\n"
                        f"---\n\n*Created by [ARIA AI]({owner_url})*"
                    )
                    encoded = _b64.b64encode(md.encode()).decode()
                    file_r = await gh._put(
                        f"/repos/{owner}/aria-insights/contents/tiktok/{today}-{niche}-{i}.md",
                        {"message": f"tiktok: {niche} — {hook[:50]}", "content": encoded}
                    )
                    if "error" not in file_r:
                        url = f"https://github.com/{owner}/aria-insights/blob/main/tiktok/{today}-{niche}-{i}.md"
                        urls_created.append(url)

            if not urls_created:
                return {"success": False, "summary": "tiktok_script: GitHub archive failed"}

            avg_views = sum(s.estimated_views for s in scripts) // max(len(scripts), 1)
            logger.info("[IncomeLoop] tiktok_script: %d scripts archived", len(urls_created))
            return {
                "success": True,
                "summary": f"TikTok scripts: {len(scripts)} scripts for {', '.join(niches)} — ~{avg_views:,} avg est. views each",
                "revenue_potential": 15.0,  # viral TikTok can drive hundreds of product clicks
                "urls": urls_created[:4],
            }

        except Exception as exc:
            logger.error("[IncomeLoop] tiktok_script: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_linkedin_outreach(self) -> dict:
        """
        Generate personalized B2B LinkedIn outreach sequences.
        Creates prospect profiles + connection messages + 3-step follow-up sequence.
        Archives to GitHub for tracking. High revenue potential: one closed B2B deal
        can be worth $500-$5,000.
        """
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.web_tools import WebTools
            from apps.core.memory.redis_client import get_cache
            import json as _json

            ai = get_ai_client()
            if not ai:
                return {"success": False, "summary": "linkedin_outreach: AI unavailable"}

            cache = get_cache()

            # Load already-outreached companies to avoid duplicates
            outreach_log: list[str] = []
            if cache:
                raw = await cache.get("aria:income:linkedin_outreach_log")
                if raw:
                    outreach_log = _json.loads(raw) if isinstance(raw, str) else raw

            wt = WebTools()
            r = await wt.search_web("B2B SaaS startups looking for AI automation consulting 2025", num_results=5)
            industry_context = "SaaS startups and e-commerce businesses that need AI automation"
            if r.get("success") and r.get("results"):
                industry_context = r["results"][0].get("snippet", industry_context)[:200]

            # Generate prospect profiles + outreach messages
            outreach_data = await ai.complete_json(
                system=(
                    "You are a B2B sales expert who writes hyper-personalized LinkedIn messages "
                    "that get 40%+ response rates. No generic templates. Output JSON only."
                ),
                user=f"""Generate 5 LinkedIn outreach sequences for ARIA AI (an autonomous AI business platform).

Industry context: {industry_context}

For each prospect, generate:
- A realistic (fictional) prospect profile
- A connection request note (max 300 chars)
- 3-message follow-up sequence (send 3, 7, 14 days after connection)

JSON:
{{
  "prospects": [
    {{
      "name": "First Last",
      "title": "CEO / Founder / Head of Growth",
      "company": "Company Name",
      "industry": "SaaS / E-commerce / Marketing Agency",
      "pain_point": "specific pain ARIA can solve for this person",
      "connection_note": "personalized 300-char note (NO LinkedIn or 'I noticed' clichés)",
      "follow_up_1": "day 3 message (150 chars max, value-first)",
      "follow_up_2": "day 7 message (200 chars, social proof + CTA)",
      "follow_up_3": "day 14 message (100 chars, final gentle CTA)"
    }}
  ]
}}""",
                model=AIModel.CREATIVE,
                max_tokens=2500,
            )

            if not outreach_data or not outreach_data.get("prospects"):
                return {"success": False, "summary": "linkedin_outreach: AI failed to generate prospects"}

            prospects = outreach_data["prospects"]
            urls_created = []

            # Archive outreach sequences to GitHub
            if settings.GITHUB_TOKEN:
                from apps.core.tools.github_client import AriaGitHubClient
                import base64 as _b64
                from datetime import datetime, timezone
                gh = AriaGitHubClient()
                owner = settings.GITHUB_USERNAME or "Geremypolanco"
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

                md_lines = [
                    f"# LinkedIn Outreach Batch — {today}",
                    f"*{len(prospects)} prospects | Industry: B2B SaaS / E-commerce*",
                    "",
                ]
                for i, p in enumerate(prospects, 1):
                    md_lines += [
                        f"## Prospect {i}: {p.get('name', 'Unknown')} — {p.get('title', '')} @ {p.get('company', '')}",
                        f"**Industry:** {p.get('industry', '')}",
                        f"**Pain point:** {p.get('pain_point', '')}",
                        "",
                        f"### Connection Note",
                        f"> {p.get('connection_note', '')}",
                        "",
                        f"### Follow-up Sequence",
                        f"- **Day 3:** {p.get('follow_up_1', '')}",
                        f"- **Day 7:** {p.get('follow_up_2', '')}",
                        f"- **Day 14:** {p.get('follow_up_3', '')}",
                        "",
                        "---",
                        "",
                    ]
                md_lines += [
                    "## How to Use",
                    "1. Find these profiles on LinkedIn",
                    "2. Send connection request with the note above",
                    "3. Schedule follow-ups as shown",
                    "4. Goal: discovery call → proposal → close ($500-$5,000 deal)",
                    "",
                    "*Generated by ARIA AI — automated B2B outreach engine*",
                ]

                encoded = _b64.b64encode("\n".join(md_lines).encode()).decode()
                file_r = await gh._put(
                    f"/repos/{owner}/aria-insights/contents/outreach/{today}-linkedin-batch.md",
                    {"message": f"outreach: LinkedIn B2B batch {today}", "content": encoded}
                )
                if "error" not in file_r:
                    url = f"https://github.com/{owner}/aria-insights/blob/main/outreach/{today}-linkedin-batch.md"
                    urls_created.append(url)

            # Update outreach log
            if cache and prospects:
                new_entries = [f"{p.get('name', '')}@{p.get('company', '')}" for p in prospects]
                outreach_log = (outreach_log + new_entries)[-200:]
                await cache.set("aria:income:linkedin_outreach_log", _json.dumps(outreach_log), ttl_seconds=86400 * 90)

            if not urls_created:
                return {"success": False, "summary": "linkedin_outreach: archive failed"}

            logger.info("[IncomeLoop] linkedin_outreach: %d prospect sequences generated", len(prospects))
            return {
                "success": True,
                "summary": f"LinkedIn outreach: {len(prospects)} personalized sequences for B2B prospects (potential $500-$5,000/client)",
                "revenue_potential": 25.0,  # one closed deal = massive ROI
                "urls": urls_created,
            }

        except Exception as exc:
            logger.error("[IncomeLoop] linkedin_outreach: %s", exc)
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
            "github_gists": {
                "active": bool(settings.GITHUB_TOKEN),
                "keys_needed": ["GITHUB_TOKEN"],
                "revenue_channels": ["developer discovery", "backlinks", "code snippet SEO"],
            },
            "github_sponsors": {
                "active": bool(settings.GITHUB_TOKEN),
                "keys_needed": ["GITHUB_TOKEN"],
                "revenue_channels": ["passive supporter income", "sponsorships", "ko-fi / buy-me-a-coffee"],
            },
            "twitter_api": {
                "active": bool(
                    getattr(settings, "TWITTER_API_KEY", None) and
                    getattr(settings, "TWITTER_API_SECRET", None) and
                    getattr(settings, "TWITTER_ACCESS_TOKEN", None) and
                    getattr(settings, "TWITTER_ACCESS_SECRET", None)
                ),
                "keys_needed": ["TWITTER_API_KEY", "TWITTER_API_SECRET", "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET"],
                "revenue_channels": ["viral threads", "direct Twitter posting", "audience building"],
            },
            "linkedin_api": {
                "active": bool(
                    getattr(settings, "LINKEDIN_ACCESS_TOKEN", None) and
                    getattr(settings, "LINKEDIN_PERSON_URN", None)
                ),
                "keys_needed": ["LINKEDIN_ACCESS_TOKEN", "LINKEDIN_PERSON_URN"],
                "revenue_channels": ["B2B leads", "LinkedIn articles", "thought leadership"],
            },
            "reddit": {
                "active": bool(
                    getattr(settings, "REDDIT_CLIENT_ID", None) and
                    getattr(settings, "REDDIT_CLIENT_SECRET", None) and
                    getattr(settings, "REDDIT_REFRESH_TOKEN", None)
                ),
                "keys_needed": ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_REFRESH_TOKEN", "REDDIT_USERNAME"],
                "revenue_channels": ["organic Reddit traffic", "subreddit reach", "affiliate link traffic"],
            },
            "stripe": {
                "active": bool(getattr(settings, "STRIPE_SECRET_KEY", None)),
                "keys_needed": ["STRIPE_SECRET_KEY"],
                "revenue_channels": ["real checkout links", "payment processing", "product sales"],
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
            emoji = "💰" if high_value else ("📝" if result.strategy in ("github_publish", "content_pipeline", "affiliate_content", "content_repurposer") else "✅")
            is_product = result.strategy in ("product_factory", "ebook_factory", "premium_offer", "shopify_listing", "niche_rotator", "hf_spaces_demo", "lead_magnet")
            msg = (
                f"{emoji} <b>ARIA publicó contenido nuevo</b>\n"
                f"Estrategia: {result.strategy}\n"
                f"Potencial: ${result.revenue_potential:.1f}\n"
                f"{result.summary[:200]}"
                + (f"\n\n{urls_text}" if urls_text else "")
                + (f"\n\n📦 <i>Ver catálogo: /catalogo</i>" if is_product else "")
                + (f"\n📊 <i>Analíticas: /reporte</i>" if high_value else "")
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

            # Throttled portfolio update: at most once every 4 hours
            last_update_key = "aria:income:last_portfolio_product_update"
            last_update = await cache.get(last_update_key)
            if not last_update:
                asyncio.create_task(self._update_portfolio_products(cache, entry))
                await cache.set(last_update_key, "1", ttl_seconds=3600 * 4)
        except Exception as exc:
            logger.debug("[IncomeLoop] register_product: %s", exc)

    async def _update_portfolio_products(self, cache, new_entry: dict) -> None:
        """Append the latest products section to aria-portfolio README."""
        if not settings.GITHUB_TOKEN:
            return
        try:
            from apps.core.tools.github_client import AriaGitHubClient
            import base64 as _b64
            gh    = AriaGitHubClient()
            owner = settings.GITHUB_USERNAME or "Geremypolanco"
            repo  = "aria-portfolio"

            # Load catalog (last 10 items)
            raw_items = await cache.lrange("aria:products:catalog", -10, -1)
            catalog   = []
            for raw in (raw_items or []):
                try:
                    catalog.append(json.loads(raw) if isinstance(raw, str) else raw)
                except Exception:
                    pass

            # Build products section
            products_section = "## 📦 Latest Products & Publications\n\n"
            for item in reversed(catalog[-8:]):
                title   = item.get("title", "")[:80]
                urls    = item.get("urls", [])
                revenue = item.get("revenue", 0)
                date    = item.get("created_at", "")[:10]
                if urls:
                    link = urls[0]
                    products_section += f"- **[{title}]({link})** — ${revenue:.0f} potential ({date})\n"
                else:
                    products_section += f"- **{title}** — ${revenue:.0f} potential ({date})\n"

            # Read current README
            readme_data = await gh._get(f"/repos/{owner}/{repo}/contents/README.md")
            if "error" in readme_data or "content" not in readme_data:
                return
            current_readme = _b64.b64decode(readme_data["content"].replace("\n", "")).decode("utf-8", errors="replace")
            sha = readme_data.get("sha", "")

            # Replace or append products section
            marker_start = "## 📦 Latest Products"
            if marker_start in current_readme:
                # Find next H2 after the products section
                idx_start = current_readme.index(marker_start)
                idx_end   = current_readme.find("\n## ", idx_start + 1)
                if idx_end == -1:
                    new_readme = current_readme[:idx_start] + products_section
                else:
                    new_readme = current_readme[:idx_start] + products_section + "\n" + current_readme[idx_end:]
            else:
                new_readme = current_readme.rstrip() + "\n\n" + products_section

            await gh._put(f"/repos/{owner}/{repo}/contents/README.md", {
                "message": "auto: update portfolio with latest products",
                "content": _b64.b64encode(new_readme.encode()).decode(),
                "sha": sha,
            })
            logger.info("[IncomeLoop] Portfolio updated with %d products", len(catalog))
        except Exception as exc:
            logger.debug("[IncomeLoop] update_portfolio_products: %s", exc)

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

            # Revenue projection
            if total_cycles > 0 and total_tracked_rev > 0:
                cycles_per_day = (24 * 3600) / INTERVAL_SECONDS  # ~48 cycles/day
                rev_per_cycle  = total_tracked_rev / max(total_cycles, 1)
                proj_7d  = rev_per_cycle * cycles_per_day * 7
                proj_30d = rev_per_cycle * cycles_per_day * 30
                lines += [
                    "",
                    "📈 <b>Proyección de ingresos (potencial):</b>",
                    f"  7 días:  <b>${proj_7d:.2f}</b>",
                    f"  30 días: <b>${proj_30d:.2f}</b>",
                    f"  <i>(basado en {total_cycles} ciclos @ ${rev_per_cycle:.3f}/ciclo)</i>",
                ]

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
