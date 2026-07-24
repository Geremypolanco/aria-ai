"""
ARIA Content Pipeline — Content monetization engine.

Full flow:
1. Detects real trends (HN + Reddit + Product Hunt + Hacker News)
2. Generates SEO articles with Groq (ultra fast)
3. Injects affiliate links (Amazon + ClickBank + Hotmart)
4. Publishes to Medium + Dev.to + Hashnode simultaneously
5. Distributes on social media
6. Logs everything in Supabase for tracking
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import UTC, datetime

import httpx

from apps.core.config import settings
from apps.core.intelligence.quality_checker import get_quality_checker

logger = logging.getLogger("aria.content_pipeline")


# ── AFFILIATE CATEGORIES BY TOPIC ─────────────────────────

AFFILIATE_CATALOG: dict[str, list[dict]] = {
    "tech": [
        {"keyword": "laptop", "asin": "B09N9HZT5P", "title": "Recommended laptop"},
        {"keyword": "headphones", "asin": "B0CH2NZJ1Z", "title": "Top headphones"},
        {"keyword": "mouse", "asin": "B09HMKFDXC", "title": "Ergonomic mouse"},
        {"keyword": "keyboard", "asin": "B07WGNHL7Q", "title": "Mechanical keyboard"},
        {"keyword": "monitor", "asin": "B08B48BQ7T", "title": "4K monitor"},
        {"keyword": "webcam", "asin": "B08CS18WVP", "title": "HD webcam"},
        {"keyword": "microphone", "asin": "B07WYYLYVK", "title": "USB microphone"},
        {"keyword": "ssd", "asin": "B08GTYFC37", "title": "Fast SSD"},
        {"keyword": "usb hub", "asin": "B07NSGFRMW", "title": "USB-C Hub"},
        {"keyword": "cable management", "asin": "B07TPKN6PX", "title": "Cable management"},
    ],
    "ai": [
        {"keyword": "gpu", "asin": "B092PX4K4B", "title": "GPU for ML"},
        {"keyword": "book ai", "asin": "B0BX7BWJMR", "title": "AI book"},
        {"keyword": "raspberry pi", "asin": "B09TTNF8BT", "title": "Raspberry Pi"},
        {"keyword": "ai headset", "asin": "B0CM5DXNX3", "title": "Headset for AI productivity"},
        {"keyword": "ai notebook", "asin": "B09V3KXJPB", "title": "Recommended AI notebook"},
    ],
    "business": [
        {"keyword": "business book", "asin": "B079JN6B2Y", "title": "Business book"},
        {"keyword": "kindle", "asin": "B09SWS2R84", "title": "Kindle Paperwhite"},
        {"keyword": "desk", "asin": "B08CHRM5CC", "title": "Standing desk"},
        {"keyword": "chair", "asin": "B09HCPHTX1", "title": "Ergonomic chair"},
        {"keyword": "planner", "asin": "B07VQ6KRVY", "title": "Executive planner"},
        {"keyword": "whiteboard", "asin": "B07MB4PZXB", "title": "Portable whiteboard"},
    ],
    "finance": [
        {"keyword": "book finance", "asin": "B076NCZRNL", "title": "Finance book"},
        {"keyword": "calculator", "asin": "B00000J1ER", "title": "Financial calculator"},
        {"keyword": "rich dad poor dad", "asin": "B07HPG8KJX", "title": "Rich Dad Poor Dad"},
        {"keyword": "investing book", "asin": "B00JGB01W2", "title": "The Intelligent Investor"},
    ],
    "fitness": [
        {"keyword": "fitness tracker", "asin": "B09B4P7LLN", "title": "Fitness tracker"},
        {"keyword": "protein", "asin": "B07QMSL3Z5", "title": "Protein"},
        {"keyword": "yoga mat", "asin": "B07DQHV8NK", "title": "Yoga mat"},
        {"keyword": "resistance bands", "asin": "B01AVDVHTI", "title": "Resistance bands"},
        {"keyword": "foam roller", "asin": "B00O6XNJZ4", "title": "Foam roller"},
    ],
    "marketing": [
        {"keyword": "marketing book", "asin": "B07H1ZYSL6", "title": "Marketing book"},
        {"keyword": "seo book", "asin": "B09N9WG1DT", "title": "SEO book"},
        {"keyword": "copywriting", "asin": "B01N7V61GO", "title": "Breakthrough Advertising"},
        {"keyword": "influence book", "asin": "B002BD2UUC", "title": "Influence - Cialdini"},
    ],
    "crypto": [
        {"keyword": "hardware wallet", "asin": "B08Z51WMRB", "title": "Hardware wallet"},
        {"keyword": "crypto book", "asin": "B07T2XHX6G", "title": "Crypto book"},
        {"keyword": "bitcoin book", "asin": "B07C7KDBWZ", "title": "Bitcoin Standard"},
    ],
    "productivity": [
        {"keyword": "time management book", "asin": "B004DEPHOY", "title": "Getting Things Done"},
        {"keyword": "deep work book", "asin": "B00X47ZVXM", "title": "Deep Work - Cal Newport"},
        {"keyword": "pomodoro timer", "asin": "B01N6TBSML", "title": "Pomodoro Timer"},
        {"keyword": "notebook", "asin": "B01EB3OSLW", "title": "Leuchtturm1917 notebook"},
        {"keyword": "standing mat", "asin": "B07P3DJBY7", "title": "Standing desk mat"},
    ],
    "ecommerce": [
        {"keyword": "dropshipping book", "asin": "B099TTDYXT", "title": "Dropshipping guide"},
        {"keyword": "label printer", "asin": "B08VRTJ9XR", "title": "Label printer"},
        {"keyword": "scale", "asin": "B0012BTXKC", "title": "Postal scale"},
        {"keyword": "packaging", "asin": "B01N1MGFEC", "title": "Packaging materials"},
    ],
    "content_creator": [
        {"keyword": "ring light", "asin": "B07DLGNLZG", "title": "Ring light for streaming"},
        {"keyword": "green screen", "asin": "B07XSCMNKD", "title": "Portable chroma key"},
        {"keyword": "tripod", "asin": "B08FQZRBBR", "title": "Flexible tripod"},
        {"keyword": "sd card", "asin": "B07H9DVLBB", "title": "Fast SD card"},
        {"keyword": "capture card", "asin": "B07Z7KL9B2", "title": "4K capture card"},
    ],
}

CLICKBANK_PRODUCTS = [
    {
        "id": "cb_prod_1",
        "vendor": "clickbank",
        "hoplink_base": "https://vendor.clickbank.net/?affiliate=AFFILIATE&vendor=VENDOR",
        "title": "AI for Business Course",
        "commission": "75%",
    },
    {
        "id": "cb_prod_2",
        "vendor": "clickbank",
        "hoplink_base": "https://vendor.clickbank.net/?affiliate=AFFILIATE&vendor=VENDOR2",
        "title": "Digital Marketing Course",
        "commission": "60%",
    },
]


class ContentPipeline:
    """Central content generation and monetization engine."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)

    # ── TREND DETECTION ────────────────────────────────────

    async def get_trending_topics(self, limit: int = 10) -> list[dict]:
        """Gets trending topics from multiple free sources."""
        topics = []
        sources = await asyncio.gather(
            self._get_hackernews_trends(),
            self._get_reddit_trends(),
            self._get_product_hunt_trends(),
            return_exceptions=True,
        )
        for source in sources:
            if isinstance(source, list):
                topics.extend(source)

        # Deduplicate and prioritize by score
        seen = set()
        unique = []
        for t in topics:
            key = t.get("title", "").lower()[:30]
            if key not in seen:
                seen.add(key)
                unique.append(t)

        # Sort by descending score
        unique.sort(key=lambda x: x.get("score", 0), reverse=True)
        logger.info("[ContentPipeline] %d trending topics found", len(unique))
        return unique[:limit]

    async def _get_hackernews_trends(self) -> list[dict]:
        """Top stories from Hacker News (public API, no auth)."""
        try:
            res = await self._http.get("https://hacker-news.firebaseio.com/v0/topstories.json")
            ids = res.json()[:15]
            topics = []
            for story_id in ids[:8]:
                story_res = await self._http.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
                )
                story = story_res.json()
                if story and story.get("title"):
                    topics.append(
                        {
                            "title": story["title"],
                            "url": story.get("url", ""),
                            "score": story.get("score", 0),
                            "source": "hackernews",
                            "category": self._detect_category(story["title"]),
                        }
                    )
            return topics
        except Exception as exc:
            logger.warning("[ContentPipeline] HN error: %s", exc)
            return []

    async def _get_reddit_trends(self) -> list[dict]:
        """Hot posts from relevant subreddits (public API)."""
        subreddits = ["artificial", "entrepreneur", "marketing", "technology", "passive_income"]
        topics = []
        for sub in subreddits[:3]:
            try:
                res = await self._http.get(
                    f"https://www.reddit.com/r/{sub}/hot.json?limit=5",
                    headers={"User-Agent": "ARIA/1.0 content-bot"},
                )
                if res.status_code == 200:
                    posts = res.json().get("data", {}).get("children", [])
                    for post in posts[:3]:
                        data = post.get("data", {})
                        if (
                            data.get("title")
                            and not data.get("is_self", False)
                            or data.get("selftext")
                        ):
                            topics.append(
                                {
                                    "title": data["title"],
                                    "url": f"https://reddit.com{data.get('permalink', '')}",
                                    "score": data.get("score", 0),
                                    "source": f"reddit/{sub}",
                                    "category": self._detect_category(data["title"]),
                                }
                            )
            except Exception:
                continue
        return topics

    async def _get_product_hunt_trends(self) -> list[dict]:
        """Products of the day on Product Hunt (public GraphQL API)."""
        try:
            query = """
            {
              posts(first: 5, order: VOTES) {
                edges {
                  node {
                    name
                    tagline
                    votesCount
                    website
                    topics { edges { node { name } } }
                  }
                }
              }
            }
            """
            res = await self._http.post(
                "https://api.producthunt.com/v2/api/graphql",
                json={"query": query},
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": (
                        f"Bearer {settings.PRODUCT_HUNT_TOKEN}"
                        if settings.PRODUCT_HUNT_TOKEN
                        else ""
                    ),
                },
            )
            if res.status_code == 200:
                posts = res.json().get("data", {}).get("posts", {}).get("edges", [])
                return [
                    {
                        "title": p["node"]["name"] + " — " + p["node"]["tagline"],
                        "url": p["node"].get("website", ""),
                        "score": p["node"].get("votesCount", 0),
                        "source": "product_hunt",
                        "category": "tech",
                    }
                    for p in posts
                ]
        except Exception:
            pass
        return []

    def _detect_category(self, title: str) -> str:
        title_lower = title.lower()
        if any(
            w in title_lower
            for w in [
                "ai",
                "gpt",
                "llm",
                "machine learning",
                "neural",
                "openai",
                "claude",
                "gemini",
            ]
        ):
            return "ai"
        if any(
            w in title_lower
            for w in ["startup", "business", "revenue", "saas", "entrepreneur", "money"]
        ):
            return "business"
        if any(
            w in title_lower for w in ["crypto", "bitcoin", "ethereum", "blockchain", "defi", "nft"]
        ):
            return "crypto"
        if any(
            w in title_lower
            for w in ["python", "javascript", "typescript", "react", "nextjs", "api", "code", "dev"]
        ):
            return "tech"
        if any(
            w in title_lower
            for w in ["marketing", "seo", "traffic", "social media", "ads", "growth"]
        ):
            return "marketing"
        if any(
            w in title_lower for w in ["finance", "invest", "stock", "trading", "passive income"]
        ):
            return "finance"
        return "tech"

    # ── CONTENT GENERATION ─────────────────────────────────

    async def generate_article(self, topic: dict, language: str = "es") -> dict | None:
        """Generates a complete SEO article with AI."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()
            category = topic.get("category", "tech")

            lang_instruction = "in Spanish" if language == "es" else "in English"

            prompt = f"""Write a complete SEO article {lang_instruction} about:

Suggested title: {topic['title']}
Category: {category}

REQUIRED structure:
1. Compelling SEO title (H1)
2. Meta description (160 chars)
3. Powerful introduction (2 paragraphs)
4. 4-5 sections with H2 subtitles
5. List of key points
6. Call-to-action at the end
7. 3 SEO tags/keywords

Format: use **H1:**, **H2:**, **META:**, **TAGS:** as markers.
Length: 1200-1500 words.
Tone: expert but accessible, like a senior blogger."""

            response = await ai.complete(
                system=(
                    "You are a senior SEO writer specialized in viral content. "
                    "You generate articles that rank on Google and drive clicks and conversions. "
                    "Your content is original, valuable, and well structured."
                ),
                user=prompt,
                model=AIModel.STRATEGY,
                max_tokens=3000,
                temperature=0.7,
            )

            if not response or not response.success:
                return None

            article_text = response.content
            parsed = self._parse_article(article_text, topic)
            parsed["category"] = category
            parsed["source_topic"] = topic
            parsed["language"] = language
            parsed["generated_at"] = datetime.now(UTC).isoformat()
            parsed["word_count"] = len(article_text.split())

            logger.info(
                "[ContentPipeline] Article generated: %s (%d words)",
                parsed.get("title", "")[:50],
                parsed["word_count"],
            )
            return parsed

        except Exception as exc:
            logger.error("[ContentPipeline] Error generating article: %s", exc)
            return None

    def _parse_article(self, text: str, topic: dict) -> dict:
        """Extracts metadata from the generated article."""
        lines = text.split("\n")
        title = topic.get("title", "Article")
        meta = ""
        tags = []

        for line in lines:
            if line.startswith(("**H1:", "# ")):
                title = line.replace("**H1:", "").replace("**", "").replace("# ", "").strip()
            elif line.startswith("**META:"):
                meta = line.replace("**META:", "").replace("**", "").strip()
            elif line.startswith("**TAGS:"):
                tags_str = line.replace("**TAGS:", "").replace("**", "").strip()
                tags = [t.strip() for t in tags_str.split(",")]

        if not meta:
            meta = f"{title[:120]}. Read the full article for more information."

        if not tags:
            tags = [topic.get("category", "tech"), "aria ai", "technology"]

        return {
            "title": title,
            "meta_description": meta,
            "tags": tags,
            "body": text,
            "body_html": self._markdown_to_html(text),
        }

    def _markdown_to_html(self, text: str) -> str:
        """Converts basic markdown to HTML."""
        html = text
        html = re.sub(r"\*\*H1:\s*(.*?)\*\*", r"<h1>\1</h1>", html)
        html = re.sub(r"\*\*H2:\s*(.*?)\*\*", r"<h2>\1</h2>", html)
        html = re.sub(r"\*\*META:\s*.*?\*\*", "", html)
        html = re.sub(r"\*\*TAGS:\s*.*?\*\*", "", html)
        html = re.sub(r"^#{1}\s+(.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
        html = re.sub(r"^#{2}\s+(.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
        html = re.sub(r"^#{3}\s+(.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
        html = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", html)
        html = re.sub(r"\*(.*?)\*", r"<em>\1</em>", html)
        html = re.sub(r"^[-*]\s+(.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
        html = re.sub(r"(<li>.*</li>)", r"<ul>\1</ul>", html, flags=re.DOTALL)
        html = "\n".join(
            f"<p>{line}</p>" if line.strip() and not line.strip().startswith("<") else line
            for line in html.split("\n")
        )
        return html

    # ── AFFILIATE LINK INJECTION ───────────────────────────

    def inject_affiliate_links(self, article: dict) -> dict:
        """Injects relevant Amazon affiliate links into the article."""
        category = article.get("category", "tech")
        tag = settings.AMAZON_ASSOCIATE_TAG or "aria-ai-20"
        products = AFFILIATE_CATALOG.get(category, AFFILIATE_CATALOG["tech"])

        body = article.get("body", "")
        injected_count = 0

        for product in products[:3]:
            keyword = product["keyword"].lower()
            if keyword in body.lower() and injected_count < 2:
                affiliate_url = f"https://www.amazon.com/dp/{product['asin']}?tag={tag}"
                anchor = f'<a href="{affiliate_url}" target="_blank" rel="noopener">{product["title"]}</a>'
                # Replace the first occurrence of the keyword with the link
                pattern = re.compile(re.escape(keyword), re.IGNORECASE)
                new_body, n = pattern.subn(anchor, body, count=1)
                if n > 0:
                    body = new_body
                    injected_count += 1

        # If nothing was injected, add a resources section at the end
        if injected_count == 0 and products:
            affiliate_section = "\n\n## Recommended resources\n\n"
            for p in products[:3]:
                url = f"https://www.amazon.com/dp/{p['asin']}?tag={tag}"
                affiliate_section += f"- [{p['title']}]({url})\n"
            body += affiliate_section

        article["body"] = body
        article["affiliate_links_injected"] = injected_count
        article["amazon_tag"] = tag

        # Add a ClickBank link if applicable
        if category in ("business", "marketing", "ai"):
            cb_tag = settings.CLICKBANK_AFFILIATE_ID or ""
            if cb_tag and CLICKBANK_PRODUCTS:
                cb = CLICKBANK_PRODUCTS[0]
                hoplink = f"https://hop.clickbank.net/?affiliate={cb_tag}&vendor={cb['vendor']}"
                body += f'\n\n<p>👉 <strong><a href="{hoplink}">Recommended course: {cb["title"]} — {cb["commission"]} commission</a></strong></p>'
                article["body"] = body

        return article

    # ── MULTI-PLATFORM PUBLISHING ──────────────────────────

    async def publish_everywhere(self, article: dict) -> dict:
        """Publishes the article to all configured platforms."""
        from apps.core.tools.publishing_tools import PublishingTools

        publisher = PublishingTools()

        results = await asyncio.gather(
            publisher.publish_medium(article),
            publisher.publish_devto(article),
            publisher.publish_hashnode(article),
            return_exceptions=True,
        )

        published_urls = []
        for i, r in enumerate(results):
            platforms = ["medium", "devto", "hashnode"]
            if isinstance(r, dict) and r.get("success"):
                published_urls.append({"platform": platforms[i], "url": r.get("url", "")})
                logger.info("[ContentPipeline] Published on %s: %s", platforms[i], r.get("url", ""))
            elif isinstance(r, Exception):
                logger.warning("[ContentPipeline] Error on %s: %s", platforms[i], r)

        article["published_to"] = published_urls
        article["published_count"] = len(published_urls)
        return article

    async def distribute_social(self, article: dict) -> dict:
        """Distributes the article on social media."""
        from apps.core.tools.social_content_tools import SocialContentTools

        social = SocialContentTools()

        title = article.get("title", "")
        urls = article.get("published_to", [])
        primary_url = urls[0]["url"] if urls else ""
        tags = article.get("tags", [])
        hashtags = " ".join(f"#{t.replace(' ', '')}" for t in tags[:3])

        post_text = f"{title}\n\n{primary_url}\n\n{hashtags}"

        results = await social.post_to_all(post_text, article_url=primary_url, title=title)
        article["social_distribution"] = results
        return article

    # ── FULL PIPELINE ──────────────────────────────────────

    async def run_pipeline(self, num_articles: int = 3, language: str = "es") -> dict:
        """
        Runs the full monetization pipeline.
        Generates N articles about trending topics and publishes them.
        """
        start = time.time()
        logger.info("[ContentPipeline] Starting pipeline — %d articles", num_articles)

        # 1. Get trending topics
        topics = await self.get_trending_topics(limit=num_articles * 2)
        if not topics:
            logger.warning("[ContentPipeline] No trending topics — aborting")
            return {"success": False, "error": "No trending topics found"}

        published = []
        errors = []

        for topic in topics[:num_articles]:
            try:
                # 2. Generate article
                article = await self.generate_article(topic, language=language)
                if not article:
                    continue

                # 2b. Quality control — regenerate once if it doesn't pass
                _qc = get_quality_checker()
                _keywords = topic.get("keywords", [])
                _report = _qc.check(article, keywords=_keywords)
                if not _report.passed:
                    logger.warning(
                        "[ContentPipeline] Article failed QC (score %d), regenerating: %s",
                        _report.score,
                        "; ".join(_report.issues),
                    )
                    _retry = await self.generate_article(topic, language=language)
                    if _retry:
                        article = _retry
                        _report2 = _qc.check(article, keywords=_keywords)
                        if not _report2.passed:
                            logger.warning(
                                "[ContentPipeline] Regeneration also failed QC (score %d) — publishing anyway",
                                _report2.score,
                            )

                # 3. Inject affiliates
                article = self.inject_affiliate_links(article)

                # 4. Publish to platforms
                article = await self.publish_everywhere(article)

                # 5. Distribute on social media (if platforms are connected)
                if article.get("published_count", 0) > 0:
                    article = await self.distribute_social(article)

                # 6. Save to Supabase
                await self._save_article(article, topic)

                published.append(
                    {
                        "title": article.get("title", ""),
                        "platforms": [p["platform"] for p in article.get("published_to", [])],
                        "urls": article.get("published_to", []),
                        "affiliate_links": article.get("affiliate_links_injected", 0),
                        "word_count": article.get("word_count", 0),
                    }
                )

            except Exception as exc:
                logger.error(
                    "[ContentPipeline] Error in article %s: %s", topic.get("title", "")[:40], exc
                )
                errors.append(str(exc))

        elapsed = int(time.time() - start)
        result = {
            "success": len(published) > 0,
            "articles_published": len(published),
            "articles": published,
            "errors": errors,
            "elapsed_seconds": elapsed,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        logger.info(
            "[ContentPipeline] Pipeline completed — %d articles in %ds",
            len(published),
            elapsed,
        )
        return result

    async def _save_article(self, article: dict, topic: dict) -> None:
        """Saves the published article to Supabase."""
        try:
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            urls = article.get("published_to", [])
            primary_url = urls[0]["url"] if urls else ""
            db._client.table("products").insert(
                {
                    "name": article.get("title", "")[:200],
                    "type": "content_article",
                    "platform": ",".join(p["platform"] for p in urls),
                    "url": primary_url,
                    "status": "published",
                    "metadata": json.dumps(
                        {
                            "category": article.get("category"),
                            "language": article.get("language"),
                            "word_count": article.get("word_count"),
                            "affiliate_links": article.get("affiliate_links_injected", 0),
                            "tags": article.get("tags", []),
                            "source_topic": topic.get("title", ""),
                        }
                    ),
                }
            ).execute()
        except Exception as exc:
            logger.warning("[ContentPipeline] Could not save article to DB: %s", exc)
