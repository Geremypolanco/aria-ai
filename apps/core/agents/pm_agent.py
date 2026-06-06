"""
pm_agent.py — Project Manager Agent con Google Suite + HuggingFace Suite.
Investigación de mercado completa: web, YouTube, libros, tendencias, NLP, imágenes.
"""
from __future__ import annotations
import logging
from typing import Any
from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.pm_agent")


class PMAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="pm",
            description="Investigación de mercado y gestión de proyectos — análisis completo con Google + HuggingFace",
            capabilities=[
                "market_research", "competitor_analysis", "niche_validation",
                "trend_analysis", "product_ideation", "content_strategy",
                "sentiment_analysis", "image_analysis", "multilingual_research",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context.get("task", "")
        niche = context.get("niche", "digital products")
        language = context.get("language", "es")
        deep_research = context.get("deep_research", True)

        results: dict[str, Any] = {"success": True, "agent": "pm_agent", "niche": niche}

        # ── 1. Investigación de mercado completa con Google Suite
        market_data = await self._deep_market_research(niche, language)
        results["market_research"] = market_data

        # ── 2. Análisis de sentimiento del mercado con HuggingFace
        if deep_research:
            sentiment_data = await self._analyze_market_sentiment(market_data, niche)
            results["market_sentiment"] = sentiment_data

        # ── 3. Oportunidades de nicho con YouTube + NER
        opportunities = await self._find_opportunities(niche, market_data)
        results["opportunities"] = opportunities

        # ── 4. Síntesis final con IA
        strategy = await self._generate_strategy(niche, task, results)
        results["strategy"] = strategy

        # ── 5. Guardar en Supabase
        await self._save_research(niche, results)
        await self._log("market_research_complete", f"Nicho: {niche} | Tendencias: {len(market_data.get('trending_topics',[]))}")

        return results

    async def _deep_market_research(self, niche: str, language: str) -> dict[str, Any]:
        """Investigación completa usando TODAS las APIs de Google."""
        import asyncio
        try:
            from apps.core.tools.google_suite import GoogleSuite
            google = GoogleSuite()

            # Ejecutar todas las búsquedas en paralelo
            market_task   = google.full_market_research(niche, language)
            trends_rt     = google.trends_realtime("US")
            kg_task       = google.knowledge_graph_search(niche)
            books_task    = google.books_search(f"{niche} business", max_results=5)
            yt_trending   = google.youtube_trending("US")

            market, trends_rt_r, kg, books, yt_trend = await asyncio.gather(
                market_task, trends_rt, kg_task, books_task, yt_trending,
                return_exceptions=True,
            )

            # Enriquecer con NLP si hay datos web
            web_text = " ".join([r.get("snippet","") for r in (market.get("web_results",[]) if isinstance(market,dict) else [])[:5]])
            nlp = {}
            if web_text:
                nlp = await google.nlp_analyze(web_text[:3000])

            return {
                "market_overview": market if isinstance(market, dict) else {},
                "realtime_trends": trends_rt_r.get("realtime_trends",[])[:10] if isinstance(trends_rt_r,dict) else [],
                "trending_topics": market.get("trending_topics",[]) if isinstance(market,dict) else [],
                "knowledge_graph": kg.get("entities",[]) if isinstance(kg,dict) else [],
                "relevant_books": books.get("books",[])[:3] if isinstance(books,dict) else [],
                "trending_videos": yt_trend.get("trending",[])[:10] if isinstance(yt_trend,dict) else [],
                "nlp_entities": nlp.get("entities",[]) if isinstance(nlp,dict) else [],
                "nlp_categories": nlp.get("categories",[]) if isinstance(nlp,dict) else [],
                "nlp_sentiment": nlp.get("sentiment",{}) if isinstance(nlp,dict) else {},
            }
        except Exception as exc:
            logger.error("[PMAgent] market research error: %s", exc)
            return {"error": str(exc)}

    async def _analyze_market_sentiment(self, market_data: dict, niche: str) -> dict[str, Any]:
        """Analiza el sentimiento del mercado con HuggingFace."""
        try:
            from apps.core.tools.huggingface_suite import HuggingFaceSuite
            hf = HuggingFaceSuite()

            # Recopilar textos del mercado
            texts = []
            for item in market_data.get("market_overview",{}).get("web_results",[])[:5]:
                if item.get("snippet"):
                    texts.append(item["snippet"])
            for video in market_data.get("trending_videos",[])[:3]:
                if video.get("title"):
                    texts.append(video["title"])

            if not texts:
                return {"error": "Sin textos para analizar"}

            return await hf.analyze_market_sentiment(niche, texts)
        except Exception as exc:
            logger.error("[PMAgent] sentiment error: %s", exc)
            return {"error": str(exc)}

    async def _find_opportunities(self, niche: str, market_data: dict) -> list[dict]:
        """Encuentra oportunidades de productos usando clasificación zero-shot + YouTube."""
        import asyncio
        opportunities = []
        try:
            from apps.core.tools.google_suite import GoogleSuite
            from apps.core.tools.huggingface_suite import HuggingFaceSuite
            google = GoogleSuite()
            hf = HuggingFaceSuite()

            # Buscar videos de alto rendimiento sobre el nicho
            yt_search = await google.youtube_search(
                f"best {niche} products 2025 review", max_results=10, order="viewCount"
            )

            if yt_search.get("success") and yt_search.get("results"):
                # Obtener stats de los top videos
                video_ids = [v["id"] for v in yt_search["results"][:5] if v.get("id")]
                if video_ids:
                    video_stats = await google.youtube_video_details(video_ids)
                    if video_stats.get("success"):
                        for v in video_stats.get("videos",[])[:5]:
                            # Clasificar si es oportunidad real
                            cls = await hf.classify_zero_shot(
                                v.get("title",""),
                                ["high demand product", "tutorial only", "review comparison", "affiliate marketing", "low demand"],
                            )
                            opportunities.append({
                                "source": "youtube",
                                "title": v.get("title",""),
                                "views": v.get("views",0),
                                "tags": v.get("tags",[])[:5],
                                "opportunity_type": cls.get("best_label","") if isinstance(cls,dict) else "",
                                "opportunity_score": cls.get("best_score",0) if isinstance(cls,dict) else 0,
                            })
        except Exception as exc:
            logger.error("[PMAgent] find_opportunities error: %s", exc)

        return opportunities[:10]

    async def _generate_strategy(self, niche: str, task: str, data: dict) -> dict[str, Any]:
        """Genera estrategia final con todos los datos recopilados."""
        context_summary = {
            "trending_topics": data.get("market_research",{}).get("trending_topics",[])[:5],
            "sentiment": data.get("market_sentiment",{}).get("overall",""),
            "top_opportunities": data.get("opportunities",[])[:3],
            "nlp_entities": data.get("market_research",{}).get("nlp_entities",[])[:5],
        }

        strategy_prompt = (
            f"Como PM experto en productos digitales, analiza estos datos de mercado y genera una estrategia:\n"
            f"Nicho: {niche}\n"
            f"Tarea: {task}\n"
            f"Datos: {context_summary}\n\n"
            "Genera un JSON con:\n"
            "- top_3_products: [3 ideas de productos digitales para crear]\n"
            "- target_audience: descripción del público objetivo\n"
            "- pricing_strategy: rango de precios recomendado\n"
            "- content_angles: [3 ángulos de contenido únicos]\n"
            "- risk_level: bajo/medio/alto\n"
            "- expected_revenue_month1: estimación primer mes en USD"
        )

        response = await self.think(
            system="Eres un PM experto en productos digitales. Responde SOLO con JSON válido.",
            user=strategy_prompt,
            model=AIModel.ANALYTICAL,
        )

        try:
            import json, re
            match = re.search(r"\{.*\}", response or "", re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return {"raw": response}

    async def _save_research(self, niche: str, data: dict) -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            await db.save_niche_analysis(
                niche=niche,
                score=75,
                metadata={k: str(v)[:500] for k, v in data.items() if k != "strategy"},
            )
        except Exception as exc:
            logger.warning("[PMAgent] Error guardando: %s", exc)
