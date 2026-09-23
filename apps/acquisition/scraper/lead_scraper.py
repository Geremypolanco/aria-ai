"""
LeadScraper — Finds real business leads via web discovery.

Searches for businesses in a given niche using public signals:
- Structured Google-style search queries (via httpx)
- Parses business names, URLs, and signals from response patterns
- Scores leads by digital presence gaps (weak SEO, no automation, etc.)
- Feeds discovered leads into LeadEngine

Uses only httpx (no external scraping libs required).
Respects rate limits with polite delays between requests.
"""

from __future__ import annotations

import asyncio
import logging
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field

import httpx

from apps.core.memory.redis_client import get_cache

logger = logging.getLogger("aria.acquisition.lead_scraper")

_SCRAPER_KEY = "acquisition:scraper:v1"
_SCRAPER_TTL = 86400 * 30  # 30 days


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class RawLead:
    raw_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    niche: str = ""
    company_name: str = ""
    website_url: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    signals: list = field(default_factory=list)
    scraped_at: float = field(default_factory=time.time)
    source: str = "web"

    def to_dict(self) -> dict:
        return {
            "raw_id": self.raw_id,
            "niche": self.niche,
            "company_name": self.company_name,
            "website_url": self.website_url,
            "email": self.email,
            "phone": self.phone,
            "location": self.location,
            "signals": self.signals,
            "scraped_at": self.scraped_at,
            "source": self.source,
        }


@dataclass
class ScrapedBatch:
    batch_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    niche: str = ""
    leads_found: int = 0
    leads_qualified: int = 0
    scrape_duration_s: float = 0.0
    sources_checked: list = field(default_factory=list)
    raw_leads: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "niche": self.niche,
            "leads_found": self.leads_found,
            "leads_qualified": self.leads_qualified,
            "scrape_duration_s": round(self.scrape_duration_s, 3),
            "sources_checked": self.sources_checked,
            "raw_leads": self.raw_leads,
            "created_at": self.created_at,
        }


# ── Main class ────────────────────────────────────────────────────────────────


class LeadScraper:
    """Web-based B2B lead discovery.

    Returns ONLY leads discovered from real web sources. If a source is
    unreachable or yields nothing, the result is an empty list — this
    scraper never fabricates, pads, or invents leads.
    """

    # NOTE: niche signal archetypes were removed along with the synthetic
    # lead generator. Signals are now only added by enrich_lead() when it
    # genuinely verifies them on the lead's own website.

    # (Removed: _NICHE_BUSINESS_TYPES and _NAME_PREFIXES — they only fed the
    # synthetic lead generator, which was deleted. This scraper deals
    # exclusively in real, discovered leads.)

    def __init__(self) -> None:
        self._scrape_history: list[dict] = []
        self._loaded: bool = False
        self._headers: dict = {
            "User-Agent": "Mozilla/5.0 (compatible; ARIABot/1.0; +https://aria.ai/bot)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

    # ── Persistence ──────────────────────────────────────────────────────────

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_SCRAPER_KEY)
            if isinstance(data, list):
                self._scrape_history = data
        except Exception as exc:
            logger.warning("LeadScraper._load failed: %s", exc)
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            trimmed = self._scrape_history[-500:]
            await cache.set(_SCRAPER_KEY, trimmed, ttl_seconds=_SCRAPER_TTL)
            self._scrape_history = trimmed
        except Exception as exc:
            logger.warning("LeadScraper._save failed: %s", exc)

    # ── Web Discovery ─────────────────────────────────────────────────────────

    async def _search_businesses(
        self,
        niche: str,
        location: str = "United States",
        count: int = 5,
    ) -> list[RawLead]:
        """
        Attempt DuckDuckGo instant answer API to discover businesses.

        On ANY failure (network, HTTP error, parse error) returns an empty
        list. No synthetic or placeholder leads are ever generated — an
        empty result honestly means "no leads discovered".
        """
        query = f"{niche} businesses contact email {location}"
        url = (
            f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}"
            f"&format=json&no_html=1&skip_disambig=1"
        )

        raw_leads: list[RawLead] = []

        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=10.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    topics = data.get("RelatedTopics", [])

                    for topic in topics[:count]:
                        text = topic.get("Text", "") if isinstance(topic, dict) else ""
                        if not text:
                            continue

                        # Extract a company name from the first few words
                        words = text.split()
                        company_name = (
                            " ".join(words[:3]).strip(".,;:") if words else "Unknown Business"
                        )

                        # Extract URL if present in the topic
                        first_url = topic.get("FirstURL", "")
                        website_url = first_url if first_url.startswith("http") else ""

                        # Signals stay empty here: only the enrichment step
                        # (enrich_lead) may add signals, and only those it
                        # actually verifies from the fetched page. Guessing
                        # signals would fabricate data about real businesses.
                        lead = RawLead(
                            niche=niche,
                            company_name=company_name,
                            website_url=website_url,
                            location=location,
                            signals=[],
                            source="duckduckgo",
                        )
                        raw_leads.append(lead)

                    logger.info(
                        "DuckDuckGo returned %d topics for niche '%s'",
                        len(raw_leads),
                        niche,
                    )
                else:
                    logger.warning(
                        "DuckDuckGo search HTTP %d for niche '%s' — returning no leads",
                        response.status_code,
                        niche,
                    )
        except Exception as exc:
            logger.warning(
                "DuckDuckGo search failed for niche '%s': %s — returning no leads",
                niche,
                exc,
            )

        # Polite delay between requests
        await asyncio.sleep(1.0)

        return raw_leads[:count]

    # ── Lead Enrichment ──────────────────────────────────────────────────────

    async def enrich_lead(self, raw_lead: RawLead) -> RawLead:
        """
        If the lead has a website_url, fetch it and check for common gaps:
        missing meta description, no contact form, etc.
        """
        if not raw_lead.website_url:
            return raw_lead

        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=5.0) as client:
                response = await client.get(raw_lead.website_url, follow_redirects=True)
                if response.status_code == 200:
                    html = response.text.lower()

                    # Check for common missing elements
                    if (
                        'meta name="description"' not in html
                        and "<meta name='description'" not in html
                    ):
                        if "missing meta description" not in raw_lead.signals:
                            raw_lead.signals.append("missing meta description")

                    contact_indicators = ["contact", "contact-us", "get-in-touch", "reach-us"]
                    has_contact = any(ind in html for ind in contact_indicators)
                    if not has_contact and "no contact form detected" not in raw_lead.signals:
                        raw_lead.signals.append("no contact form detected")

                    form_indicators = ["<form", 'type="submit"', "type='submit'"]
                    has_form = any(ind in html for ind in form_indicators)
                    if not has_form and "no web forms found" not in raw_lead.signals:
                        raw_lead.signals.append("no web forms found")

                    if "mailto:" not in html and raw_lead.email == "":
                        if "no email found on site" not in raw_lead.signals:
                            raw_lead.signals.append("no email found on site")

                    # Check for analytics/tracking
                    tracking_indicators = ["google-analytics", "googletagmanager", "gtag(", "fbq("]
                    has_tracking = any(ind in html for ind in tracking_indicators)
                    if (
                        not has_tracking
                        and "no tracking/analytics detected" not in raw_lead.signals
                    ):
                        raw_lead.signals.append("no tracking/analytics detected")

        except Exception as exc:
            logger.debug("enrich_lead fetch failed for %s: %s", raw_lead.website_url, exc)
            raw_lead.signals.append("website unreachable or slow")

        return raw_lead

    # ── Main Scrape Entry Point ───────────────────────────────────────────────

    async def scrape_leads(
        self,
        niche: str,
        count: int = 10,
        location: str = "US",
    ) -> ScrapedBatch:
        """Scrape and qualify leads for the given niche."""
        await self._load()

        start_ts = time.time()
        niche_clean = niche.strip().lower()
        location_full = "United States" if location.upper() in ("US", "USA") else location

        raw_leads = await self._search_businesses(
            niche=niche_clean,
            location=location_full,
            count=count,
        )

        # Qualify: keep leads with 2+ signals OR a website_url
        qualified = [lead for lead in raw_leads if len(lead.signals) >= 2 or bool(lead.website_url)]

        duration = time.time() - start_ts

        batch = ScrapedBatch(
            niche=niche_clean,
            leads_found=len(raw_leads),
            leads_qualified=len(qualified),
            scrape_duration_s=duration,
            sources_checked=["duckduckgo"],
            raw_leads=[lead.to_dict() for lead in raw_leads],
        )

        self._scrape_history.append(batch.to_dict())
        await self._save()

        logger.info(
            "Scraped %d leads (%d qualified) for niche '%s' in %.2fs",
            len(raw_leads),
            len(qualified),
            niche_clean,
            duration,
        )
        return batch

    # ── Stats & History ──────────────────────────────────────────────────────

    def scraper_stats(self) -> dict:
        """Aggregate statistics across all scrape batches."""
        total_batches = len(self._scrape_history)
        total_leads = sum(b.get("leads_found", 0) for b in self._scrape_history)
        total_qualified = sum(b.get("leads_qualified", 0) for b in self._scrape_history)

        avg_qual_rate = 0.0
        if total_leads > 0:
            avg_qual_rate = round(total_qualified / total_leads * 100, 2)

        by_niche: dict[str, dict] = {}
        for batch in self._scrape_history:
            n = batch.get("niche", "unknown")
            if n not in by_niche:
                by_niche[n] = {"batches": 0, "leads_found": 0, "leads_qualified": 0}
            by_niche[n]["batches"] += 1
            by_niche[n]["leads_found"] += batch.get("leads_found", 0)
            by_niche[n]["leads_qualified"] += batch.get("leads_qualified", 0)

        last_scrape_at = 0.0
        if self._scrape_history:
            last_scrape_at = self._scrape_history[-1].get("created_at", 0.0)

        return {
            "total_batches": total_batches,
            "total_leads_scraped": total_leads,
            "total_qualified": total_qualified,
            "avg_qualification_rate_pct": avg_qual_rate,
            "by_niche": by_niche,
            "last_scrape_at": last_scrape_at,
        }

    def recent_batches(self, limit: int = 10) -> list[dict]:
        """Return the most recent N scrape batches."""
        return self._scrape_history[-limit:]


# ── Singleton ─────────────────────────────────────────────────────────────────

_scraper_instance: LeadScraper | None = None


def get_lead_scraper() -> LeadScraper:
    global _scraper_instance
    if _scraper_instance is None:
        _scraper_instance = LeadScraper()
    return _scraper_instance
