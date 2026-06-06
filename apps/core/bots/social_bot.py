"""
social_bot.py — Bot especializado en monitoreo y gestión de redes sociales.
Aria NO revisa redes manualmente. Este bot las vigila y reporta lo que importa.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
logger = logging.getLogger("aria.bots.social")

TRENDING_SUBREDDITS = ["entrepreneur", "SaaS", "startups", "digitalnomad", "MachineLearning", "productivity"]
CONTENT_PILLARS = ["productividad con IA", "automatización de negocios", "ingresos pasivos digitales",
                   "marketing sin presupuesto", "casos de éxito startup"]

class SocialBot:
    def __init__(self):
        self._trends_cache: List[Dict] = []
        self._scan_count = 0
        self._mentions: List[Dict] = []
        self._keywords: List[str] = ["aria ai", "automatizacion", "ia negocios"]

    async def get_trending(self, platform: str = "all") -> Dict:
        try:
            from apps.core.tools.knowledge_suite import get_knowledge_suite
            ks = get_knowledge_suite()
            trends: Dict[str, Any] = {}

            if platform in ("all", "reddit"):
                reddit_posts = []
                for sub in TRENDING_SUBREDDITS[:4]:
                    r = ks.reddit.subreddit_hot(sub, limit=5)
                    for post in r.get("data", []):
                        reddit_posts.append({"source": f"r/{sub}", "title": post.get("title"),
                                             "score": post.get("score"), "url": post.get("permalink")})
                trends["reddit"] = sorted(reddit_posts, key=lambda x: x.get("score", 0), reverse=True)[:10]

            if platform in ("all", "hackernews"):
                hn = ks.news.hackernews_top(limit=10)
                trends["hackernews"] = [{"title": i.get("title"), "score": i.get("score"), "url": i.get("url")}
                                        for i in hn.get("data", [])]

            self._trends_cache = [trends]
            self._scan_count += 1
            return {"success": True, "trends": trends, "scanned_at": datetime.now(timezone.utc).isoformat()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def generate_content_ideas(self, trends_data: Optional[Dict] = None) -> List[str]:
        try:
            if not trends_data:
                result = await self.get_trending()
                trends_data = result.get("trends", {})
            from apps.core.tools.ai_client import AIModel, get_ai_client
            import json as _json
            ai = get_ai_client()
            pillars_text = "\n".join(f"- {p}" for p in CONTENT_PILLARS)
            trends_text = _json.dumps(trends_data, ensure_ascii=False, default=str)[:800]
            response = await ai.complete(
                system="Generas 8 ideas de contenido virales para redes. Combinas tendencias con pilares de negocio. Una idea por línea, sin numeración.",
                user=f"Pilares:\n{pillars_text}\n\nTendencias:\n{trends_text}",
                model=AIModel.FAST, max_tokens=400, agent_name="social_bot_ideas",
            )
            if not response.success:
                return []
            return [line.strip() for line in response.content.strip().split("\n") if line.strip()]
        except Exception as e:
            return []

    def best_time_to_post(self, platform: str = "general") -> str:
        schedules = {
            "twitter": "8am-10am ET, 12pm-1pm ET, 5pm-6pm ET (días laborables)",
            "linkedin": "Martes-Jueves, 8am-10am ET o 5pm-6pm ET",
            "instagram": "11am-1pm ET o 7pm-9pm ET, especialmente Miércoles",
            "reddit": "9am-12pm ET los domingos-lunes",
            "general": "9am-11am ET o 7pm-9pm ET en días laborables",
        }
        return schedules.get(platform.lower(), schedules["general"])

    async def monitor_keywords(self, keywords: Optional[List[str]] = None) -> Dict:
        kws = keywords or self._keywords
        try:
            from apps.core.tools.knowledge_suite import get_knowledge_suite
            ks = get_knowledge_suite()
            found = []
            for kw in kws[:5]:
                reddit_r = ks.reddit.search(kw, limit=5)
                for post in reddit_r.get("data", []):
                    found.append({"keyword": kw, "source": "reddit", "title": post.get("title"),
                                  "url": post.get("permalink"), "score": post.get("score")})
            self._mentions.extend(found)
            return {"success": True, "mentions_found": len(found), "items": found}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def add_keyword(self, keyword: str) -> None:
        if keyword not in self._keywords:
            self._keywords.append(keyword)

    def status(self) -> Dict:
        return {"bot": "SocialBot", "scans": self._scan_count, "keywords_monitored": self._keywords,
                "mentions_found": len(self._mentions), "content_pillars": CONTENT_PILLARS}

_instance: Optional[SocialBot] = None
def get_social_bot() -> SocialBot:
    global _instance
    if _instance is None:
        _instance = SocialBot()
    return _instance
