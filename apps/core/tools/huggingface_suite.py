"""
huggingface_suite.py — Suite completa de HuggingFace Inference API para ARIA AI.

Capacidades integradas (todas con HF_TOKEN gratuito):
  - Generación de imágenes (FLUX.1-schnell, SDXL, Stable Diffusion 3.5)
  - Traducción automática (Helsinki-NLP — 1000+ pares de idiomas)
  - Resumen automático (BART, Pegasus, mT5)
  - Análisis de sentimiento (DistilBERT, RoBERTa, multilingual)
  - Clasificación zero-shot (sin entrenamiento previo)
  - Reconocimiento de entidades (NER — BERT, spaCy)
  - Respuesta a preguntas (Question Answering)
  - Embeddings de texto (sentence-transformers, all-MiniLM)
  - Text-to-Speech (Bark — voces realistas)
  - Speech-to-Text (Whisper large-v3)
  - Descripción de imágenes / Image Captioning (BLIP-2, GIT)
  - Detección de objetos (DETR, YOLOs)
  - Clasificación de imágenes (ViT, EfficientNet)
  - Relleno de texto (Fill-mask — BERT)
  - Extracción de features / embeddings de imágenes
  - Clasificación de audio
  - Estimación de profundidad (DPT, Depth-Anything)
  - Detección de idioma
  - Generación de código (Qwen2.5-Coder)
"""
from __future__ import annotations
import asyncio
import base64
import io
import json
import logging
import time
from typing import Any, Optional
import httpx
from apps.core.config import settings

logger = logging.getLogger("aria.huggingface_suite")
HF_API = "https://api-inference.huggingface.co/models"
HF_ROUTER = "https://router.huggingface.co"


class HuggingFaceSuite:
    """Suite completa de capacidades de HuggingFace para ARIA AI."""

    def __init__(self) -> None:
        self._token = settings.HF_TOKEN
        self._http = httpx.AsyncClient(timeout=120.0)

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Authorization": f"Bearer {self._token}"}
        if extra:
            h.update(extra)
        return h

    def _ok(self) -> bool:
        return bool(self._token)

    async def _call(
        self,
        model: str,
        payload: Any,
        binary: bool = False,
        wait_for_model: bool = True,
        provider: str = "",
        timeout: float = 120.0,
    ) -> Any:
        """Llamada genérica a HF Inference API con retry en cold start."""
        if not self._ok():
            return None

        base_url = f"{HF_ROUTER}/hf-inference/models" if provider else HF_API
        url = f"{base_url}/{model}"
        headers = self._headers({
            "Content-Type": "application/json",
            "X-Wait-For-Model": "true" if wait_for_model else "false",
        })
        if binary:
            headers.pop("Content-Type", None)

        for attempt in range(3):
            try:
                if isinstance(payload, bytes):
                    res = await self._http.post(url, headers=headers, content=payload, timeout=timeout)
                else:
                    res = await self._http.post(url, headers=headers, json=payload, timeout=timeout)

                if res.status_code == 200:
                    return res.content if binary else res.json()
                if res.status_code == 503 and attempt < 2:
                    # Model loading — wait and retry
                    wait = res.json().get("estimated_time", 20)
                    logger.info("[HF] Model %s loading, waiting %ss...", model, wait)
                    await asyncio.sleep(min(wait, 30))
                    continue
                logger.warning("[HF] %s HTTP %d: %s", model, res.status_code, res.text[:200])
                return None
            except Exception as exc:
                logger.error("[HF] %s attempt %d error: %s", model, attempt, exc)
                if attempt < 2:
                    await asyncio.sleep(5)
        return None

    # ══════════════════════════════════════════════════════════════
    # 1. GENERACIÓN DE IMÁGENES — FLUX.1, SDXL, SD 3.5
    # ══════════════════════════════════════════════════════════════

    async def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        model: str = "black-forest-labs/FLUX.1-schnell",
        width: int = 1024,
        height: int = 1024,
        num_inference_steps: int = 4,
        guidance_scale: float = 0.0,
        seed: int = -1,
    ) -> dict[str, Any]:
        """
        Genera imagen con IA. Modelos disponibles:
        - black-forest-labs/FLUX.1-schnell (rápido, alta calidad)
        - black-forest-labs/FLUX.1-dev (mayor calidad, más lento)
        - stabilityai/stable-diffusion-xl-base-1.0 (SDXL)
        - stabilityai/stable-diffusion-3.5-large (SD 3.5)
        - stabilityai/stable-diffusion-2-1 (SD 2.1)
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            payload: dict[str, Any] = {
                "inputs": prompt,
                "parameters": {
                    "width": width,
                    "height": height,
                    "num_inference_steps": num_inference_steps,
                    "guidance_scale": guidance_scale,
                },
            }
            if negative_prompt:
                payload["parameters"]["negative_prompt"] = negative_prompt
            if seed >= 0:
                payload["parameters"]["seed"] = seed

            img_bytes = await self._call(model, payload, binary=True, timeout=120.0)
            if img_bytes:
                return {
                    "success": True,
                    "image_bytes": img_bytes,
                    "image_b64": base64.b64encode(img_bytes).decode(),
                    "model": model,
                    "prompt": prompt,
                    "size": f"{width}x{height}",
                }
            return {"success": False, "error": "No se pudo generar la imagen"}
        except Exception as exc:
            logger.error("[HF] generate_image error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def generate_product_image(self, product_name: str, niche: str, style: str = "professional product photography") -> dict[str, Any]:
        """Genera imagen de producto para marketing/ecommerce."""
        prompt = (
            f"{style}, {product_name} for {niche} market, "
            "high quality, clean background, commercial photography, "
            "8K resolution, professional lighting, product showcase"
        )
        return await self.generate_image(prompt, model="black-forest-labs/FLUX.1-schnell")

    async def generate_social_media_image(self, text: str, niche: str, platform: str = "instagram") -> dict[str, Any]:
        """Genera imagen optimizada para redes sociales."""
        size_map = {"instagram": (1024, 1024), "twitter": (1200, 628), "linkedin": (1200, 628), "tiktok": (1080, 1920)}
        w, h = size_map.get(platform, (1024, 1024))
        prompt = (
            f"Social media post for {platform}, {niche} niche, "
            f"text overlay concept: '{text[:50]}', "
            "vibrant colors, eye-catching design, professional, modern, trending"
        )
        return await self.generate_image(prompt, width=w, height=h)

    async def generate_blog_thumbnail(self, title: str, niche: str) -> dict[str, Any]:
        """Genera thumbnail para artículo de blog."""
        prompt = (
            f"Blog post thumbnail, {niche}, concept: '{title[:60]}', "
            "professional design, text-ready space, 16:9 ratio, "
            "high contrast, attention-grabbing, modern flat design"
        )
        return await self.generate_image(prompt, width=1200, height=628)

    # ══════════════════════════════════════════════════════════════
    # 2. TRADUCCIÓN — Helsinki-NLP (1000+ pares de idiomas)
    # ══════════════════════════════════════════════════════════════

    async def translate(self, text: str, source: str, target: str) -> dict[str, Any]:
        """
        Traduce texto usando modelos Helsinki-NLP.
        Soporta pares: es-en, en-es, fr-en, de-en, ja-en, zh-en, ar-en, pt-en,
        ru-en, it-en, ko-en, nl-en, sv-en, pl-en, y muchos más.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            model = f"Helsinki-NLP/opus-mt-{source}-{target}"
            result = await self._call(model, {"inputs": text})
            if result and isinstance(result, list):
                return {
                    "success": True,
                    "translated": result[0].get("translation_text", ""),
                    "source": source,
                    "target": target,
                    "model": model,
                }
            # Fallback: try multilingual model
            result2 = await self._call("Helsinki-NLP/opus-mt-tc-big-en-es", {"inputs": text})
            if result2:
                return {"success": True, "translated": result2[0].get("translation_text",""), "source": source, "target": target}
            return {"success": False, "error": "Traducción no disponible para este par de idiomas"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def translate_to_many(self, text: str, source: str, targets: list[str]) -> dict[str, str]:
        """Traduce texto a múltiples idiomas simultáneamente."""
        tasks = [self.translate(text, source, t) for t in targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            lang: (r.get("translated","") if isinstance(r, dict) and r.get("success") else text)
            for lang, r in zip(targets, results)
        }

    async def translate_product_listing(self, listing: dict, source: str = "es", targets: list[str] | None = None) -> dict[str, Any]:
        """Traduce un listing de producto completo a múltiples idiomas."""
        if not targets:
            targets = ["en", "fr", "de", "pt", "it", "ja", "zh"]
        results: dict[str, dict] = {}
        for lang in targets:
            name = await self.translate(listing.get("name",""), source, lang)
            desc = await self.translate(listing.get("description",""), source, lang)
            results[lang] = {
                "name": name.get("translated",""),
                "description": desc.get("translated",""),
            }
        return {"success": True, "listings": results}

    # ══════════════════════════════════════════════════════════════
    # 3. RESUMEN AUTOMÁTICO — BART, Pegasus, mT5
    # ══════════════════════════════════════════════════════════════

    async def summarize(
        self,
        text: str,
        max_length: int = 150,
        min_length: int = 50,
        model: str = "facebook/bart-large-cnn",
        language: str = "en",
    ) -> dict[str, Any]:
        """
        Genera resumen de texto. Modelos disponibles:
        - facebook/bart-large-cnn (inglés, excelente para noticias)
        - google/pegasus-xsum (inglés, resúmenes muy cortos)
        - csebuetnlp/mT5_multilingual_XLSum (multilingüe)
        - philschmid/bart-large-cnn-samsum (conversaciones)
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            if language != "en":
                model = "csebuetnlp/mT5_multilingual_XLSum"
            result = await self._call(model, {
                "inputs": text[:3000],
                "parameters": {"max_length": max_length, "min_length": min_length, "do_sample": False},
            })
            if result and isinstance(result, list):
                return {
                    "success": True,
                    "summary": result[0].get("summary_text",""),
                    "original_length": len(text),
                    "model": model,
                }
            return {"success": False, "error": "Sin respuesta del modelo de resumen"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def summarize_articles(self, articles: list[str], language: str = "en") -> list[str]:
        """Resume múltiples artículos en paralelo."""
        tasks = [self.summarize(a, language=language) for a in articles]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r.get("summary","") if isinstance(r,dict) and r.get("success") else "" for r in results]

    # ══════════════════════════════════════════════════════════════
    # 4. ANÁLISIS DE SENTIMIENTO
    # ══════════════════════════════════════════════════════════════

    async def analyze_sentiment(
        self,
        text: str,
        multilingual: bool = True,
    ) -> dict[str, Any]:
        """
        Análisis de sentimiento. Modelos:
        - cardiffnlp/twitter-roberta-base-sentiment (inglés, tweets)
        - lxyuan/distilbert-base-multilingual-cased-sentiments-student (multilingüe)
        - nlptown/bert-base-multilingual-uncased-sentiment (1-5 estrellas)
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            model = ("lxyuan/distilbert-base-multilingual-cased-sentiments-student"
                     if multilingual else "cardiffnlp/twitter-roberta-base-sentiment-latest")
            result = await self._call(model, {"inputs": text[:512]})
            if result and isinstance(result, list):
                scores = result[0] if isinstance(result[0], list) else result
                best = max(scores, key=lambda x: x.get("score", 0))
                label = best.get("label","").lower()
                normalized = "positivo" if "pos" in label else "negativo" if "neg" in label else "neutro"
                return {
                    "success": True,
                    "sentiment": normalized,
                    "confidence": round(best.get("score",0), 3),
                    "all_scores": {s.get("label",""):round(s.get("score",0),3) for s in scores},
                }
            return {"success": False, "error": "Sin respuesta del modelo"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def analyze_sentiment_batch(self, texts: list[str]) -> list[dict]:
        """Analiza sentimiento de múltiples textos en paralelo."""
        tasks = [self.analyze_sentiment(t) for t in texts[:20]]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def analyze_market_sentiment(self, niche: str, texts: list[str]) -> dict[str, Any]:
        """Analiza el sentimiento del mercado sobre un nicho."""
        results = await self.analyze_sentiment_batch(texts)
        valid = [r for r in results if isinstance(r, dict) and r.get("success")]
        if not valid:
            return {"success": False, "error": "Sin análisis disponible"}
        pos = sum(1 for r in valid if r.get("sentiment") == "positivo")
        neg = sum(1 for r in valid if r.get("sentiment") == "negativo")
        neu = sum(1 for r in valid if r.get("sentiment") == "neutro")
        total = len(valid)
        return {
            "success": True,
            "niche": niche,
            "total_analyzed": total,
            "positive_pct": round(pos/total*100, 1),
            "negative_pct": round(neg/total*100, 1),
            "neutral_pct": round(neu/total*100, 1),
            "overall": "positivo" if pos > neg else "negativo" if neg > pos else "neutro",
        }

    # ══════════════════════════════════════════════════════════════
    # 5. CLASIFICACIÓN ZERO-SHOT — Sin entrenamiento previo
    # ══════════════════════════════════════════════════════════════

    async def classify_zero_shot(
        self,
        text: str,
        candidate_labels: list[str],
        hypothesis_template: str = "This text is about {}.",
        model: str = "facebook/bart-large-mnli",
    ) -> dict[str, Any]:
        """
        Clasifica texto en CUALQUIER categoría sin entrenamiento.
        Modelos: facebook/bart-large-mnli, cross-encoder/nli-deberta-v3-large
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(model, {
                "inputs": text[:1000],
                "parameters": {"candidate_labels": candidate_labels, "hypothesis_template": hypothesis_template},
            })
            if result and "labels" in result:
                return {
                    "success": True,
                    "best_label": result["labels"][0],
                    "best_score": round(result["scores"][0], 3),
                    "all_labels": dict(zip(result["labels"], [round(s,3) for s in result["scores"]])),
                }
            return {"success": False, "error": "Sin resultado de clasificación"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def classify_product_niche(self, product_description: str) -> dict[str, Any]:
        """Clasifica un producto en su nicho de mercado automáticamente."""
        niches = [
            "health and wellness", "personal finance", "digital marketing",
            "technology and software", "education and online courses",
            "fitness and sports", "beauty and fashion", "food and cooking",
            "travel and lifestyle", "business and entrepreneurship",
            "entertainment and gaming", "relationships and dating",
        ]
        return await self.classify_zero_shot(product_description, niches)

    async def classify_content_type(self, content: str) -> dict[str, Any]:
        """Clasifica el tipo de contenido."""
        types = ["educational", "promotional", "entertaining", "informational", "inspirational", "controversial"]
        return await self.classify_zero_shot(content, types)

    # ══════════════════════════════════════════════════════════════
    # 6. RECONOCIMIENTO DE ENTIDADES NOMBRADAS (NER)
    # ══════════════════════════════════════════════════════════════

    async def extract_entities(
        self,
        text: str,
        model: str = "dslim/bert-base-NER",
    ) -> dict[str, Any]:
        """
        Extrae entidades: personas, organizaciones, lugares, fechas, productos.
        Modelos: dslim/bert-base-NER, Jean-Baptiste/roberta-large-ner-english,
                 flair/ner-english-large (multilingual: Davlan/bert-base-multilingual-cased-ner-hrl)
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(model, {"inputs": text[:512]})
            if result and isinstance(result, list):
                entities: dict[str, list] = {}
                for e in result:
                    entity_type = e.get("entity_group", e.get("entity","")).replace("B-","").replace("I-","")
                    word = e.get("word","").replace("##","")
                    if entity_type not in entities:
                        entities[entity_type] = []
                    if word and word not in entities[entity_type]:
                        entities[entity_type].append(word)
                return {"success": True, "entities": entities, "raw": result[:20]}
            return {"success": False, "error": "Sin entidades detectadas"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 7. RESPUESTA A PREGUNTAS (Question Answering)
    # ══════════════════════════════════════════════════════════════

    async def answer_question(
        self,
        question: str,
        context: str,
        model: str = "deepset/roberta-base-squad2",
    ) -> dict[str, Any]:
        """
        Responde preguntas basándose en un contexto dado (QA extractivo).
        Modelos: deepset/roberta-base-squad2, deepset/deberta-v3-base-squad2
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(model, {"inputs": {"question": question, "context": context[:3000]}})
            if result and isinstance(result, dict):
                return {
                    "success": True,
                    "answer": result.get("answer",""),
                    "confidence": round(result.get("score",0), 3),
                    "start": result.get("start",0),
                    "end": result.get("end",0),
                }
            return {"success": False, "error": "Sin respuesta"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 8. EMBEDDINGS DE TEXTO — Búsqueda semántica y similaridad
    # ══════════════════════════════════════════════════════════════

    async def get_embeddings(
        self,
        texts: list[str],
        model: str = "sentence-transformers/all-MiniLM-L6-v2",
    ) -> dict[str, Any]:
        """
        Genera embeddings vectoriales para búsqueda semántica y similaridad.
        Modelos: sentence-transformers/all-MiniLM-L6-v2 (rápido, 384 dims)
                 sentence-transformers/all-mpnet-base-v2 (preciso, 768 dims)
                 intfloat/multilingual-e5-large (multilingüe, 1024 dims)
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(model, {"inputs": texts})
            if result and isinstance(result, list):
                return {"success": True, "embeddings": result, "model": model, "dimensions": len(result[0]) if result else 0}
            return {"success": False, "error": "Sin embeddings"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def compute_similarity(self, text1: str, text2: str) -> dict[str, Any]:
        """Calcula la similaridad semántica entre dos textos (0-1)."""
        result = await self.get_embeddings([text1, text2])
        if not result.get("success"):
            return result
        import math
        emb = result["embeddings"]
        e1, e2 = emb[0], emb[1]
        dot = sum(a*b for a, b in zip(e1, e2))
        norm1 = math.sqrt(sum(a**2 for a in e1))
        norm2 = math.sqrt(sum(b**2 for b in e2))
        similarity = dot / (norm1 * norm2) if norm1 * norm2 > 0 else 0
        return {"success": True, "similarity": round(similarity, 4), "text1": text1[:100], "text2": text2[:100]}

    async def find_most_similar(self, query: str, candidates: list[str]) -> dict[str, Any]:
        """Encuentra el texto más similar a un query entre una lista de candidatos."""
        all_texts = [query] + candidates
        result = await self.get_embeddings(all_texts)
        if not result.get("success"):
            return result
        import math
        embs = result["embeddings"]
        q_emb = embs[0]
        def cosine(a, b):
            d = sum(x*y for x,y in zip(a,b))
            return d / (math.sqrt(sum(x**2 for x in a)) * math.sqrt(sum(y**2 for y in b)) + 1e-9)
        scores = [(candidates[i], cosine(q_emb, embs[i+1])) for i in range(len(candidates))]
        scores.sort(key=lambda x: x[1], reverse=True)
        return {"success": True, "query": query, "ranked": [(t, round(s,4)) for t,s in scores[:10]]}

    # ══════════════════════════════════════════════════════════════
    # 9. TEXT-TO-SPEECH — Bark (voces realistas)
    # ══════════════════════════════════════════════════════════════

    async def text_to_speech_bark(
        self,
        text: str,
        voice_preset: str = "v2/es_speaker_1",
    ) -> dict[str, Any]:
        """
        Genera audio realista con Bark.
        Voces españolas: v2/es_speaker_0 hasta v2/es_speaker_9
        Voces inglesas: v2/en_speaker_0 hasta v2/en_speaker_9
        Soporta risas [laughter], sighs [sighs], música, efectos de sonido.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(
                "suno/bark",
                {"inputs": text[:300], "parameters": {"voice_preset": voice_preset}},
                binary=True,
                timeout=120.0,
            )
            if result:
                return {
                    "success": True,
                    "audio_bytes": result,
                    "audio_b64": base64.b64encode(result).decode(),
                    "voice": voice_preset,
                }
            return {"success": False, "error": "Sin audio generado"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 10. SPEECH-TO-TEXT — Whisper large-v3
    # ══════════════════════════════════════════════════════════════

    async def transcribe(
        self,
        audio_bytes: bytes,
        language: str = "es",
        model: str = "openai/whisper-large-v3",
    ) -> dict[str, Any]:
        """
        Transcribe audio a texto con Whisper large-v3.
        Soporta 99 idiomas automáticamente.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(
                model,
                audio_bytes,
                binary=False,
                timeout=120.0,
            )
            if result and isinstance(result, dict):
                return {
                    "success": True,
                    "transcript": result.get("text",""),
                    "language": language,
                    "model": model,
                }
            return {"success": False, "error": "Sin transcripción"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 11. IMAGE CAPTIONING — BLIP-2, GIT
    # ══════════════════════════════════════════════════════════════

    async def describe_image(
        self,
        image_bytes: bytes = b"",
        image_url: str = "",
        model: str = "Salesforce/blip-image-captioning-large",
    ) -> dict[str, Any]:
        """
        Describe el contenido de una imagen con IA.
        Modelos: Salesforce/blip-image-captioning-large, nlpconnect/vit-gpt2-image-captioning
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            if image_url and not image_bytes:
                res = await self._http.get(image_url, timeout=30.0)
                image_bytes = res.content

            result = await self._call(model, image_bytes, binary=False, timeout=60.0)
            if result and isinstance(result, list):
                description = result[0].get("generated_text","")
                return {"success": True, "description": description, "model": model}
            return {"success": False, "error": "Sin descripción generada"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 12. DETECCIÓN DE OBJETOS — DETR, YOLO
    # ══════════════════════════════════════════════════════════════

    async def detect_objects(
        self,
        image_bytes: bytes,
        model: str = "facebook/detr-resnet-50",
        threshold: float = 0.7,
    ) -> dict[str, Any]:
        """
        Detecta y localiza objetos en imágenes.
        Modelos: facebook/detr-resnet-50, hustvl/yolos-tiny, facebook/detr-resnet-101
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(model, image_bytes, binary=False, timeout=60.0)
            if result and isinstance(result, list):
                detected = [
                    {"label": o.get("label",""), "confidence": round(o.get("score",0),3), "box": o.get("box",{})}
                    for o in result if o.get("score",0) >= threshold
                ]
                labels = list(set(o["label"] for o in detected))
                return {"success": True, "objects": detected, "unique_labels": labels, "count": len(detected)}
            return {"success": False, "error": "Sin objetos detectados"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 13. CLASIFICACIÓN DE IMÁGENES — ViT, EfficientNet
    # ══════════════════════════════════════════════════════════════

    async def classify_image(
        self,
        image_bytes: bytes,
        model: str = "google/vit-base-patch16-224",
    ) -> dict[str, Any]:
        """
        Clasifica imágenes en 1000 categorías de ImageNet.
        Modelos: google/vit-base-patch16-224, microsoft/resnet-50
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(model, image_bytes, binary=False, timeout=60.0)
            if result and isinstance(result, list):
                return {
                    "success": True,
                    "top_label": result[0].get("label",""),
                    "top_score": round(result[0].get("score",0),3),
                    "all": [{"label":r.get("label",""),"score":round(r.get("score",0),3)} for r in result[:5]],
                }
            return {"success": False, "error": "Sin clasificación"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 14. FILL-MASK — Completar texto
    # ══════════════════════════════════════════════════════════════

    async def fill_mask(self, text: str, model: str = "bert-base-uncased") -> dict[str, Any]:
        """
        Completa texto con [MASK]. Útil para generar variaciones de copy.
        Ejemplo: "The best [MASK] for digital marketing is..."
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(model, {"inputs": text})
            if result and isinstance(result, list):
                return {
                    "success": True,
                    "predictions": [{"text":r.get("sequence",""),"token":r.get("token_str",""),"score":round(r.get("score",0),3)} for r in result[:5]],
                }
            return {"success": False, "error": "Sin predicciones"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 15. DETECCIÓN DE IDIOMA
    # ══════════════════════════════════════════════════════════════

    async def detect_language(self, text: str) -> dict[str, Any]:
        """Detecta el idioma de un texto (176 idiomas)."""
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call("papluca/xlm-roberta-base-language-detection", {"inputs": text[:512]})
            if result and isinstance(result, list):
                best = max(result[0] if isinstance(result[0],list) else result, key=lambda x: x.get("score",0))
                return {"success": True, "language": best.get("label",""), "confidence": round(best.get("score",0),3)}
            return {"success": False, "error": "Sin resultado"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 16. CLASIFICACIÓN DE AUDIO
    # ══════════════════════════════════════════════════════════════

    async def classify_audio(self, audio_bytes: bytes, model: str = "ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition") -> dict[str, Any]:
        """
        Clasifica audio por emoción o tipo.
        Modelos: ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition (emociones)
                 MIT/ast-finetuned-audioset-10-10-0.4593 (eventos de audio)
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(model, audio_bytes, binary=False, timeout=60.0)
            if result and isinstance(result, list):
                return {"success": True, "classifications": [{"label":r.get("label",""),"score":round(r.get("score",0),3)} for r in result[:5]]}
            return {"success": False, "error": "Sin clasificación de audio"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 17. ESTIMACIÓN DE PROFUNDIDAD
    # ══════════════════════════════════════════════════════════════

    async def estimate_depth(self, image_bytes: bytes, model: str = "depth-anything/Depth-Anything-V2-Small-hf") -> dict[str, Any]:
        """Estima profundidad de una imagen — útil para análisis de producto."""
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(model, image_bytes, binary=True, timeout=60.0)
            if result:
                return {"success": True, "depth_image_bytes": result, "depth_b64": base64.b64encode(result).decode()}
            return {"success": False, "error": "Sin resultado"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 18. GENERACIÓN DE CÓDIGO — Qwen2.5-Coder
    # ══════════════════════════════════════════════════════════════

    async def generate_code(
        self,
        prompt: str,
        language: str = "python",
        model: str = "Qwen/Qwen2.5-Coder-32B-Instruct",
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """
        Genera código en cualquier lenguaje de programación.
        Usa el ai_client para mayor confiabilidad con circuit breaker.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = await get_ai_client()
            response = await ai.complete(
                system=f"You are an expert {language} developer. Generate clean, production-ready code. Return only code, no explanations unless asked.",
                user=prompt,
                model=AIModel.CODE,
            )
            if response and response.success:
                return {"success": True, "code": response.content, "language": language, "model": response.model}
            return {"success": False, "error": "Sin código generado"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # HELPER: Pipeline completo de contenido para un producto
    # ══════════════════════════════════════════════════════════════

    async def create_product_content_pack(
        self,
        product_name: str,
        product_description: str,
        niche: str,
        languages: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Genera un pack completo de contenido para un producto usando múltiples capacidades HF:
        - Imagen del producto (FLUX.1)
        - Imagen para redes sociales
        - Thumbnail de blog
        - Resumen del producto
        - Clasificación del nicho
        - Sentimiento del mercado
        - Traducción a múltiples idiomas
        """
        if not languages:
            languages = ["en", "fr", "de", "pt"]

        logger.info("[HF] Creando content pack para: %s", product_name)

        img_task = self.generate_product_image(product_name, niche)
        social_task = self.generate_social_media_image(f"Nuevo: {product_name}", niche, "instagram")
        thumb_task = self.generate_blog_thumbnail(f"Cómo usar {product_name}", niche)
        summary_task = self.summarize(product_description, max_length=100, language="es")
        niche_task = self.classify_product_niche(product_description)
        sentiment_task = self.analyze_sentiment(product_description)
        translate_task = self.translate_product_listing(
            {"name": product_name, "description": product_description},
            source="es", targets=languages
        )

        results = await asyncio.gather(
            img_task, social_task, thumb_task, summary_task,
            niche_task, sentiment_task, translate_task,
            return_exceptions=True,
        )
        img, social, thumb, summary, niche_cls, sentiment, translations = results

        return {
            "success": True,
            "product_name": product_name,
            "niche": niche,
            "product_image": {"b64": img.get("image_b64","")[:100]+"..." if isinstance(img,dict) and img.get("success") else None},
            "social_image": {"b64": social.get("image_b64","")[:100]+"..." if isinstance(social,dict) and social.get("success") else None},
            "blog_thumbnail": {"b64": thumb.get("image_b64","")[:100]+"..." if isinstance(thumb,dict) and thumb.get("success") else None},
            "summary": summary.get("summary","") if isinstance(summary,dict) else "",
            "niche_classification": niche_cls.get("best_label","") if isinstance(niche_cls,dict) else niche,
            "market_sentiment": sentiment.get("sentiment","") if isinstance(sentiment,dict) else "",
            "translations": translations.get("listings",{}) if isinstance(translations,dict) else {},
        }

    # ══════════════════════════════════════════════════════════════
    # 19. ANÁLISIS COMPLETO DE COMPETENCIA con HF
    # ══════════════════════════════════════════════════════════════

    async def analyze_competitor_content(self, content_list: list[str], niche: str) -> dict[str, Any]:
        """Analiza contenido de competidores para extraer insights."""
        if not content_list:
            return {"success": False, "error": "Sin contenido para analizar"}

        # Análisis en paralelo
        sentiment_tasks = [self.analyze_sentiment(c[:512]) for c in content_list[:10]]
        sentiments = await asyncio.gather(*sentiment_tasks, return_exceptions=True)

        # Clasificar tipo de contenido
        types_tasks = [self.classify_content_type(c[:512]) for c in content_list[:5]]
        content_types = await asyncio.gather(*types_tasks, return_exceptions=True)

        # Resumen de todos los contenidos juntos
        combined = " ".join(content_list[:3])[:3000]
        summary = await self.summarize(combined)

        pos = sum(1 for s in sentiments if isinstance(s,dict) and s.get("sentiment") == "positivo")
        neg = sum(1 for s in sentiments if isinstance(s,dict) and s.get("sentiment") == "negativo")

        return {
            "success": True,
            "niche": niche,
            "analyzed": len(content_list),
            "sentiment_distribution": {"positive": pos, "negative": neg, "neutral": len(sentiments)-pos-neg},
            "dominant_content_type": content_types[0].get("best_label","") if content_types and isinstance(content_types[0],dict) else "",
            "key_insights": summary.get("summary",""),
        }
