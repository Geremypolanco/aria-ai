"""
google_suite.py — Suite completa de Google APIs para ARIA AI.

APIs integradas (todas con GOOGLE_API_KEY):
  - Custom Search API (búsqueda web + imágenes)
  - Cloud Vision API (análisis de imágenes, OCR, etiquetas, objetos, logos)
  - Cloud Natural Language API (sentimiento, entidades, categorías, sintaxis)
  - Cloud Translation API (100+ idiomas bidireccional)
  - Cloud Text-to-Speech API (voces neuronales en múltiples idiomas)
  - Cloud Speech-to-Text API (transcripción de audio)
  - YouTube Data API v3 (búsqueda, stats, comentarios, canales, playlists)
  - Books API (búsqueda de libros)
  - Knowledge Graph Search API (entidades del Knowledge Graph)
  - PageSpeed Insights API (análisis de velocidad y SEO)
  - Fact Check Tools API (verificación de hechos)
  - Google Trends via RSS (sin key requerida)
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.google_suite")
BASE = "https://www.googleapis.com"


class GoogleSuite:
    """Suite completa de APIs de Google para ARIA AI."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)
        self._key = settings.GOOGLE_API_KEY

    def _ok(self) -> bool:
        return bool(self._key)

    def _p(self, extra: dict | None = None) -> dict:
        """Params base con API key."""
        params = {"key": self._key}
        if extra:
            params.update(extra)
        return params

    # ══════════════════════════════════════════════════════════════
    # 1. CUSTOM SEARCH API — Búsqueda web e imágenes
    # ══════════════════════════════════════════════════════════════

    async def web_search(
        self,
        query: str,
        num: int = 10,
        language: str = "es",
        country: str = "US",
        site_restrict: str = "",
    ) -> dict[str, Any]:
        """Búsqueda web completa via Google Custom Search."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            params = {
                "key": self._key,
                "cx": "017576662512468239146:omuauf_lfve",  # Google public CSE
                "q": query,
                "num": min(num, 10),
                "lr": f"lang_{language}",
                "gl": country,
                "safe": "active",
            }
            if site_restrict:
                params["siteSearch"] = site_restrict
            res = await self._http.get(f"{BASE}/customsearch/v1", params=params)
            if res.status_code == 200:
                data = res.json()
                items = data.get("items", [])
                return {
                    "success": True,
                    "query": query,
                    "total_results": data.get("searchInformation", {}).get("totalResults", "0"),
                    "results": [
                        {
                            "title": i.get("title", ""),
                            "url": i.get("link", ""),
                            "snippet": i.get("snippet", ""),
                            "domain": i.get("displayLink", ""),
                        }
                        for i in items
                    ],
                }
            # Fallback: use SerpAPI if configured
            return await self._serp_fallback(query, num)
        except Exception as exc:
            logger.error("[GoogleSuite] web_search error: %s", exc)
            return await self._serp_fallback(query, num)

    async def _serp_fallback(self, query: str, num: int = 10) -> dict[str, Any]:
        """Fallback a SerpAPI si Custom Search falla."""
        if not settings.SERP_API_KEY:
            return {"success": False, "error": "Custom Search y SerpAPI no disponibles"}
        try:
            res = await self._http.get(
                "https://serpapi.com/search",
                params={"q": query, "num": num, "api_key": settings.SERP_API_KEY},
            )
            if res.status_code == 200:
                data = res.json()
                results = [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("link", ""),
                        "snippet": r.get("snippet", ""),
                    }
                    for r in data.get("organic_results", [])[:num]
                ]
                return {"success": True, "query": query, "results": results, "source": "serpapi"}
        except Exception:
            pass
        return {"success": False, "error": "Búsqueda web no disponible"}

    async def image_search(self, query: str, num: int = 10) -> dict[str, Any]:
        """Búsqueda de imágenes via Custom Search."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            params = {
                "key": self._key,
                "cx": "017576662512468239146:omuauf_lfve",
                "q": query,
                "searchType": "image",
                "num": min(num, 10),
                "safe": "active",
            }
            res = await self._http.get(f"{BASE}/customsearch/v1", params=params)
            if res.status_code == 200:
                items = res.json().get("items", [])
                return {
                    "success": True,
                    "images": [
                        {
                            "title": i.get("title", ""),
                            "url": i.get("link", ""),
                            "thumbnail": i.get("image", {}).get("thumbnailLink", ""),
                            "width": i.get("image", {}).get("width", 0),
                            "height": i.get("image", {}).get("height", 0),
                            "source": i.get("displayLink", ""),
                        }
                        for i in items
                    ],
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 2. CLOUD VISION API — Análisis completo de imágenes
    # ══════════════════════════════════════════════════════════════

    async def vision_analyze(
        self,
        image_url: str = "",
        image_bytes: bytes = b"",
        features: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Análisis completo de imagen con Vision API.
        Features disponibles: LABEL_DETECTION, TEXT_DETECTION, OBJECT_LOCALIZATION,
        FACE_DETECTION, LOGO_DETECTION, IMAGE_PROPERTIES, SAFE_SEARCH_DETECTION,
        LANDMARK_DETECTION, WEB_DETECTION, DOCUMENT_TEXT_DETECTION
        """
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        if not features:
            features = [
                "LABEL_DETECTION",
                "TEXT_DETECTION",
                "OBJECT_LOCALIZATION",
                "WEB_DETECTION",
                "IMAGE_PROPERTIES",
            ]
        try:
            image_payload: dict[str, Any] = {}
            if image_url:
                image_payload["source"] = {"imageUri": image_url}
            elif image_bytes:
                image_payload["content"] = base64.b64encode(image_bytes).decode()
            else:
                return {"success": False, "error": "Se requiere image_url o image_bytes"}

            body = {
                "requests": [
                    {
                        "image": image_payload,
                        "features": [{"type": f, "maxResults": 15} for f in features],
                    }
                ]
            }
            res = await self._http.post(
                f"{BASE}/vision/v1/images:annotate",
                params={"key": self._key},
                json=body,
            )
            if res.status_code == 200:
                r = (res.json().get("responses") or [{}])[0]
                result: dict[str, Any] = {"success": True}

                # Labels (objetos detectados)
                if "labelAnnotations" in r:
                    result["labels"] = [
                        {"label": l["description"], "confidence": round(l["score"], 3)}
                        for l in r["labelAnnotations"][:10]
                    ]
                # Texto detectado (OCR)
                if "textAnnotations" in r:
                    result["full_text"] = (
                        r["textAnnotations"][0]["description"] if r["textAnnotations"] else ""
                    )
                    result["text_blocks"] = [t["description"] for t in r["textAnnotations"][1:5]]
                # Objetos localizados
                if "localizedObjectAnnotations" in r:
                    result["objects"] = [
                        {"name": o["name"], "confidence": round(o["score"], 3)}
                        for o in r["localizedObjectAnnotations"][:10]
                    ]
                # Logos
                if "logoAnnotations" in r:
                    result["logos"] = [l["description"] for l in r["logoAnnotations"]]
                # Web detection (páginas similares)
                if "webDetection" in r:
                    web = r["webDetection"]
                    result["web_entities"] = [
                        e["description"] for e in web.get("webEntities", [])[:5]
                    ]
                    result["similar_images"] = [
                        p["url"] for p in web.get("fullMatchingImages", [])[:3]
                    ]
                # Propiedades de imagen
                if "imagePropertiesAnnotation" in r:
                    colors = (
                        r["imagePropertiesAnnotation"].get("dominantColors", {}).get("colors", [])
                    )
                    result["dominant_colors"] = [
                        {
                            "rgb": f"#{int(c['color'].get('red',0)):02x}{int(c['color'].get('green',0)):02x}{int(c['color'].get('blue',0)):02x}",
                            "score": round(c.get("score", 0), 3),
                        }
                        for c in colors[:5]
                    ]
                # Safe search
                if "safeSearchAnnotation" in r:
                    result["safe_search"] = r["safeSearchAnnotation"]

                return result
            return {
                "success": False,
                "error": f"Vision API HTTP {res.status_code}: {res.text[:200]}",
            }
        except Exception as exc:
            logger.error("[GoogleSuite] vision_analyze error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def vision_ocr(self, image_url: str = "", image_bytes: bytes = b"") -> dict[str, Any]:
        """Extrae texto de una imagen (OCR)."""
        result = await self.vision_analyze(
            image_url=image_url, image_bytes=image_bytes, features=["DOCUMENT_TEXT_DETECTION"]
        )
        return {"success": result.get("success", False), "text": result.get("full_text", "")}

    # ══════════════════════════════════════════════════════════════
    # 3. CLOUD NATURAL LANGUAGE API — NLP completo
    # ══════════════════════════════════════════════════════════════

    async def nlp_analyze(self, text: str, language: str = "") -> dict[str, Any]:
        """Análisis NLP completo: sentimiento, entidades, categorías, sintaxis."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            doc = {"content": text, "type": "PLAIN_TEXT"}
            if language:
                doc["language"] = language

            # Ejecutar los 3 análisis en paralelo
            import asyncio

            sentiment_task = self._nlp_request("analyzeSentiment", doc)
            entities_task = self._nlp_request("analyzeEntities", doc)
            categories_task = self._nlp_request("classifyText", doc if len(text) > 20 else None)

            sentiment_r, entities_r, categories_r = await asyncio.gather(
                sentiment_task, entities_task, categories_task, return_exceptions=True
            )

            result: dict[str, Any] = {"success": True, "text_length": len(text)}

            if isinstance(sentiment_r, dict) and "documentSentiment" in sentiment_r:
                s = sentiment_r["documentSentiment"]
                result["sentiment"] = {
                    "score": round(s.get("score", 0), 3),
                    "magnitude": round(s.get("magnitude", 0), 3),
                    "label": (
                        "positivo"
                        if s.get("score", 0) > 0.1
                        else "negativo" if s.get("score", 0) < -0.1 else "neutro"
                    ),
                }

            if isinstance(entities_r, dict) and "entities" in entities_r:
                result["entities"] = [
                    {
                        "name": e["name"],
                        "type": e.get("type", "UNKNOWN"),
                        "salience": round(e.get("salience", 0), 3),
                        "wikipedia": e.get("metadata", {}).get("wikipedia_url", ""),
                    }
                    for e in entities_r["entities"][:10]
                ]

            if isinstance(categories_r, dict) and "categories" in categories_r:
                result["categories"] = [
                    {"name": c["name"], "confidence": round(c.get("confidence", 0), 3)}
                    for c in categories_r["categories"][:5]
                ]

            return result
        except Exception as exc:
            logger.error("[GoogleSuite] nlp_analyze error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def _nlp_request(self, endpoint: str, doc: dict | None) -> dict:
        if not doc:
            return {}
        res = await self._http.post(
            f"https://language.googleapis.com/v1/documents:{endpoint}",
            params={"key": self._key},
            json={"document": doc, "encodingType": "UTF8"},
        )
        return res.json() if res.status_code == 200 else {}

    async def analyze_sentiment(self, text: str) -> dict[str, Any]:
        """Análisis de sentimiento rápido."""
        r = await self.nlp_analyze(text)
        return {"success": r.get("success"), "sentiment": r.get("sentiment", {})}

    async def extract_entities(self, text: str) -> dict[str, Any]:
        """Extrae entidades nombradas (personas, lugares, organizaciones)."""
        r = await self.nlp_analyze(text)
        return {"success": r.get("success"), "entities": r.get("entities", [])}

    async def classify_content(self, text: str) -> dict[str, Any]:
        """Clasifica contenido en categorías de Google (1000+ categorías)."""
        r = await self.nlp_analyze(text)
        return {"success": r.get("success"), "categories": r.get("categories", [])}

    # ══════════════════════════════════════════════════════════════
    # 4. CLOUD TRANSLATION API — 133 idiomas
    # ══════════════════════════════════════════════════════════════

    async def translate(self, text: str, target: str, source: str = "") -> dict[str, Any]:
        """Traduce texto a cualquiera de los 133 idiomas soportados."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            body: dict[str, Any] = {"q": text, "target": target, "format": "text"}
            if source:
                body["source"] = source
            res = await self._http.post(
                f"{BASE}/language/translate/v2",
                params={"key": self._key},
                json=body,
            )
            if res.status_code == 200:
                t = (res.json().get("data", {}).get("translations") or [{}])[0]
                return {
                    "success": True,
                    "translated": t.get("translatedText", ""),
                    "source_language": t.get("detectedSourceLanguage", source),
                    "target_language": target,
                }
            return {"success": False, "error": f"HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def detect_language(self, text: str) -> dict[str, Any]:
        """Detecta el idioma de un texto."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            res = await self._http.post(
                f"{BASE}/language/translate/v2/detect",
                params={"key": self._key},
                json={"q": text},
            )
            if res.status_code == 200:
                d = (res.json().get("data", {}).get("detections") or [[{}]])[0][0]
                return {
                    "success": True,
                    "language": d.get("language", ""),
                    "confidence": round(d.get("confidence", 0), 3),
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def translate_batch(self, texts: list[str], target: str) -> list[str]:
        """Traduce una lista de textos al idioma destino."""
        import asyncio

        tasks = [self.translate(t, target) for t in texts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [
            r.get("translated", t) if isinstance(r, dict) and r.get("success") else t
            for r, t in zip(results, texts, strict=False)
        ]

    async def translate_content_multilang(self, text: str, targets: list[str]) -> dict[str, str]:
        """Traduce texto a múltiples idiomas simultáneamente."""
        import asyncio

        tasks = [self.translate(text, lang) for lang in targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            lang: (r.get("translated", "") if isinstance(r, dict) and r.get("success") else "")
            for lang, r in zip(targets, results, strict=False)
        }

    # ══════════════════════════════════════════════════════════════
    # 5. CLOUD TEXT-TO-SPEECH API — Voces neuronales
    # ══════════════════════════════════════════════════════════════

    async def text_to_speech(
        self,
        text: str,
        language_code: str = "es-ES",
        voice_name: str = "es-ES-Neural2-A",
        speaking_rate: float = 1.0,
        pitch: float = 0.0,
    ) -> dict[str, Any]:
        """Convierte texto a voz con voces neuronales de Google."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            body = {
                "input": {"text": text[:5000]},
                "voice": {"languageCode": language_code, "name": voice_name},
                "audioConfig": {
                    "audioEncoding": "MP3",
                    "speakingRate": speaking_rate,
                    "pitch": pitch,
                },
            }
            res = await self._http.post(
                "https://texttospeech.googleapis.com/v1/text:synthesize",
                params={"key": self._key},
                json=body,
            )
            if res.status_code == 200:
                audio_b64 = res.json().get("audioContent", "")
                audio_bytes = base64.b64decode(audio_b64)
                return {
                    "success": True,
                    "audio_bytes": audio_bytes,
                    "format": "mp3",
                    "language": language_code,
                    "voice": voice_name,
                }
            return {"success": False, "error": f"TTS HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            logger.error("[GoogleSuite] tts error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def list_tts_voices(self, language_code: str = "") -> dict[str, Any]:
        """Lista todas las voces disponibles (400+ voces en 50+ idiomas)."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            params = {"key": self._key}
            if language_code:
                params["languageCode"] = language_code
            res = await self._http.get(
                "https://texttospeech.googleapis.com/v1/voices", params=params
            )
            if res.status_code == 200:
                voices = res.json().get("voices", [])
                return {
                    "success": True,
                    "count": len(voices),
                    "voices": [
                        {
                            "name": v["name"],
                            "language": v["languageCodes"][0],
                            "gender": v.get("ssmlGender", ""),
                            "type": "Neural2" if "Neural" in v["name"] else "Standard",
                        }
                        for v in voices[:30]
                    ],
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 6. CLOUD SPEECH-TO-TEXT API — Transcripción de audio
    # ══════════════════════════════════════════════════════════════

    async def speech_to_text(
        self,
        audio_bytes: bytes,
        language: str = "es-ES",
        audio_encoding: str = "OGG_OPUS",
        sample_rate: int = 16000,
    ) -> dict[str, Any]:
        """Transcribe audio a texto con Speech-to-Text API."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            body = {
                "config": {
                    "encoding": audio_encoding,
                    "sampleRateHertz": sample_rate,
                    "languageCode": language,
                    "alternativeLanguageCodes": ["en-US", "es-MX", "es-AR"],
                    "enableAutomaticPunctuation": True,
                    "model": "latest_long",
                },
                "audio": {"content": base64.b64encode(audio_bytes).decode()},
            }
            res = await self._http.post(
                "https://speech.googleapis.com/v1/speech:recognize",
                params={"key": self._key},
                json=body,
                timeout=60.0,
            )
            if res.status_code == 200:
                results = res.json().get("results", [])
                transcript = " ".join(
                    r.get("alternatives", [{}])[0].get("transcript", "") for r in results
                )
                confidence = (
                    results[0].get("alternatives", [{}])[0].get("confidence", 0) if results else 0
                )
                return {
                    "success": True,
                    "transcript": transcript,
                    "confidence": round(confidence, 3),
                    "language": language,
                }
            return {"success": False, "error": f"STT HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            logger.error("[GoogleSuite] stt error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 7. YOUTUBE DATA API v3 — Completo
    # ══════════════════════════════════════════════════════════════

    async def youtube_search(
        self,
        query: str,
        max_results: int = 20,
        order: str = "relevance",
        video_type: str = "video",
        language: str = "",
    ) -> dict[str, Any]:
        """Búsqueda completa en YouTube."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            params = {
                "part": "snippet",
                "q": query,
                "type": video_type,
                "maxResults": min(max_results, 50),
                "order": order,
                "key": self._key,
                "safeSearch": "moderate",
            }
            if language:
                params["relevanceLanguage"] = language
            res = await self._http.get(f"{BASE}/youtube/v3/search", params=params)
            if res.status_code == 200:
                items = res.json().get("items", [])
                return {
                    "success": True,
                    "query": query,
                    "count": len(items),
                    "results": [
                        {
                            "id": i["id"].get("videoId", "")
                            or i["id"].get("channelId", "")
                            or i["id"].get("playlistId", ""),
                            "type": i["id"].get("kind", "").split("#")[-1],
                            "title": i["snippet"]["title"],
                            "channel": i["snippet"].get("channelTitle", ""),
                            "description": i["snippet"].get("description", "")[:200],
                            "published": i["snippet"].get("publishedAt", ""),
                            "thumbnail": i["snippet"]
                            .get("thumbnails", {})
                            .get("high", {})
                            .get("url", ""),
                        }
                        for i in items
                    ],
                }
            return {"success": False, "error": f"HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def youtube_video_details(self, video_ids: list[str]) -> dict[str, Any]:
        """Detalles completos de videos: stats, contenido, tags, monetización."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            res = await self._http.get(
                f"{BASE}/youtube/v3/videos",
                params={
                    "part": "snippet,statistics,contentDetails,topicDetails,status",
                    "id": ",".join(video_ids[:50]),
                    "key": self._key,
                },
            )
            if res.status_code == 200:
                items = res.json().get("items", [])
                return {
                    "success": True,
                    "videos": [
                        {
                            "id": v["id"],
                            "title": v["snippet"]["title"],
                            "channel": v["snippet"]["channelTitle"],
                            "channel_id": v["snippet"]["channelId"],
                            "description": v["snippet"].get("description", "")[:500],
                            "tags": v["snippet"].get("tags", [])[:10],
                            "category_id": v["snippet"].get("categoryId", ""),
                            "duration": v.get("contentDetails", {}).get("duration", ""),
                            "views": int(v.get("statistics", {}).get("viewCount", 0)),
                            "likes": int(v.get("statistics", {}).get("likeCount", 0)),
                            "comments": int(v.get("statistics", {}).get("commentCount", 0)),
                            "topics": v.get("topicDetails", {}).get("topicCategories", []),
                            "license": v.get("status", {}).get("license", ""),
                        }
                        for v in items
                    ],
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def youtube_channel_details(
        self, channel_id: str = "", username: str = ""
    ) -> dict[str, Any]:
        """Detalles completos de un canal de YouTube."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            params = {
                "part": "snippet,statistics,brandingSettings,contentDetails",
                "key": self._key,
            }
            if channel_id:
                params["id"] = channel_id
            elif username:
                params["forUsername"] = username
            res = await self._http.get(f"{BASE}/youtube/v3/channels", params=params)
            if res.status_code == 200:
                items = res.json().get("items", [])
                if not items:
                    return {"success": False, "error": "Canal no encontrado"}
                c = items[0]
                return {
                    "success": True,
                    "id": c["id"],
                    "name": c["snippet"]["title"],
                    "description": c["snippet"].get("description", "")[:300],
                    "subscribers": int(c.get("statistics", {}).get("subscriberCount", 0)),
                    "views": int(c.get("statistics", {}).get("viewCount", 0)),
                    "videos": int(c.get("statistics", {}).get("videoCount", 0)),
                    "country": c["snippet"].get("country", ""),
                    "created": c["snippet"].get("publishedAt", ""),
                    "uploads_playlist": c.get("contentDetails", {})
                    .get("relatedPlaylists", {})
                    .get("uploads", ""),
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def youtube_comments(self, video_id: str, max_results: int = 20) -> dict[str, Any]:
        """Obtiene comentarios de un video (útil para análisis de mercado)."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            res = await self._http.get(
                f"{BASE}/youtube/v3/commentThreads",
                params={
                    "part": "snippet",
                    "videoId": video_id,
                    "maxResults": min(max_results, 100),
                    "order": "relevance",
                    "key": self._key,
                },
            )
            if res.status_code == 200:
                items = res.json().get("items", [])
                return {
                    "success": True,
                    "video_id": video_id,
                    "count": len(items),
                    "comments": [
                        {
                            "text": i["snippet"]["topLevelComment"]["snippet"]["textDisplay"],
                            "likes": i["snippet"]["topLevelComment"]["snippet"].get("likeCount", 0),
                            "author": i["snippet"]["topLevelComment"]["snippet"].get(
                                "authorDisplayName", ""
                            ),
                        }
                        for i in items
                    ],
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def youtube_trending(self, region: str = "US", category_id: str = "0") -> dict[str, Any]:
        """Videos trending de YouTube por región y categoría."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            params = {
                "part": "snippet,statistics",
                "chart": "mostPopular",
                "regionCode": region,
                "maxResults": 50,
                "key": self._key,
            }
            # "0" isn't a real YouTube category id (they start at "1") — the
            # API rejects it with a 400, so only send it when a real category
            # was actually requested.
            if category_id and category_id != "0":
                params["videoCategoryId"] = category_id
            res = await self._http.get(f"{BASE}/youtube/v3/videos", params=params)
            if res.status_code == 200:
                items = res.json().get("items", [])
                return {
                    "success": True,
                    "region": region,
                    "trending": [
                        {
                            "id": v["id"],
                            "title": v["snippet"]["title"],
                            "channel": v["snippet"]["channelTitle"],
                            "views": int(v.get("statistics", {}).get("viewCount", 0)),
                            "tags": v["snippet"].get("tags", [])[:5],
                        }
                        for v in items
                    ],
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def youtube_search_captions(self, video_id: str) -> dict[str, Any]:
        """Lista los subtítulos disponibles en un video."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            res = await self._http.get(
                f"{BASE}/youtube/v3/captions",
                params={
                    "part": "snippet",
                    "videoId": video_id,
                    "key": self._key,
                },
            )
            if res.status_code == 200:
                items = res.json().get("items", [])
                return {
                    "success": True,
                    "captions": [
                        {
                            "id": i["id"],
                            "language": i["snippet"]["language"],
                            "name": i["snippet"]["name"],
                        }
                        for i in items
                    ],
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 8. KNOWLEDGE GRAPH SEARCH API — Entidades del grafo de conocimiento
    # ══════════════════════════════════════════════════════════════

    async def knowledge_graph_search(
        self, query: str, languages: list[str] | None = None, limit: int = 5
    ) -> dict[str, Any]:
        """Busca entidades en el Knowledge Graph de Google."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            params = {"query": query, "limit": limit, "indent": True, "key": self._key}
            if languages:
                params["languages"] = ",".join(languages)
            res = await self._http.get(
                "https://kgsearch.googleapis.com/v1/entities:search", params=params
            )
            if res.status_code == 200:
                items = res.json().get("itemListElement", [])
                return {
                    "success": True,
                    "entities": [
                        {
                            "name": i.get("result", {}).get("name", ""),
                            "description": i.get("result", {}).get("description", ""),
                            "types": i.get("result", {}).get("@type", []),
                            "url": i.get("result", {}).get("url", ""),
                            "score": round(i.get("resultScore", 0), 2),
                        }
                        for i in items
                    ],
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 9. PAGESPEED INSIGHTS API — SEO y velocidad
    # ══════════════════════════════════════════════════════════════

    async def pagespeed_analyze(self, url: str, strategy: str = "mobile") -> dict[str, Any]:
        """Analiza velocidad y SEO de cualquier URL."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            res = await self._http.get(
                f"{BASE}/pagespeedonline/v5/runPagespeed",
                params={"url": url, "strategy": strategy, "key": self._key},
                timeout=60.0,
            )
            if res.status_code == 200:
                data = res.json()
                cats = data.get("lighthouseResult", {}).get("categories", {})
                audits = data.get("lighthouseResult", {}).get("audits", {})
                return {
                    "success": True,
                    "url": url,
                    "strategy": strategy,
                    "scores": {
                        "performance": round(cats.get("performance", {}).get("score", 0) * 100),
                        "accessibility": round(cats.get("accessibility", {}).get("score", 0) * 100),
                        "best_practices": round(
                            cats.get("best-practices", {}).get("score", 0) * 100
                        ),
                        "seo": round(cats.get("seo", {}).get("score", 0) * 100),
                    },
                    "metrics": {
                        "fcp": audits.get("first-contentful-paint", {}).get("displayValue", ""),
                        "lcp": audits.get("largest-contentful-paint", {}).get("displayValue", ""),
                        "cls": audits.get("cumulative-layout-shift", {}).get("displayValue", ""),
                        "speed_index": audits.get("speed-index", {}).get("displayValue", ""),
                    },
                    "opportunities": [
                        {
                            "title": audits[k].get("title", ""),
                            "savings": audits[k].get("displayValue", ""),
                        }
                        for k in audits
                        if audits[k].get("details", {}).get("type") == "opportunity"
                        and audits[k].get("score", 1) < 0.9
                    ][:5],
                }
            return {"success": False, "error": f"PageSpeed HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 10. BOOKS API — Investigación de mercado editorial
    # ══════════════════════════════════════════════════════════════

    async def books_search(
        self, query: str, max_results: int = 10, language: str = ""
    ) -> dict[str, Any]:
        """Busca libros en Google Books (útil para investigación de nichos)."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            params = {
                "q": query,
                "maxResults": min(max_results, 40),
                "key": self._key,
                "printType": "books",
                "orderBy": "relevance",
            }
            if language:
                params["langRestrict"] = language
            res = await self._http.get(f"{BASE}/books/v1/volumes", params=params)
            if res.status_code == 200:
                items = res.json().get("items", [])
                return {
                    "success": True,
                    "query": query,
                    "books": [
                        {
                            "title": i["volumeInfo"].get("title", ""),
                            "authors": i["volumeInfo"].get("authors", []),
                            "published": i["volumeInfo"].get("publishedDate", ""),
                            "categories": i["volumeInfo"].get("categories", []),
                            "description": i["volumeInfo"].get("description", "")[:300],
                            "pages": i["volumeInfo"].get("pageCount", 0),
                            "rating": i["volumeInfo"].get("averageRating", 0),
                            "ratings_count": i["volumeInfo"].get("ratingsCount", 0),
                            "price": i.get("saleInfo", {}).get("listPrice", {}).get("amount", 0),
                        }
                        for i in items
                    ],
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 11. FACT CHECK TOOLS API — Verificación de hechos
    # ══════════════════════════════════════════════════════════════

    async def fact_check(self, query: str) -> dict[str, Any]:
        """Verifica un hecho o claim usando Google Fact Check API."""
        if not self._ok():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            res = await self._http.get(
                f"{BASE}/factchecktools/v1alpha1/claims:search",
                params={"query": query, "key": self._key, "pageSize": 5},
            )
            if res.status_code == 200:
                claims = res.json().get("claims", [])
                return {
                    "success": True,
                    "query": query,
                    "fact_checks": [
                        {
                            "text": c.get("text", ""),
                            "claimant": c.get("claimant", ""),
                            "reviews": [
                                {
                                    "rating": r.get("textualRating", ""),
                                    "publisher": r.get("publisher", {}).get("name", ""),
                                    "url": r.get("url", ""),
                                }
                                for r in c.get("claimReview", [])
                            ],
                        }
                        for c in claims
                    ],
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 12. GOOGLE TRENDS — Sin API key (RSS público)
    # ══════════════════════════════════════════════════════════════

    async def trends_daily(self, geo: str = "US") -> dict[str, Any]:
        """Trending searches diarios de Google Trends."""
        try:
            res = await self._http.get(
                "https://trends.google.com/trends/trendingsearches/daily/rss",
                params={"geo": geo},
                timeout=15.0,
            )
            if res.status_code == 200:
                titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", res.text)
                traffic = re.findall(r"<ht:approx_traffic>(.*?)</ht:approx_traffic>", res.text)
                trends = [
                    {"topic": t, "traffic": tr}
                    for t, tr in zip(titles[1:21], traffic, strict=False)
                ]
                return {"success": True, "geo": geo, "trends": trends, "count": len(trends)}
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def trends_realtime(self, geo: str = "US", category: str = "all") -> dict[str, Any]:
        """Trending searches en tiempo real de Google."""
        try:
            url = f"https://trends.google.com/trends/api/realtimetrends?hl=en-US&tz=-360&cat={category}&geo={geo}&fi=0&fs=0&ri=300&rs=20&sort=0"
            res = await self._http.get(url, timeout=15.0)
            if res.status_code == 200:
                raw = res.text.lstrip(")]}',\n")
                data = json.loads(raw)
                stories = data.get("storySummaries", {}).get("trendingStories", [])
                return {
                    "success": True,
                    "realtime_trends": [
                        {"title": s.get("title", ""), "traffic": s.get("entityNames", [])}
                        for s in stories[:20]
                    ],
                }
        except Exception as exc:
            logger.warning("[GoogleSuite] trends_realtime error: %s", exc)
        return await self.trends_daily(geo)

    # ══════════════════════════════════════════════════════════════
    # HELPER: Análisis de mercado completo con todas las APIs
    # ══════════════════════════════════════════════════════════════

    async def full_market_research(self, niche: str, language: str = "es") -> dict[str, Any]:
        """
        Investigación de mercado completa usando todas las APIs de Google.
        Combina: Web Search + YouTube + Books + Knowledge Graph + Trends + NLP.
        """
        import asyncio

        logger.info("[GoogleSuite] Full market research: %s", niche)

        web_task = self.web_search(f"{niche} market opportunities 2025", num=5)
        youtube_task = self.youtube_search(
            f"how to make money with {niche}", max_results=5, order="viewCount"
        )
        books_task = self.books_search(niche, max_results=5)
        kg_task = self.knowledge_graph_search(niche, limit=3)
        trends_task = self.trends_daily("US")

        web, youtube, books, kg, trends = await asyncio.gather(
            web_task, youtube_task, books_task, kg_task, trends_task, return_exceptions=True
        )

        # NLP analysis on web results
        web_snippets = " ".join(
            [
                r.get("snippet", "")
                for r in (web.get("results", []) if isinstance(web, dict) else [])[:5]
            ]
        )
        nlp_task = self.nlp_analyze(web_snippets[:3000]) if web_snippets else asyncio.sleep(0)
        nlp = await nlp_task

        any_succeeded = any(
            isinstance(x, dict) and x.get("success") for x in (web, youtube, books, kg, trends)
        )
        return {
            "success": any_succeeded,
            "niche": niche,
            "web_results": web.get("results", [])[:5] if isinstance(web, dict) else [],
            "youtube_videos": youtube.get("results", [])[:5] if isinstance(youtube, dict) else [],
            "books": books.get("books", [])[:3] if isinstance(books, dict) else [],
            "knowledge_graph": kg.get("entities", [])[:3] if isinstance(kg, dict) else [],
            "trending_topics": trends.get("trends", [])[:10] if isinstance(trends, dict) else [],
            "nlp_insights": nlp if isinstance(nlp, dict) else {},
        }
