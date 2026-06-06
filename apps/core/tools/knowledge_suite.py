"""
knowledge_suite.py — Suite completa de conocimiento para ARIA.

Integra librerías de conocimiento en todas las categorías:
  • Búsqueda web: DuckDuckGo, Wikipedia, extracción de contenido
  • Ciencia:      arXiv, PubMed, Semantic Scholar
  • Finanzas:     Yahoo Finance, CoinGecko (crypto), Alpha Vantage
  • Noticias:     GNews, RSS, NewsAPI
  • Cómputo:      Wolfram Alpha, conversión de unidades, clima
  • RAG/Memoria:  ChromaDB, Sentence Transformers (embeddings locales)
  • Social:       HackerNews, Reddit, tendencias globales

Sin clave de API requerida: DuckDuckGo, Wikipedia, arXiv, CoinGecko,
  HackerNews, Semantic Scholar, clima (wttr.in).
Con clave opcional: Wolfram Alpha, Alpha Vantage, NewsAPI, Reddit.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# UTILIDADES INTERNAS
# ──────────────────────────────────────────────────────────────────────────────

def _try_import(module: str, package: str) -> Optional[Any]:
    try:
        import importlib
        return importlib.import_module(module)
    except ImportError:
        logger.warning("Librería '%s' no instalada. Instala con: pip install %s", module, package)
        return None


def _ok(data: Any, **extra) -> Dict:
    return {"success": True, "data": data, **extra}


def _err(msg: str) -> Dict:
    return {"success": False, "error": msg}


# ──────────────────────────────────────────────────────────────────────────────
# 1. BÚSQUEDA WEB — DuckDuckGo (sin API key)
# ──────────────────────────────────────────────────────────────────────────────

class WebSearchEngine:
    """Búsqueda web usando DuckDuckGo (gratis, sin API key)."""

    def search(self, query: str, max_results: int = 8, region: str = "es-es") -> Dict:
        ddg = _try_import("duckduckgo_search", "duckduckgo-search")
        if not ddg:
            return _err("duckduckgo-search no instalado")
        try:
            with ddg.DDGS() as d:
                results = list(d.text(query, region=region, max_results=max_results))
            return _ok(results, query=query, count=len(results))
        except Exception as e:
            return _err(str(e))

    def search_news(self, query: str, max_results: int = 8, region: str = "es-es") -> Dict:
        ddg = _try_import("duckduckgo_search", "duckduckgo-search")
        if not ddg:
            return _err("duckduckgo-search no instalado")
        try:
            with ddg.DDGS() as d:
                results = list(d.news(query, region=region, max_results=max_results))
            return _ok(results, query=query, count=len(results))
        except Exception as e:
            return _err(str(e))

    def search_images(self, query: str, max_results: int = 6) -> Dict:
        ddg = _try_import("duckduckgo_search", "duckduckgo-search")
        if not ddg:
            return _err("duckduckgo-search no instalado")
        try:
            with ddg.DDGS() as d:
                results = list(d.images(query, max_results=max_results))
            return _ok(results, query=query, count=len(results))
        except Exception as e:
            return _err(str(e))

    def suggest(self, query: str) -> Dict:
        """Autocompletado de búsqueda."""
        ddg = _try_import("duckduckgo_search", "duckduckgo-search")
        if not ddg:
            return _err("duckduckgo-search no instalado")
        try:
            with ddg.DDGS() as d:
                results = list(d.suggestions(query))
            return _ok(results)
        except Exception as e:
            return _err(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 2. WIKIPEDIA (sin API key)
# ──────────────────────────────────────────────────────────────────────────────

class WikipediaEngine:
    """Acceso a Wikipedia en múltiples idiomas."""

    def __init__(self, language: str = "es"):
        self.language = language

    def summary(self, topic: str, sentences: int = 5, lang: Optional[str] = None) -> Dict:
        wk = _try_import("wikipediaapi", "wikipedia-api")
        if not wk:
            return _err("wikipedia-api no instalado")
        try:
            wiki = wk.Wikipedia(
                language=lang or self.language,
                user_agent="ARIA-AI/1.0 (https://github.com/Geremypolanco/aria-ai)"
            )
            page = wiki.page(topic)
            if not page.exists():
                return _err(f"No se encontró página: {topic}")
            text = page.summary
            if sentences:
                parts = text.split(". ")
                text = ". ".join(parts[:sentences]) + ("." if len(parts) > sentences else "")
            return _ok({
                "title": page.title,
                "summary": text,
                "url": page.fullurl,
                "categories": list(page.categories.keys())[:10],
                "sections": [s.title for s in page.sections],
            })
        except Exception as e:
            return _err(str(e))

    def search(self, query: str, results: int = 8, lang: Optional[str] = None) -> Dict:
        wk = _try_import("wikipediaapi", "wikipedia-api")
        if not wk:
            return _err("wikipedia-api no instalado")
        try:
            wiki = wk.Wikipedia(
                language=lang or self.language,
                user_agent="ARIA-AI/1.0"
            )
            srp = wiki.search(query, results=results)
            return _ok([{"title": r, "url": f"https://{lang or self.language}.wikipedia.org/wiki/{r.replace(' ', '_')}"} for r in srp])
        except Exception as e:
            return _err(str(e))

    def full_article(self, topic: str, lang: Optional[str] = None) -> Dict:
        wk = _try_import("wikipediaapi", "wikipedia-api")
        if not wk:
            return _err("wikipedia-api no instalado")
        try:
            wiki = wk.Wikipedia(
                language=lang or self.language,
                user_agent="ARIA-AI/1.0"
            )
            page = wiki.page(topic)
            if not page.exists():
                return _err(f"No se encontró: {topic}")
            sections = {}
            for s in page.sections:
                sections[s.title] = s.text[:500]
            return _ok({
                "title": page.title,
                "url": page.fullurl,
                "summary": page.summary[:1000],
                "sections": sections,
                "references": list(page.references.keys())[:10],
            })
        except Exception as e:
            return _err(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 3. EXTRACCIÓN DE CONTENIDO WEB (trafilatura)
# ──────────────────────────────────────────────────────────────────────────────

class WebContentExtractor:
    """Extrae texto limpio de cualquier URL (artículos, blogs, docs)."""

    def extract(self, url: str, include_comments: bool = False) -> Dict:
        tr = _try_import("trafilatura", "trafilatura")
        if not tr:
            return _err("trafilatura no instalado")
        try:
            downloaded = tr.fetch_url(url)
            if not downloaded:
                return _err("No se pudo descargar la URL")
            text = tr.extract(
                downloaded,
                include_comments=include_comments,
                include_tables=True,
                favor_precision=True,
            )
            meta = tr.extract_metadata(downloaded)
            return _ok({
                "url": url,
                "text": text or "",
                "title": meta.title if meta else None,
                "author": meta.author if meta else None,
                "date": meta.date if meta else None,
                "description": meta.description if meta else None,
                "language": meta.language if meta else None,
                "word_count": len((text or "").split()),
            })
        except Exception as e:
            return _err(str(e))

    def extract_links(self, url: str) -> Dict:
        tr = _try_import("trafilatura", "trafilatura")
        if not tr:
            return _err("trafilatura no instalado")
        try:
            from trafilatura.spider import focused_crawler
            to_visit, known = focused_crawler(url, max_seen_urls=20, max_known_urls=50)
            return _ok({"to_visit": list(to_visit), "known": list(known)})
        except Exception as e:
            return _err(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 4. CIENCIA — arXiv (sin API key)
# ──────────────────────────────────────────────────────────────────────────────

class ArxivEngine:
    """Búsqueda y acceso a papers científicos en arXiv."""

    CATEGORIES = {
        "ia": "cs.AI", "ml": "cs.LG", "nlp": "cs.CL",
        "fisica": "physics", "mate": "math", "bio": "q-bio",
        "economia": "econ", "stat": "stat",
    }

    def search(self, query: str, max_results: int = 8, category: Optional[str] = None) -> Dict:
        ax = _try_import("arxiv", "arxiv")
        if not ax:
            return _err("arxiv no instalado")
        try:
            cat = self.CATEGORIES.get(category or "", category or "")
            search_query = f"cat:{cat} AND ({query})" if cat else query
            client = ax.Client()
            search = ax.Search(query=search_query, max_results=max_results,
                               sort_by=ax.SortCriterion.Relevance)
            results = []
            for r in client.results(search):
                results.append({
                    "id": r.get_short_id(),
                    "title": r.title,
                    "authors": [a.name for a in r.authors[:4]],
                    "abstract": r.summary[:400],
                    "url": r.entry_id,
                    "pdf": r.pdf_url,
                    "published": r.published.strftime("%Y-%m-%d") if r.published else None,
                    "categories": r.categories,
                })
            return _ok(results, count=len(results))
        except Exception as e:
            return _err(str(e))

    def get_paper(self, arxiv_id: str) -> Dict:
        ax = _try_import("arxiv", "arxiv")
        if not ax:
            return _err("arxiv no instalado")
        try:
            client = ax.Client()
            search = ax.Search(id_list=[arxiv_id])
            paper = next(client.results(search))
            return _ok({
                "id": paper.get_short_id(),
                "title": paper.title,
                "authors": [a.name for a in paper.authors],
                "abstract": paper.summary,
                "url": paper.entry_id,
                "pdf": paper.pdf_url,
                "published": paper.published.strftime("%Y-%m-%d") if paper.published else None,
                "updated": paper.updated.strftime("%Y-%m-%d") if paper.updated else None,
                "categories": paper.categories,
                "comment": paper.comment,
                "doi": paper.doi,
            })
        except Exception as e:
            return _err(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 5. CIENCIA — PubMed (biomedicina, sin API key básico)
# ──────────────────────────────────────────────────────────────────────────────

class PubMedEngine:
    """Búsqueda en PubMed (biomedicina, salud)."""

    BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(self):
        self._client = httpx.Client(timeout=20.0)

    def search(self, query: str, max_results: int = 8) -> Dict:
        try:
            r = self._client.get(f"{self.BASE}/esearch.fcgi", params={
                "db": "pubmed", "term": query, "retmax": max_results,
                "retmode": "json", "sort": "relevance",
            })
            r.raise_for_status()
            ids = r.json()["esearchresult"]["idlist"]
            if not ids:
                return _ok([], count=0)
            details = self._fetch_details(ids)
            return _ok(details, count=len(details))
        except Exception as e:
            return _err(str(e))

    def _fetch_details(self, ids: List[str]) -> List[Dict]:
        try:
            r = self._client.get(f"{self.BASE}/esummary.fcgi", params={
                "db": "pubmed", "id": ",".join(ids), "retmode": "json",
            })
            r.raise_for_status()
            uids = r.json()["result"]["uids"]
            result_data = r.json()["result"]
            out = []
            for uid in uids:
                a = result_data[uid]
                out.append({
                    "pmid": uid,
                    "title": a.get("title", ""),
                    "authors": [au.get("name", "") for au in a.get("authors", [])[:5]],
                    "journal": a.get("fulljournalname", ""),
                    "pubdate": a.get("pubdate", ""),
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                    "doi": a.get("elocationid", ""),
                })
            return out
        except Exception:
            return []

    def get_abstract(self, pmid: str) -> Dict:
        try:
            r = self._client.get(f"{self.BASE}/efetch.fcgi", params={
                "db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "text",
            })
            r.raise_for_status()
            return _ok({"pmid": pmid, "abstract": r.text.strip()})
        except Exception as e:
            return _err(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 6. CIENCIA — Semantic Scholar (sin API key)
# ──────────────────────────────────────────────────────────────────────────────

class SemanticScholarEngine:
    """Búsqueda en Semantic Scholar (papers con citas, referencias)."""

    BASE = "https://api.semanticscholar.org/graph/v1"

    def __init__(self):
        self._client = httpx.Client(timeout=20.0, headers={"User-Agent": "ARIA-AI/1.0"})

    def search(self, query: str, limit: int = 8, fields: str = "title,authors,year,abstract,citationCount,url,openAccessPdf") -> Dict:
        try:
            r = self._client.get(f"{self.BASE}/paper/search", params={
                "query": query, "limit": limit, "fields": fields,
            })
            r.raise_for_status()
            papers = r.json().get("data", [])
            out = []
            for p in papers:
                out.append({
                    "id": p.get("paperId"),
                    "title": p.get("title"),
                    "authors": [a.get("name") for a in p.get("authors", [])[:4]],
                    "year": p.get("year"),
                    "abstract": (p.get("abstract") or "")[:400],
                    "citations": p.get("citationCount", 0),
                    "url": p.get("url"),
                    "pdf": (p.get("openAccessPdf") or {}).get("url"),
                })
            return _ok(out, count=len(out))
        except Exception as e:
            return _err(str(e))

    def get_paper(self, paper_id: str) -> Dict:
        try:
            r = self._client.get(f"{self.BASE}/paper/{paper_id}", params={
                "fields": "title,authors,year,abstract,citationCount,references,citations,url,openAccessPdf",
            })
            r.raise_for_status()
            p = r.json()
            return _ok({
                "id": paper_id,
                "title": p.get("title"),
                "authors": [a.get("name") for a in p.get("authors", [])],
                "year": p.get("year"),
                "abstract": p.get("abstract"),
                "citations": p.get("citationCount", 0),
                "url": p.get("url"),
                "references_count": len(p.get("references", [])),
                "top_references": [(r2.get("title"), r2.get("year")) for r2 in p.get("references", [])[:5]],
            })
        except Exception as e:
            return _err(str(e))

    def get_author(self, author_id: str) -> Dict:
        try:
            r = self._client.get(f"{self.BASE}/author/{author_id}", params={
                "fields": "name,affiliations,paperCount,citationCount,hIndex",
            })
            r.raise_for_status()
            return _ok(r.json())
        except Exception as e:
            return _err(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 7. FINANZAS — Yahoo Finance (sin API key)
# ──────────────────────────────────────────────────────────────────────────────

class FinanceEngine:
    """Datos financieros: acciones, ETFs, divisas via Yahoo Finance."""

    def get_ticker(self, symbol: str) -> Dict:
        yf = _try_import("yfinance", "yfinance")
        if not yf:
            return _err("yfinance no instalado")
        try:
            t = yf.Ticker(symbol.upper())
            info = t.info
            return _ok({
                "symbol": symbol.upper(),
                "name": info.get("longName") or info.get("shortName"),
                "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "currency": info.get("currency"),
                "change_pct": info.get("regularMarketChangePercent"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "website": info.get("website"),
                "description": (info.get("longBusinessSummary") or "")[:300],
                "exchange": info.get("exchange"),
                "volume": info.get("regularMarketVolume"),
            })
        except Exception as e:
            return _err(str(e))

    def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> Dict:
        yf = _try_import("yfinance", "yfinance")
        if not yf:
            return _err("yfinance no instalado")
        try:
            t = yf.Ticker(symbol.upper())
            hist = t.history(period=period, interval=interval)
            if hist.empty:
                return _err(f"Sin datos para {symbol}")
            rows = []
            for dt, row in hist.iterrows():
                rows.append({
                    "date": str(dt)[:10],
                    "open": round(row["Open"], 4),
                    "high": round(row["High"], 4),
                    "low": round(row["Low"], 4),
                    "close": round(row["Close"], 4),
                    "volume": int(row.get("Volume", 0)),
                })
            return _ok(rows, symbol=symbol.upper(), period=period, count=len(rows))
        except Exception as e:
            return _err(str(e))

    def compare_tickers(self, symbols: List[str], period: str = "1mo") -> Dict:
        yf = _try_import("yfinance", "yfinance")
        if not yf:
            return _err("yfinance no instalado")
        try:
            out = {}
            for s in symbols:
                t = yf.Ticker(s.upper())
                info = t.info
                out[s.upper()] = {
                    "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                    "change_pct": info.get("regularMarketChangePercent"),
                    "market_cap": info.get("marketCap"),
                    "pe_ratio": info.get("trailingPE"),
                }
            return _ok(out)
        except Exception as e:
            return _err(str(e))

    def search_tickers(self, query: str) -> Dict:
        yf = _try_import("yfinance", "yfinance")
        if not yf:
            return _err("yfinance no instalado")
        try:
            tickers = yf.Search(query)
            return _ok(tickers.quotes[:10] if hasattr(tickers, "quotes") else [])
        except Exception as e:
            return _err(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 8. CRYPTO — CoinGecko (sin API key, gratis)
# ──────────────────────────────────────────────────────────────────────────────

class CryptoEngine:
    """Precios y datos de criptomonedas via CoinGecko."""

    def __init__(self):
        self._client = httpx.Client(timeout=15.0, headers={"accept": "application/json"})
        self._base = "https://api.coingecko.com/api/v3"

    def get_price(self, coins: List[str], vs_currencies: List[str] = None) -> Dict:
        vs = ",".join(vs_currencies or ["usd", "eur"])
        ids = ",".join(coins)
        try:
            r = self._client.get(f"{self._base}/simple/price", params={
                "ids": ids, "vs_currencies": vs,
                "include_24hr_change": "true",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
            })
            r.raise_for_status()
            return _ok(r.json())
        except Exception as e:
            return _err(str(e))

    def top_coins(self, limit: int = 20, vs_currency: str = "usd") -> Dict:
        try:
            r = self._client.get(f"{self._base}/coins/markets", params={
                "vs_currency": vs_currency, "order": "market_cap_desc",
                "per_page": limit, "page": 1, "sparkline": False,
                "price_change_percentage": "1h,24h,7d",
            })
            r.raise_for_status()
            coins = r.json()
            out = [{
                "rank": c["market_cap_rank"],
                "name": c["name"],
                "symbol": c["symbol"].upper(),
                "price": c["current_price"],
                "change_24h": c.get("price_change_percentage_24h"),
                "change_7d": c.get("price_change_percentage_7d_in_currency"),
                "market_cap": c["market_cap"],
                "volume_24h": c["total_volume"],
            } for c in coins]
            return _ok(out, count=len(out))
        except Exception as e:
            return _err(str(e))

    def get_coin_details(self, coin_id: str) -> Dict:
        try:
            r = self._client.get(f"{self._base}/coins/{coin_id}", params={
                "localization": "false", "tickers": "false",
                "community_data": "true", "developer_data": "false",
            })
            r.raise_for_status()
            c = r.json()
            desc = c.get("description", {}).get("en", "")
            return _ok({
                "id": c["id"],
                "name": c["name"],
                "symbol": c["symbol"].upper(),
                "rank": c["market_cap_rank"],
                "description": desc[:400] if desc else "",
                "price_usd": c["market_data"]["current_price"].get("usd"),
                "price_eur": c["market_data"]["current_price"].get("eur"),
                "ath": c["market_data"]["ath"].get("usd"),
                "ath_date": c["market_data"]["ath_date"].get("usd"),
                "market_cap": c["market_data"]["market_cap"].get("usd"),
                "supply": c["market_data"].get("circulating_supply"),
                "max_supply": c["market_data"].get("max_supply"),
                "sentiment_up": c.get("sentiment_votes_up_percentage"),
                "homepage": (c.get("links", {}).get("homepage", [""])[0]),
                "twitter": c.get("links", {}).get("twitter_screen_name"),
                "reddit": c.get("links", {}).get("subreddit_url"),
            })
        except Exception as e:
            return _err(str(e))

    def trending(self) -> Dict:
        try:
            r = self._client.get(f"{self._base}/search/trending")
            r.raise_for_status()
            items = r.json().get("coins", [])
            out = [{"name": i["item"]["name"], "symbol": i["item"]["symbol"],
                    "rank": i["item"]["market_cap_rank"]} for i in items[:10]]
            return _ok(out)
        except Exception as e:
            return _err(str(e))

    def global_market(self) -> Dict:
        try:
            r = self._client.get(f"{self._base}/global")
            r.raise_for_status()
            d = r.json()["data"]
            return _ok({
                "total_market_cap_usd": d["total_market_cap"].get("usd"),
                "total_volume_24h_usd": d["total_volume"].get("usd"),
                "btc_dominance": d.get("market_cap_percentage", {}).get("btc"),
                "eth_dominance": d.get("market_cap_percentage", {}).get("eth"),
                "active_coins": d.get("active_cryptocurrencies"),
                "markets": d.get("markets"),
                "market_cap_change_24h": d.get("market_cap_change_percentage_24h_usd"),
            })
        except Exception as e:
            return _err(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 9. WOLFRAM ALPHA (clave opcional: WOLFRAM_APP_ID)
# ──────────────────────────────────────────────────────────────────────────────

class WolframEngine:
    """Cómputo de conocimiento: matemáticas, física, conversiones, datos."""

    def __init__(self):
        from apps.core.config import settings
        self._app_id = getattr(settings, "WOLFRAM_APP_ID", None) or os.getenv("WOLFRAM_APP_ID")
        self._client = httpx.Client(timeout=20.0)

    def is_configured(self) -> bool:
        return bool(self._app_id)

    def query(self, question: str, units: str = "metric") -> Dict:
        if not self._app_id:
            return _err("WOLFRAM_APP_ID no configurado. Obtén una clave gratis en developer.wolframalpha.com")
        try:
            r = self._client.get("https://api.wolframalpha.com/v2/query", params={
                "input": question, "appid": self._app_id,
                "output": "json", "units": units, "format": "plaintext",
            })
            r.raise_for_status()
            pods = r.json().get("queryresult", {}).get("pods", [])
            results = []
            for pod in pods:
                sub = pod.get("subpods", [{}])[0]
                text = sub.get("plaintext", "").strip()
                if text and pod.get("title") not in ("Input", "Input interpretation"):
                    results.append({"section": pod.get("title"), "answer": text})
            if not results:
                return _err("Sin resultado para esa consulta")
            return _ok(results, question=question)
        except Exception as e:
            return _err(str(e))

    def short_answer(self, question: str) -> Dict:
        if not self._app_id:
            return _err("WOLFRAM_APP_ID no configurado")
        try:
            r = self._client.get("https://api.wolframalpha.com/v1/result", params={
                "input": question, "appid": self._app_id,
            })
            if r.status_code == 200:
                return _ok({"answer": r.text})
            return _err(r.text)
        except Exception as e:
            return _err(str(e))

    def spoken_answer(self, question: str) -> Dict:
        if not self._app_id:
            return _err("WOLFRAM_APP_ID no configurado")
        try:
            r = self._client.get("https://api.wolframalpha.com/v1/spoken", params={
                "input": question, "appid": self._app_id,
            })
            if r.status_code == 200:
                return _ok({"answer": r.text})
            return _err(r.text)
        except Exception as e:
            return _err(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 10. NOTICIAS (GNews + NewsAPI + RSS)
# ──────────────────────────────────────────────────────────────────────────────

class NewsEngine:
    """Noticias de múltiples fuentes: GNews, NewsAPI, RSS."""

    def __init__(self):
        from apps.core.config import settings
        self._news_api_key = getattr(settings, "NEWS_API_KEY", None) or os.getenv("NEWS_API_KEY")
        self._gnews_key = getattr(settings, "GNEWS_API_KEY", None) or os.getenv("GNEWS_API_KEY")
        self._client = httpx.Client(timeout=15.0)

    def gnews(self, query: str, lang: str = "es", country: str = "mx", max_results: int = 8) -> Dict:
        """Google News via GNews (API key opcional, tier gratis disponible)."""
        params: Dict = {"q": query, "lang": lang, "country": country, "max": max_results}
        if self._gnews_key:
            params["apikey"] = self._gnews_key
        try:
            r = self._client.get("https://gnews.io/api/v4/search", params=params)
            r.raise_for_status()
            articles = r.json().get("articles", [])
            out = [{
                "title": a["title"],
                "description": a.get("description", "")[:200],
                "source": a.get("source", {}).get("name"),
                "url": a["url"],
                "published": a.get("publishedAt"),
            } for a in articles]
            return _ok(out, count=len(out))
        except Exception as e:
            return _err(str(e))

    def newsapi(self, query: str, language: str = "es", page_size: int = 8) -> Dict:
        """NewsAPI (requiere NEWS_API_KEY)."""
        if not self._news_api_key:
            return _err("NEWS_API_KEY no configurado")
        try:
            r = self._client.get("https://newsapi.org/v2/everything", params={
                "q": query, "language": language, "pageSize": page_size,
                "sortBy": "publishedAt", "apiKey": self._news_api_key,
            })
            r.raise_for_status()
            articles = r.json().get("articles", [])
            out = [{
                "title": a["title"],
                "description": (a.get("description") or "")[:200],
                "source": a["source"]["name"],
                "url": a["url"],
                "published": a.get("publishedAt"),
                "author": a.get("author"),
            } for a in articles]
            return _ok(out, count=len(out))
        except Exception as e:
            return _err(str(e))

    def rss(self, feed_url: str, limit: int = 10) -> Dict:
        """Parsea cualquier feed RSS/Atom."""
        fp = _try_import("feedparser", "feedparser")
        if not fp:
            return _err("feedparser no instalado")
        try:
            feed = fp.parse(feed_url)
            entries = []
            for e in feed.entries[:limit]:
                entries.append({
                    "title": e.get("title"),
                    "link": e.get("link"),
                    "summary": (e.get("summary") or "")[:300],
                    "published": e.get("published"),
                    "author": e.get("author"),
                })
            return _ok(entries, feed_title=feed.feed.get("title"), count=len(entries))
        except Exception as e:
            return _err(str(e))

    def hackernews_top(self, limit: int = 15) -> Dict:
        """Top stories de HackerNews (sin API key)."""
        try:
            r = self._client.get("https://hacker-news.firebaseio.com/v0/topstories.json")
            r.raise_for_status()
            ids = r.json()[:limit]
            stories = []
            for sid in ids[:limit]:
                sr = self._client.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
                if sr.status_code == 200:
                    d = sr.json()
                    stories.append({
                        "id": sid,
                        "title": d.get("title"),
                        "url": d.get("url"),
                        "score": d.get("score"),
                        "comments": d.get("descendants", 0),
                        "by": d.get("by"),
                    })
            return _ok(stories, count=len(stories))
        except Exception as e:
            return _err(str(e))

    def hackernews_ask(self, limit: int = 10) -> Dict:
        """Ask HN — preguntas de la comunidad."""
        try:
            r = self._client.get("https://hacker-news.firebaseio.com/v0/askstories.json")
            r.raise_for_status()
            ids = r.json()[:limit]
            stories = []
            for sid in ids:
                sr = self._client.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
                if sr.status_code == 200:
                    d = sr.json()
                    stories.append({
                        "title": d.get("title"),
                        "url": f"https://news.ycombinator.com/item?id={sid}",
                        "score": d.get("score"),
                        "text": (d.get("text") or "")[:200],
                        "by": d.get("by"),
                    })
            return _ok(stories, count=len(stories))
        except Exception as e:
            return _err(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 11. CLIMA (wttr.in — sin API key)
# ──────────────────────────────────────────────────────────────────────────────

class WeatherEngine:
    """Datos del clima para cualquier ciudad (sin API key via wttr.in)."""

    def __init__(self):
        self._client = httpx.Client(timeout=10.0)

    def current(self, location: str, lang: str = "es") -> Dict:
        try:
            r = self._client.get(
                f"https://wttr.in/{location}",
                params={"format": "j1", "lang": lang},
            )
            r.raise_for_status()
            d = r.json()
            current = d["current_condition"][0]
            area = d["nearest_area"][0]
            city = area["areaName"][0]["value"]
            country = area["country"][0]["value"]
            return _ok({
                "location": f"{city}, {country}",
                "temp_c": current["temp_C"],
                "temp_f": current["temp_F"],
                "feels_like_c": current["FeelsLikeC"],
                "humidity": current["humidity"],
                "wind_kmph": current["windspeedKmph"],
                "wind_dir": current["winddir16Point"],
                "description": current["weatherDesc"][0]["value"],
                "visibility_km": current["visibility"],
                "uv_index": current["uvIndex"],
                "pressure": current["pressure"],
            })
        except Exception as e:
            return _err(str(e))

    def forecast(self, location: str, days: int = 3) -> Dict:
        try:
            r = self._client.get(
                f"https://wttr.in/{location}",
                params={"format": "j1"},
            )
            r.raise_for_status()
            d = r.json()
            weather = d["weather"][:days]
            out = []
            for w in weather:
                out.append({
                    "date": w["date"],
                    "max_c": w["maxtempC"],
                    "min_c": w["mintempC"],
                    "avg_c": w["avgtempC"],
                    "sunrise": w["astronomy"][0]["sunrise"],
                    "sunset": w["astronomy"][0]["sunset"],
                    "hourly_summary": [
                        {"time": h["time"], "temp_c": h["tempC"], "desc": h["weatherDesc"][0]["value"]}
                        for h in w["hourly"][::2]
                    ],
                })
            return _ok(out, location=location, days=len(out))
        except Exception as e:
            return _err(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 12. DIVISAS / TIPOS DE CAMBIO (sin API key)
# ──────────────────────────────────────────────────────────────────────────────

class CurrencyEngine:
    """Tipos de cambio en tiempo real via exchangerate-api (sin key para datos base)."""

    def __init__(self):
        self._client = httpx.Client(timeout=10.0)
        self._base_url = "https://api.exchangerate-api.com/v4/latest"

    def get_rates(self, base: str = "USD") -> Dict:
        try:
            r = self._client.get(f"{self._base_url}/{base.upper()}")
            r.raise_for_status()
            d = r.json()
            return _ok({
                "base": d["base"],
                "date": d["date"],
                "rates": d["rates"],
            })
        except Exception as e:
            return _err(str(e))

    def convert(self, amount: float, from_currency: str, to_currency: str) -> Dict:
        try:
            r = self._client.get(f"{self._base_url}/{from_currency.upper()}")
            r.raise_for_status()
            rates = r.json()["rates"]
            to = to_currency.upper()
            if to not in rates:
                return _err(f"Divisa no encontrada: {to}")
            converted = amount * rates[to]
            return _ok({
                "from": from_currency.upper(),
                "to": to,
                "amount": amount,
                "result": round(converted, 6),
                "rate": rates[to],
            })
        except Exception as e:
            return _err(str(e))

    def compare(self, base: str, currencies: List[str]) -> Dict:
        try:
            r = self._client.get(f"{self._base_url}/{base.upper()}")
            r.raise_for_status()
            all_rates = r.json()["rates"]
            selected = {c.upper(): all_rates.get(c.upper()) for c in currencies}
            return _ok(selected, base=base.upper())
        except Exception as e:
            return _err(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 13. REDDIT (sin API key — lectura pública)
# ──────────────────────────────────────────────────────────────────────────────

class RedditEngine:
    """Lee posts y comentarios de Reddit sin API key."""

    def __init__(self):
        self._client = httpx.Client(
            timeout=15.0,
            headers={"User-Agent": "ARIA-AI/1.0 (knowledge engine)"},
        )

    def subreddit_hot(self, subreddit: str, limit: int = 10) -> Dict:
        try:
            r = self._client.get(
                f"https://www.reddit.com/r/{subreddit}/hot.json",
                params={"limit": limit},
            )
            r.raise_for_status()
            posts = r.json()["data"]["children"]
            out = [{
                "title": p["data"]["title"],
                "score": p["data"]["score"],
                "comments": p["data"]["num_comments"],
                "url": p["data"]["url"],
                "permalink": f"https://reddit.com{p['data']['permalink']}",
                "author": p["data"]["author"],
                "flair": p["data"].get("link_flair_text"),
                "selftext": (p["data"].get("selftext") or "")[:300],
            } for p in posts]
            return _ok(out, subreddit=subreddit, count=len(out))
        except Exception as e:
            return _err(str(e))

    def search(self, query: str, subreddit: Optional[str] = None, limit: int = 10, sort: str = "relevance") -> Dict:
        try:
            base = f"https://www.reddit.com/r/{subreddit}/search.json" if subreddit else "https://www.reddit.com/search.json"
            params: Dict = {"q": query, "limit": limit, "sort": sort, "t": "month"}
            if not subreddit:
                params["restrict_sr"] = "false"
            r = self._client.get(base, params=params)
            r.raise_for_status()
            posts = r.json()["data"]["children"]
            out = [{
                "title": p["data"]["title"],
                "subreddit": p["data"]["subreddit"],
                "score": p["data"]["score"],
                "url": p["data"]["url"],
                "permalink": f"https://reddit.com{p['data']['permalink']}",
                "selftext": (p["data"].get("selftext") or "")[:300],
            } for p in posts]
            return _ok(out, count=len(out))
        except Exception as e:
            return _err(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 14. RAG / MEMORIA VECTORIAL — ChromaDB + Sentence Transformers
# ──────────────────────────────────────────────────────────────────────────────

class VectorMemoryEngine:
    """
    Motor de memoria vectorial local (ChromaDB + Sentence Transformers).
    Permite a Aria recordar documentos, indexarlos y buscar por similitud semántica.
    Directorio de datos: /data/chroma (configurable via CHROMA_PERSIST_DIR).
    """

    def __init__(self, collection_name: str = "aria_knowledge"):
        self.collection_name = collection_name
        self._chroma = None
        self._encoder = None
        self._collection = None
        self._persist_dir = os.getenv("CHROMA_PERSIST_DIR", "/data/chroma")

    def _get_chroma(self):
        if self._chroma is None:
            chromadb = _try_import("chromadb", "chromadb")
            if not chromadb:
                raise ImportError("chromadb no instalado")
            import chromadb as chroma_mod
            self._chroma = chroma_mod.PersistentClient(path=self._persist_dir)
            self._collection = self._chroma.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._chroma, self._collection

    def _get_encoder(self):
        if self._encoder is None:
            st = _try_import("sentence_transformers", "sentence-transformers")
            if not st:
                raise ImportError("sentence-transformers no instalado")
            from sentence_transformers import SentenceTransformer
            self._encoder = SentenceTransformer("all-MiniLM-L6-v2")
        return self._encoder

    def is_configured(self) -> bool:
        try:
            _get = _try_import("chromadb", "chromadb")
            st = _try_import("sentence_transformers", "sentence-transformers")
            return _get is not None and st is not None
        except Exception:
            return False

    def add_document(self, doc_id: str, text: str, metadata: Optional[Dict] = None) -> Dict:
        try:
            _, collection = self._get_chroma()
            encoder = self._get_encoder()
            embedding = encoder.encode([text])[0].tolist()
            collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[text],
                metadatas=[metadata or {}],
            )
            return _ok({"id": doc_id, "chars": len(text)})
        except Exception as e:
            return _err(str(e))

    def add_documents_bulk(self, documents: List[Dict]) -> Dict:
        """documents: lista de {id, text, metadata?}"""
        try:
            _, collection = self._get_chroma()
            encoder = self._get_encoder()
            ids = [d["id"] for d in documents]
            texts = [d["text"] for d in documents]
            metas = [d.get("metadata", {}) for d in documents]
            embeddings = encoder.encode(texts).tolist()
            collection.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metas)
            return _ok({"added": len(ids)})
        except Exception as e:
            return _err(str(e))

    def search(self, query: str, n_results: int = 5, where: Optional[Dict] = None) -> Dict:
        try:
            _, collection = self._get_chroma()
            encoder = self._get_encoder()
            q_embedding = encoder.encode([query])[0].tolist()
            params: Dict = {"query_embeddings": [q_embedding], "n_results": n_results}
            if where:
                params["where"] = where
            results = collection.query(**params)
            out = []
            for i, doc in enumerate(results["documents"][0]):
                out.append({
                    "id": results["ids"][0][i],
                    "text": doc[:500],
                    "distance": results["distances"][0][i],
                    "metadata": results["metadatas"][0][i],
                })
            return _ok(out, query=query, count=len(out))
        except Exception as e:
            return _err(str(e))

    def delete_document(self, doc_id: str) -> Dict:
        try:
            _, collection = self._get_chroma()
            collection.delete(ids=[doc_id])
            return _ok({"deleted": doc_id})
        except Exception as e:
            return _err(str(e))

    def list_documents(self, limit: int = 20) -> Dict:
        try:
            _, collection = self._get_chroma()
            data = collection.get(limit=limit, include=["documents", "metadatas"])
            out = [{"id": i, "preview": (d or "")[:100], "metadata": m}
                   for i, d, m in zip(data["ids"], data["documents"], data["metadatas"])]
            return _ok(out, count=len(out), total=collection.count())
        except Exception as e:
            return _err(str(e))

    def collection_stats(self) -> Dict:
        try:
            _, collection = self._get_chroma()
            return _ok({"collection": self.collection_name, "documents": collection.count()})
        except Exception as e:
            return _err(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 15. ALPHA VANTAGE — Indicadores económicos y fondamentales (clave opcional)
# ──────────────────────────────────────────────────────────────────────────────

class AlphaVantageEngine:
    """Indicadores financieros avanzados via Alpha Vantage (clave gratuita disponible)."""

    BASE = "https://www.alphavantage.co/query"

    def __init__(self):
        from apps.core.config import settings
        self._key = getattr(settings, "ALPHA_VANTAGE_KEY", None) or os.getenv("ALPHA_VANTAGE_KEY")
        self._client = httpx.Client(timeout=15.0)

    def is_configured(self) -> bool:
        return bool(self._key)

    def _get(self, function: str, **params) -> Dict:
        if not self._key:
            return _err("ALPHA_VANTAGE_KEY no configurado. Gratis en alphavantage.co")
        try:
            r = self._client.get(self.BASE, params={"function": function, "apikey": self._key, **params})
            r.raise_for_status()
            d = r.json()
            if "Error Message" in d:
                return _err(d["Error Message"])
            if "Note" in d:
                return _err("Límite de rate de Alpha Vantage alcanzado (5/min en tier gratuito)")
            return _ok(d)
        except Exception as e:
            return _err(str(e))

    def quote(self, symbol: str) -> Dict:
        r = self._get("GLOBAL_QUOTE", symbol=symbol)
        if not r["success"]:
            return r
        q = r["data"].get("Global Quote", {})
        return _ok({
            "symbol": q.get("01. symbol"),
            "price": q.get("05. price"),
            "change": q.get("09. change"),
            "change_pct": q.get("10. change percent"),
            "volume": q.get("06. volume"),
            "prev_close": q.get("08. previous close"),
            "open": q.get("02. open"),
            "high": q.get("03. high"),
            "low": q.get("04. low"),
        })

    def forex(self, from_currency: str, to_currency: str) -> Dict:
        r = self._get("CURRENCY_EXCHANGE_RATE",
                      from_currency=from_currency.upper(),
                      to_currency=to_currency.upper())
        if not r["success"]:
            return r
        data = r["data"].get("Realtime Currency Exchange Rate", {})
        return _ok({
            "from": data.get("1. From_Currency Code"),
            "to": data.get("3. To_Currency Code"),
            "rate": data.get("5. Exchange Rate"),
            "last_updated": data.get("6. Last Refreshed"),
        })

    def company_overview(self, symbol: str) -> Dict:
        r = self._get("OVERVIEW", symbol=symbol)
        if not r["success"]:
            return r
        d = r["data"]
        return _ok({
            "name": d.get("Name"),
            "sector": d.get("Sector"),
            "industry": d.get("Industry"),
            "description": (d.get("Description") or "")[:400],
            "employees": d.get("FullTimeEmployees"),
            "market_cap": d.get("MarketCapitalization"),
            "pe_ratio": d.get("PERatio"),
            "eps": d.get("EPS"),
            "dividend_yield": d.get("DividendYield"),
            "52w_high": d.get("52WeekHigh"),
            "52w_low": d.get("52WeekLow"),
            "analyst_target": d.get("AnalystTargetPrice"),
        })

    def economic_indicator(self, indicator: str = "REAL_GDP") -> Dict:
        """Indicadores: REAL_GDP, REAL_GDP_PER_CAPITA, FEDERAL_FUNDS_RATE, CPI, INFLATION, UNEMPLOYMENT."""
        return self._get(indicator)


# ──────────────────────────────────────────────────────────────────────────────
# SUITE PRINCIPAL — punto de entrada unificado
# ──────────────────────────────────────────────────────────────────────────────

class KnowledgeSuite:
    """
    Suite unificada de conocimiento de ARIA.
    Agrupa todos los motores en una sola interfaz.
    """

    def __init__(self):
        self.web = WebSearchEngine()
        self.wikipedia = WikipediaEngine()
        self.extractor = WebContentExtractor()
        self.arxiv = ArxivEngine()
        self.pubmed = PubMedEngine()
        self.scholar = SemanticScholarEngine()
        self.finance = FinanceEngine()
        self.crypto = CryptoEngine()
        self.wolfram = WolframEngine()
        self.news = NewsEngine()
        self.weather = WeatherEngine()
        self.currency = CurrencyEngine()
        self.reddit = RedditEngine()
        self.vector_memory = VectorMemoryEngine()
        self.alpha_vantage = AlphaVantageEngine()

    def status(self) -> Dict:
        """Devuelve qué motores están activos y cuáles necesitan configuración."""
        engines = {
            "web_search (DuckDuckGo)": True,
            "wikipedia": True,
            "web_extractor (trafilatura)": _try_import("trafilatura", "") is not None,
            "arxiv": _try_import("arxiv", "") is not None,
            "pubmed": True,
            "semantic_scholar": True,
            "finance (yfinance)": _try_import("yfinance", "") is not None,
            "crypto (CoinGecko)": True,
            "wolfram_alpha": self.wolfram.is_configured(),
            "news (GNews/NewsAPI)": True,
            "weather (wttr.in)": True,
            "currency": True,
            "reddit": True,
            "vector_memory": self.vector_memory.is_configured(),
            "alpha_vantage": self.alpha_vantage.is_configured(),
        }
        active = sum(1 for v in engines.values() if v)
        return {
            "active": active,
            "total": len(engines),
            "engines": engines,
            "needs_config": {
                "WOLFRAM_APP_ID": not self.wolfram.is_configured(),
                "ALPHA_VANTAGE_KEY": not self.alpha_vantage.is_configured(),
                "NEWS_API_KEY": not bool(os.getenv("NEWS_API_KEY")),
                "GNEWS_API_KEY": not bool(os.getenv("GNEWS_API_KEY")),
            },
        }

    def quick_research(self, query: str) -> Dict:
        """Investigación rápida: busca en web, Wikipedia y noticias a la vez."""
        web_r = self.web.search(query, max_results=5)
        wiki_r = self.wikipedia.summary(query, sentences=3)
        news_r = self.news.hackernews_top(limit=5)
        return {
            "success": True,
            "query": query,
            "web": web_r.get("data", []),
            "wikipedia": wiki_r.get("data"),
            "hackernews": news_r.get("data", []),
        }


_suite: Optional[KnowledgeSuite] = None


def get_knowledge_suite() -> KnowledgeSuite:
    global _suite
    if _suite is None:
        _suite = KnowledgeSuite()
    return _suite
