"""
Indeed connection for ARIA AI.
Job search via SerpAPI (uses the existing SERP_API_KEY — no OAuth).
Also supports direct search via Indeed RSS when SerpAPI is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("aria.connections.indeed")


class IndeedConnection:
    """
    Job search on Indeed. Does not require Indeed OAuth.
    Uses SerpAPI (existing SERP_API_KEY) as the search engine.
    Fallback: Indeed's public RSS.
    """

    SERP_URL = "https://serpapi.com/search"
    RSS_URL = "https://www.indeed.com/rss"

    def _serp_key(self) -> str:
        from apps.core.config import settings

        return getattr(settings, "SERP_API_KEY", None) or ""

    async def search_jobs(
        self,
        query: str,
        location: str = "Remote",
        max_results: int = 10,
        employment_type: str = "",
    ) -> list[dict]:
        """
        Searches for jobs on Indeed.
        Args:
          query: "software engineer Python"
          location: "New York" | "Remote" | "Miami, FL"
          employment_type: "fulltime" | "parttime" | "contract" | "temporary"
        """
        serp_key = self._serp_key()
        if serp_key:
            return await self._search_via_serpapi(
                query, location, max_results, employment_type, serp_key
            )
        return await self._search_via_rss(query, location, max_results)

    async def _search_via_serpapi(
        self,
        query: str,
        location: str,
        max_results: int,
        employment_type: str,
        api_key: str,
    ) -> list[dict]:
        params: dict[str, Any] = {
            "engine": "indeed",
            "q": query,
            "l": location,
            "api_key": api_key,
            "num": min(max_results, 15),
            "chips": f"employment_type:{employment_type}" if employment_type else "",
        }
        async with httpx.AsyncClient(timeout=20.0) as http:
            r = await http.get(self.SERP_URL, params={k: v for k, v in params.items() if v})
            r.raise_for_status()
            data = r.json()
            jobs = data.get("jobs_results", [])
            return [
                {
                    "title": j.get("title", ""),
                    "company": j.get("company_name", ""),
                    "location": j.get("location", ""),
                    "salary": j.get("salary", ""),
                    "type": j.get("job_type", ""),
                    "link": j.get("link", ""),
                    "description": (j.get("description") or "")[:400],
                    "posted": j.get("detected_extensions", {}).get("posted_at", ""),
                    "source": "indeed_via_serpapi",
                }
                for j in jobs[:max_results]
            ]

    async def _search_via_rss(self, query: str, location: str, max_results: int) -> list[dict]:
        """Fallback: Indeed public RSS (no API key needed)."""
        params = {"q": query, "l": location, "sort": "date", "limit": max_results}
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": "Mozilla/5.0"}) as http:
            try:
                r = await http.get(self.RSS_URL, params=params)
                if r.status_code != 200:
                    return []
                import xml.etree.ElementTree as ET

                root = ET.fromstring(r.text)
                items = root.findall(".//item")
                results = []
                for item in items[:max_results]:
                    title = item.findtext("title", "")
                    link = item.findtext("link", "")
                    desc = item.findtext("description", "")
                    results.append(
                        {
                            "title": title,
                            "company": "",
                            "location": location,
                            "link": link,
                            "description": desc[:400],
                            "source": "indeed_rss",
                        }
                    )
                return results
            except Exception as exc:
                logger.warning("[Indeed] RSS fallback error: %s", exc)
                return []

    async def get_job_details(self, job_url: str) -> dict:
        """Gets full job details via basic scraping."""
        try:
            async with httpx.AsyncClient(
                timeout=20.0, headers={"User-Agent": "Mozilla/5.0"}
            ) as http:
                r = await http.get(job_url)
                if r.status_code == 200:
                    # Extract title from basic HTML parsing
                    import re

                    title_m = re.search(r"<title>(.*?)</title>", r.text, re.IGNORECASE)
                    title = title_m.group(1) if title_m else "Job Posting"
                    # Extract description snippet
                    desc_m = re.search(
                        r'<div[^>]*id="jobDescriptionText"[^>]*>(.*?)</div>', r.text, re.DOTALL
                    )
                    desc_raw = desc_m.group(1) if desc_m else ""
                    desc_clean = re.sub(r"<[^>]+>", " ", desc_raw)[:1000].strip()
                    return {
                        "title": title,
                        "description": desc_clean,
                        "url": job_url,
                        "source": "indeed",
                    }
        except Exception as exc:
            logger.warning("[Indeed] get_job_details error: %s", exc)
        return {"url": job_url, "description": "Not available", "source": "indeed"}
