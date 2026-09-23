"""Phase 14 tests — LeadScraper."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


@pytest.fixture
def scraper():
    with patch("apps.acquisition.scraper.lead_scraper.get_cache", return_value=_mock_cache()):
        from apps.acquisition.scraper.lead_scraper import LeadScraper
        return LeadScraper()


# ── RawLead dataclass ─────────────────────────────────────────────────────────

def test_raw_lead_to_dict_has_required_keys(scraper):
    from apps.acquisition.scraper.lead_scraper import RawLead
    lead = RawLead(niche="fitness", company_name="Peak Fitness")
    d = lead.to_dict()
    required = {"raw_id", "niche", "company_name", "website_url", "email",
                "phone", "location", "signals", "scraped_at", "source"}
    assert required.issubset(d.keys())


def test_raw_lead_default_source(scraper):
    from apps.acquisition.scraper.lead_scraper import RawLead
    lead = RawLead(niche="fitness", company_name="GymX")
    # Default source is "web"; the scraper never produces "synthetic" leads.
    assert lead.source == "web"


def test_raw_lead_signals_is_list(scraper):
    from apps.acquisition.scraper.lead_scraper import RawLead
    lead = RawLead(niche="ecommerce", company_name="ShopX")
    assert isinstance(lead.signals, list)


# ── ScrapedBatch dataclass ────────────────────────────────────────────────────

def test_scraped_batch_to_dict_has_required_keys(scraper):
    from apps.acquisition.scraper.lead_scraper import ScrapedBatch
    batch = ScrapedBatch(niche="fitness", leads_found=5, leads_qualified=3, scrape_duration_s=1.5)
    d = batch.to_dict()
    required = {"batch_id", "niche", "leads_found", "leads_qualified", "scrape_duration_s",
                "sources_checked", "raw_leads", "created_at"}
    assert required.issubset(d.keys())


# ── Synthetic generation was REMOVED ─────────────────────────────────────────
# The scraper must never invent companies or signals. Guessing pain points
# for real businesses is fabricated data, so the synthetic generator and its
# signal/business-type tables were deleted. These tests lock that in.

def test_synthetic_generator_removed(scraper):
    assert not hasattr(scraper, "_generate_synthetic_leads")


def test_niche_signal_tables_removed(scraper):
    assert not hasattr(scraper, "_NICHE_SIGNALS")
    assert not hasattr(scraper, "_NICHE_BUSINESS_TYPES")


# ── scrape_leads ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scrape_leads_returns_batch(scraper):
    from apps.acquisition.scraper.lead_scraper import ScrapedBatch
    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=Exception("offline"))
        mock_cls.return_value = mock_http
        batch = await scraper.scrape_leads("fitness", count=5)
    assert isinstance(batch, ScrapedBatch)


@pytest.mark.asyncio
async def test_scrape_leads_has_batch_id(scraper):
    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=Exception("offline"))
        mock_cls.return_value = mock_http
        batch = await scraper.scrape_leads("fitness", count=3)
    assert len(batch.batch_id) > 0


@pytest.mark.asyncio
async def test_scrape_leads_correct_niche(scraper):
    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=Exception("offline"))
        mock_cls.return_value = mock_http
        batch = await scraper.scrape_leads("ecommerce", count=3)
    assert batch.niche == "ecommerce"


@pytest.mark.asyncio
async def test_scrape_leads_empty_when_source_down(scraper):
    """Honest failure: when the source is unreachable, the batch is empty —
    the scraper never pads results with invented companies."""
    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=Exception("offline"))
        mock_cls.return_value = mock_http
        batch = await scraper.scrape_leads("fitness", count=5)
    assert batch.leads_found == 0
    assert batch.raw_leads == []


@pytest.mark.asyncio
async def test_scrape_leads_real_results_when_source_up(scraper):
    """When DuckDuckGo answers, only real results are returned — tagged
    with their real source, never 'synthetic'."""
    payload = {
        "RelatedTopics": [
            {"Text": "Peak Fitness Gym - best gyms", "FirstURL": "https://peakfitness.example.com"},
            {"Text": "Iron Works Training Center", "FirstURL": "https://ironworks.example.com"},
        ]
    }
    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_response = MagicMock(status_code=200)
        mock_response.json = MagicMock(return_value=payload)
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_http
        batch = await scraper.scrape_leads("fitness", count=5)
    assert batch.leads_found == 2
    assert all(lead["source"] == "duckduckgo" for lead in batch.raw_leads)
    assert not any(lead["source"] == "synthetic" for lead in batch.raw_leads)
    assert batch.sources_checked == ["duckduckgo"]


@pytest.mark.asyncio
async def test_scrape_leads_stores_in_history(scraper):
    await scraper._load()
    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=Exception("offline"))
        mock_cls.return_value = mock_http
        await scraper.scrape_leads("fitness", count=3)
    assert len(scraper._scrape_history) == 1


@pytest.mark.asyncio
async def test_multiple_scrapes_accumulate(scraper):
    await scraper._load()
    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=Exception("offline"))
        mock_cls.return_value = mock_http
        await scraper.scrape_leads("fitness", count=3)
        await scraper.scrape_leads("ecommerce", count=3)
    assert len(scraper._scrape_history) == 2


# ── enrich_lead ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enrich_lead_returns_raw_lead(scraper):
    from apps.acquisition.scraper.lead_scraper import RawLead
    lead = RawLead(niche="fitness", company_name="Test Gym", website_url="")
    enriched = await scraper.enrich_lead(lead)
    assert isinstance(enriched, RawLead)


@pytest.mark.asyncio
async def test_enrich_lead_with_website_graceful(scraper):
    from apps.acquisition.scraper.lead_scraper import RawLead
    lead = RawLead(niche="fitness", company_name="Test Gym", website_url="https://example.invalid")
    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=Exception("DNS failed"))
        mock_cls.return_value = mock_http
        enriched = await scraper.enrich_lead(lead)
    assert isinstance(enriched, RawLead)
    assert len(enriched.signals) >= 0


# ── scraper_stats ─────────────────────────────────────────────────────────────

def test_scraper_stats_has_required_keys(scraper):
    stats = scraper.scraper_stats()
    required = {"total_batches", "total_leads_scraped", "total_qualified",
                "avg_qualification_rate_pct", "by_niche", "last_scrape_at"}
    assert required.issubset(stats.keys())


def test_scraper_stats_starts_zero(scraper):
    stats = scraper.scraper_stats()
    assert stats["total_batches"] == 0


def test_recent_batches_returns_list(scraper):
    result = scraper.recent_batches(limit=10)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_recent_batches_after_scrape(scraper):
    await scraper._load()
    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=Exception("offline"))
        mock_cls.return_value = mock_http
        await scraper.scrape_leads("fitness", count=3)
    result = scraper.recent_batches(limit=10)
    assert len(result) >= 1
