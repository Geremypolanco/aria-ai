"""
huggingface_suite.py — Suite completa de HuggingFace Inference API para ARIA AI.

Cubre TODOS los task groups de huggingface.co/tasks:

MULTIMODAL:
  - Visual Question Answering (ViLT, BLIP)
  - Vision Language Model (Llama Vision, SmolVLM, Qwen2.5-VL)
  - Document Question Answering (LayoutLM)
  - Image-to-Image transformation (instruct-pix2pix)
  - Image Segmentation (mask2former panoptic)
  - Zero-Shot Image Classification (CLIP)
  - Zero-Shot Object Detection (OWL-ViT)
  - Mask Generation (SAM, SlimSAM)
  - Image Feature Extraction (DINO, ViT)

NLP:
  - Traducción automática (Helsinki-NLP — 1000+ pares)
  - Resumen automático (BART, Pegasus, mT5 multilingüe)
  - Análisis de sentimiento (DistilBERT multilingual)
  - Clasificación zero-shot (BART-MNLI)
  - NER — Reconocimiento de entidades (BERT-NER)
  - Question Answering (RoBERTa-SQuAD2)
  - Embeddings de texto (sentence-transformers)
  - Fill-Mask (BERT)
  - Text Ranking / Reranking (cross-encoder)
  - Table Question Answering (TAPAS)
  - Structured Output via response_format (Qwen 2.5)
  - Detección de idioma (XLM-RoBERTa — 176 idiomas)

COMPUTER VISION:
  - Generación de imágenes (FLUX.1-schnell, SDXL, SD 3.5)
  - Image Captioning (BLIP-2, GIT)
  - Object Detection (DETR, YOLO)
  - Image Classification (ViT, EfficientNet)
  - Depth Estimation (Depth-Anything-V2)

AUDIO:
  - Speech-to-Text / ASR (Whisper large-v3)
  - Text-to-Speech (Bark — voces realistas)
  - Music Generation (MusicGen — text-to-music)
  - Audio Classification / Emotion (wav2vec2)
  - Audio Enhancement (speechbrain mtl-mimic-voicebank)

AGENTS:
  - Search Agent estilo smolagents (plan → search → reason → synthesize)
  - Code Generation (Qwen2.5-Coder-32B)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

import httpx

from apps.core.config import settings
from apps.core.tools.web_tools import _assert_public_url

logger = logging.getLogger("aria.huggingface_suite")
HF_API = "https://api-inference.huggingface.co/models"
HF_ROUTER = "https://router.huggingface.co"


class HuggingFaceSuite:
    """Suite completa de capacidades de HuggingFace para ARIA AI."""

    def __init__(self) -> None:
        self._token = settings.hf_key  # HF_TOKEN | HF_API_KEY | HUGGING_FACE_TOKEN
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
        headers = self._headers(
            {
                "Content-Type": "application/json",
                "X-Wait-For-Model": "true" if wait_for_model else "false",
            }
        )
        if binary:
            headers.pop("Content-Type", None)

        for attempt in range(3):
            try:
                if isinstance(payload, bytes):
                    res = await self._http.post(
                        url, headers=headers, content=payload, timeout=timeout
                    )
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

    async def generate_product_image(
        self, product_name: str, niche: str, style: str = "professional product photography"
    ) -> dict[str, Any]:
        """Genera imagen de producto para marketing/ecommerce."""
        prompt = (
            f"{style}, {product_name} for {niche} market, "
            "high quality, clean background, commercial photography, "
            "8K resolution, professional lighting, product showcase"
        )
        return await self.generate_image(prompt, model="black-forest-labs/FLUX.1-schnell")

    async def generate_social_media_image(
        self, text: str, niche: str, platform: str = "instagram"
    ) -> dict[str, Any]:
        """Genera imagen optimizada para redes sociales."""
        size_map = {
            "instagram": (1024, 1024),
            "twitter": (1200, 628),
            "linkedin": (1200, 628),
            "tiktok": (1080, 1920),
        }
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
                return {
                    "success": True,
                    "translated": result2[0].get("translation_text", ""),
                    "source": source,
                    "target": target,
                }
            return {"success": False, "error": "Traducción no disponible para este par de idiomas"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def translate_to_many(self, text: str, source: str, targets: list[str]) -> dict[str, str]:
        """Traduce texto a múltiples idiomas simultáneamente."""
        tasks = [self.translate(text, source, t) for t in targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            lang: (r.get("translated", "") if isinstance(r, dict) and r.get("success") else text)
            for lang, r in zip(targets, results, strict=False)
        }

    async def translate_product_listing(
        self, listing: dict, source: str = "es", targets: list[str] | None = None
    ) -> dict[str, Any]:
        """Traduce un listing de producto completo a múltiples idiomas."""
        if not targets:
            targets = ["en", "fr", "de", "pt", "it", "ja", "zh"]
        results: dict[str, dict] = {}
        for lang in targets:
            name = await self.translate(listing.get("name", ""), source, lang)
            desc = await self.translate(listing.get("description", ""), source, lang)
            results[lang] = {
                "name": name.get("translated", ""),
                "description": desc.get("translated", ""),
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
            result = await self._call(
                model,
                {
                    "inputs": text[:3000],
                    "parameters": {
                        "max_length": max_length,
                        "min_length": min_length,
                        "do_sample": False,
                    },
                },
            )
            if result and isinstance(result, list):
                return {
                    "success": True,
                    "summary": result[0].get("summary_text", ""),
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
        return [
            r.get("summary", "") if isinstance(r, dict) and r.get("success") else ""
            for r in results
        ]

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
            model = (
                "lxyuan/distilbert-base-multilingual-cased-sentiments-student"
                if multilingual
                else "cardiffnlp/twitter-roberta-base-sentiment-latest"
            )
            result = await self._call(model, {"inputs": text[:512]})
            if result and isinstance(result, list):
                scores = result[0] if isinstance(result[0], list) else result
                best = max(scores, key=lambda x: x.get("score", 0))
                label = best.get("label", "").lower()
                normalized = (
                    "positivo" if "pos" in label else "negativo" if "neg" in label else "neutro"
                )
                return {
                    "success": True,
                    "sentiment": normalized,
                    "confidence": round(best.get("score", 0), 3),
                    "all_scores": {s.get("label", ""): round(s.get("score", 0), 3) for s in scores},
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
            "positive_pct": round(pos / total * 100, 1),
            "negative_pct": round(neg / total * 100, 1),
            "neutral_pct": round(neu / total * 100, 1),
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
            result = await self._call(
                model,
                {
                    "inputs": text[:1000],
                    "parameters": {
                        "candidate_labels": candidate_labels,
                        "hypothesis_template": hypothesis_template,
                    },
                },
            )
            if result and "labels" in result:
                return {
                    "success": True,
                    "best_label": result["labels"][0],
                    "best_score": round(result["scores"][0], 3),
                    "all_labels": dict(
                        zip(result["labels"], [round(s, 3) for s in result["scores"]], strict=False)
                    ),
                }
            return {"success": False, "error": "Sin resultado de clasificación"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def classify_product_niche(self, product_description: str) -> dict[str, Any]:
        """Clasifica un producto en su nicho de mercado automáticamente."""
        niches = [
            "health and wellness",
            "personal finance",
            "digital marketing",
            "technology and software",
            "education and online courses",
            "fitness and sports",
            "beauty and fashion",
            "food and cooking",
            "travel and lifestyle",
            "business and entrepreneurship",
            "entertainment and gaming",
            "relationships and dating",
        ]
        return await self.classify_zero_shot(product_description, niches)

    async def classify_content_type(self, content: str) -> dict[str, Any]:
        """Clasifica el tipo de contenido."""
        types = [
            "educational",
            "promotional",
            "entertaining",
            "informational",
            "inspirational",
            "controversial",
        ]
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
                    entity_type = (
                        e.get("entity_group", e.get("entity", ""))
                        .replace("B-", "")
                        .replace("I-", "")
                    )
                    word = e.get("word", "").replace("##", "")
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
            result = await self._call(
                model, {"inputs": {"question": question, "context": context[:3000]}}
            )
            if result and isinstance(result, dict):
                return {
                    "success": True,
                    "answer": result.get("answer", ""),
                    "confidence": round(result.get("score", 0), 3),
                    "start": result.get("start", 0),
                    "end": result.get("end", 0),
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
                return {
                    "success": True,
                    "embeddings": result,
                    "model": model,
                    "dimensions": len(result[0]) if result else 0,
                }
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
        dot = sum(a * b for a, b in zip(e1, e2, strict=False))
        norm1 = math.sqrt(sum(a**2 for a in e1))
        norm2 = math.sqrt(sum(b**2 for b in e2))
        similarity = dot / (norm1 * norm2) if norm1 * norm2 > 0 else 0
        return {
            "success": True,
            "similarity": round(similarity, 4),
            "text1": text1[:100],
            "text2": text2[:100],
        }

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
            d = sum(x * y for x, y in zip(a, b, strict=False))
            return d / (math.sqrt(sum(x**2 for x in a)) * math.sqrt(sum(y**2 for y in b)) + 1e-9)

        scores = [(candidates[i], cosine(q_emb, embs[i + 1])) for i in range(len(candidates))]
        scores.sort(key=lambda x: x[1], reverse=True)
        return {
            "success": True,
            "query": query,
            "ranked": [(t, round(s, 4)) for t, s in scores[:10]],
        }

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
                    "transcript": result.get("text", ""),
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
                await _assert_public_url(image_url)
                res = await self._http.get(image_url, timeout=30.0)
                image_bytes = res.content

            result = await self._call(model, image_bytes, binary=False, timeout=60.0)
            if result and isinstance(result, list):
                description = result[0].get("generated_text", "")
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
                    {
                        "label": o.get("label", ""),
                        "confidence": round(o.get("score", 0), 3),
                        "box": o.get("box", {}),
                    }
                    for o in result
                    if o.get("score", 0) >= threshold
                ]
                labels = list({o["label"] for o in detected})
                return {
                    "success": True,
                    "objects": detected,
                    "unique_labels": labels,
                    "count": len(detected),
                }
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
                    "top_label": result[0].get("label", ""),
                    "top_score": round(result[0].get("score", 0), 3),
                    "all": [
                        {"label": r.get("label", ""), "score": round(r.get("score", 0), 3)}
                        for r in result[:5]
                    ],
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
                    "predictions": [
                        {
                            "text": r.get("sequence", ""),
                            "token": r.get("token_str", ""),
                            "score": round(r.get("score", 0), 3),
                        }
                        for r in result[:5]
                    ],
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
            result = await self._call(
                "papluca/xlm-roberta-base-language-detection", {"inputs": text[:512]}
            )
            if result and isinstance(result, list):
                best = max(
                    result[0] if isinstance(result[0], list) else result,
                    key=lambda x: x.get("score", 0),
                )
                return {
                    "success": True,
                    "language": best.get("label", ""),
                    "confidence": round(best.get("score", 0), 3),
                }
            return {"success": False, "error": "Sin resultado"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 16. CLASIFICACIÓN DE AUDIO
    # ══════════════════════════════════════════════════════════════

    async def classify_audio(
        self,
        audio_bytes: bytes,
        model: str = "ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition",
    ) -> dict[str, Any]:
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
                return {
                    "success": True,
                    "classifications": [
                        {"label": r.get("label", ""), "score": round(r.get("score", 0), 3)}
                        for r in result[:5]
                    ],
                }
            return {"success": False, "error": "Sin clasificación de audio"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 17. ESTIMACIÓN DE PROFUNDIDAD
    # ══════════════════════════════════════════════════════════════

    async def estimate_depth(
        self, image_bytes: bytes, model: str = "depth-anything/Depth-Anything-V2-Small-hf"
    ) -> dict[str, Any]:
        """Estima profundidad de una imagen — útil para análisis de producto."""
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(model, image_bytes, binary=True, timeout=60.0)
            if result:
                return {
                    "success": True,
                    "depth_image_bytes": result,
                    "depth_b64": base64.b64encode(result).decode(),
                }
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

            ai = get_ai_client()
            response = await ai.complete(
                system=f"You are an expert {language} developer. Generate clean, production-ready code. Return only code, no explanations unless asked.",
                user=prompt,
                model=AIModel.CODE,
            )
            if response and response.success:
                return {
                    "success": True,
                    "code": response.content,
                    "language": language,
                    "model": response.model,
                }
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
            source="es",
            targets=languages,
        )

        results = await asyncio.gather(
            img_task,
            social_task,
            thumb_task,
            summary_task,
            niche_task,
            sentiment_task,
            translate_task,
            return_exceptions=True,
        )
        img, social, thumb, summary, niche_cls, sentiment, translations = results

        return {
            "success": True,
            "product_name": product_name,
            "niche": niche,
            "product_image": {
                "b64": (
                    img.get("image_b64", "")[:100] + "..."
                    if isinstance(img, dict) and img.get("success")
                    else None
                )
            },
            "social_image": {
                "b64": (
                    social.get("image_b64", "")[:100] + "..."
                    if isinstance(social, dict) and social.get("success")
                    else None
                )
            },
            "blog_thumbnail": {
                "b64": (
                    thumb.get("image_b64", "")[:100] + "..."
                    if isinstance(thumb, dict) and thumb.get("success")
                    else None
                )
            },
            "summary": summary.get("summary", "") if isinstance(summary, dict) else "",
            "niche_classification": (
                niche_cls.get("best_label", "") if isinstance(niche_cls, dict) else niche
            ),
            "market_sentiment": (
                sentiment.get("sentiment", "") if isinstance(sentiment, dict) else ""
            ),
            "translations": (
                translations.get("listings", {}) if isinstance(translations, dict) else {}
            ),
        }

    # ══════════════════════════════════════════════════════════════
    # 19. ANÁLISIS COMPLETO DE COMPETENCIA con HF
    # ══════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════
    # 20. VISUAL QUESTION ANSWERING (VQA) — Computer Vision Course
    # ══════════════════════════════════════════════════════════════

    async def visual_question_answering(
        self,
        image_bytes: bytes,
        question: str,
        model: str = "dandelin/vilt-b32-finetuned-vqa",
    ) -> dict[str, Any]:
        """
        Responde preguntas sobre el contenido de una imagen.
        El usuario envía una foto y hace cualquier pregunta sobre ella.
        Modelos: dandelin/vilt-b32-finetuned-vqa, Salesforce/blip-vqa-base
        Ejemplos: "¿Cuántas personas hay?", "¿Qué color es el auto?", "¿Es de noche o de día?"
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            img_b64 = base64.b64encode(image_bytes).decode()
            payload = {"inputs": {"image": img_b64, "question": question}}
            result = await self._call(model, payload, timeout=60.0)
            if result and isinstance(result, list) and result:
                best = max(result, key=lambda x: x.get("score", 0))
                return {
                    "success": True,
                    "answer": best.get("answer", ""),
                    "confidence": round(best.get("score", 0), 3),
                    "all_answers": [
                        {"answer": r.get("answer", ""), "score": round(r.get("score", 0), 3)}
                        for r in result[:5]
                    ],
                    "question": question,
                }
            return {"success": False, "error": "Sin respuesta del modelo VQA"}
        except Exception as exc:
            logger.error("[HF] visual_question_answering error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 21. GENERACIÓN DE MÚSICA — MusicGen (Audio Course)
    # ══════════════════════════════════════════════════════════════

    async def generate_music(
        self,
        prompt: str,
        duration: int = 15,
        model: str = "facebook/musicgen-small",
    ) -> dict[str, Any]:
        """
        Genera música de alta calidad con MusicGen.
        Modelos: facebook/musicgen-small (rápido), facebook/musicgen-medium (mejor calidad)
        Duración recomendada: 10-30 segundos (limitación de la API gratuita).
        Ejemplos: "relaxing jazz piano", "energetic electronic beat", "cinematic orchestral"
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(
                model,
                {
                    "inputs": prompt,
                    "parameters": {"max_new_tokens": min(duration * 50, 1500)},
                },
                binary=True,
                timeout=120.0,
            )
            if result and isinstance(result, bytes) and len(result) > 100:
                return {
                    "success": True,
                    "audio_bytes": result,
                    "audio_b64": base64.b64encode(result).decode(),
                    "prompt": prompt,
                    "model": model,
                    "duration_requested": duration,
                }
            return {"success": False, "error": "MusicGen no generó audio válido"}
        except Exception as exc:
            logger.error("[HF] generate_music error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 22. IMAGE-TO-IMAGE — instruct-pix2pix (Diffusion Course)
    # ══════════════════════════════════════════════════════════════

    async def image_to_image(
        self,
        image_bytes: bytes,
        prompt: str,
        model: str = "timbrooks/instruct-pix2pix",
    ) -> dict[str, Any]:
        """
        Transforma una imagen con instrucciones en lenguaje natural (img2img).
        Modelo: timbrooks/instruct-pix2pix
        Ejemplos de prompt: "convierte a estilo anime", "añade nieve al fondo",
                            "cambia el día a noche", "haz que sea un dibujo a lápiz"
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            img_b64 = base64.b64encode(image_bytes).decode()
            payload = {
                "inputs": {"prompt": prompt, "image": img_b64},
                "parameters": {
                    "image_guidance_scale": 1.5,
                    "guidance_scale": 7.0,
                    "num_inference_steps": 20,
                },
            }
            result_bytes = await self._call(model, payload, binary=True, timeout=120.0)
            if result_bytes:
                return {
                    "success": True,
                    "image_bytes": result_bytes,
                    "image_b64": base64.b64encode(result_bytes).decode(),
                    "prompt": prompt,
                    "model": model,
                }
            return {"success": False, "error": "No se pudo transformar la imagen"}
        except Exception as exc:
            logger.error("[HF] image_to_image error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 23. ZERO-SHOT IMAGE CLASSIFICATION — CLIP (Computer Vision)
    # ══════════════════════════════════════════════════════════════

    async def zero_shot_classify_image(
        self,
        image_bytes: bytes,
        candidate_labels: list[str],
        model: str = "openai/clip-vit-base-patch32",
    ) -> dict[str, Any]:
        """
        Clasifica una imagen en CUALQUIER categoría sin entrenamiento previo usando CLIP.
        Modelos: openai/clip-vit-base-patch32, openai/clip-vit-large-patch14
        Ejemplos: ["cat","dog"], ["indoors","outdoors"], ["happy","sad","neutral"]
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            img_b64 = base64.b64encode(image_bytes).decode()
            payload = {"inputs": {"image": img_b64, "text": candidate_labels}}
            result = await self._call(model, payload, timeout=60.0)
            if result and isinstance(result, list) and result:
                return {
                    "success": True,
                    "top_label": result[0].get("label", ""),
                    "top_score": round(result[0].get("score", 0), 3),
                    "all": [
                        {"label": r.get("label", ""), "score": round(r.get("score", 0), 3)}
                        for r in result[:5]
                    ],
                }
            return {"success": False, "error": "Sin resultado de clasificación CLIP"}
        except Exception as exc:
            logger.error("[HF] zero_shot_classify_image error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 24. DOCUMENT QA — LayoutLM (LLM Course — Document Understanding)
    # ══════════════════════════════════════════════════════════════

    async def document_qa(
        self,
        image_bytes: bytes,
        question: str,
        model: str = "impira/layoutlm-document-qa",
    ) -> dict[str, Any]:
        """
        Extrae información de documentos escaneados, facturas y formularios.
        Modelo: impira/layoutlm-document-qa
        Útil para: extraer datos de facturas, preguntas sobre contratos, formularios.
        Ejemplo: "¿Cuál es el total?", "¿A nombre de quién está la factura?"
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            img_b64 = base64.b64encode(image_bytes).decode()
            result = await self._call(
                model,
                {"inputs": {"image": img_b64, "question": question}},
                timeout=60.0,
            )
            if result and isinstance(result, list) and result:
                best = max(result, key=lambda x: x.get("score", 0))
                return {
                    "success": True,
                    "answer": best.get("answer", ""),
                    "confidence": round(best.get("score", 0), 3),
                    "question": question,
                }
            if isinstance(result, dict) and result.get("answer"):
                return {
                    "success": True,
                    "answer": result.get("answer", ""),
                    "confidence": round(result.get("score", 0), 3),
                    "question": question,
                }
            return {"success": False, "error": "Sin respuesta del modelo de documento"}
        except Exception as exc:
            logger.error("[HF] document_qa error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 25. STRUCTURED OUTPUT — AsyncInferenceClient (LLM Course)
    # ══════════════════════════════════════════════════════════════

    async def generate_structured(
        self,
        prompt: str,
        schema: dict,
        model: str = "Qwen/Qwen2.5-72B-Instruct",
        system: str = "",
    ) -> dict[str, Any]:
        """
        Genera JSON estructurado garantizado usando response_format de AsyncInferenceClient.
        Schema debe ser JSON Schema: {"type":"object","properties":{...},"required":[...]}
        Ideal para: extraer datos estructurados, generar fichas de producto, crear templates.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            from huggingface_hub import AsyncInferenceClient

            client = AsyncInferenceClient(provider="hf-inference", api_key=self._token)
            sys_msg = (
                system
                or "You are a structured data extraction assistant. Always respond with valid JSON following the provided schema exactly."
            )
            messages = [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": prompt},
            ]
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=1024,
                    temperature=0.1,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": "structured_output", "schema": schema},
                    },
                ),
                timeout=60.0,
            )
            content = (response.choices[0].message.content or "").strip()
            try:
                parsed = json.loads(content)
                return {"success": True, "data": parsed, "raw": content, "model": model}
            except json.JSONDecodeError:
                return {"success": False, "error": f"JSON inválido: {content[:200]}"}
        except Exception as exc:
            logger.error("[HF] generate_structured error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 26. SEARCH AGENT — smolagents-style (Agents Course)
    # ══════════════════════════════════════════════════════════════

    async def run_search_agent(self, task: str, max_steps: int = 5) -> dict[str, Any]:
        """
        Agente autónomo de investigación estilo smolagents: plan → search → reason → synthesize.
        Útil para: investigación profunda, síntesis de información, respuestas compuestas.
        Implementa el patrón ReAct (Reason + Act) del Agents Course de HuggingFace.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            from apps.core.tools.web_tools import WebTools

            ai = get_ai_client()
            wt = WebTools()
            steps_log: list[dict] = []
            context = f"Task: {task}\n"

            # Step 1: Plan — generate search queries
            plan_resp = await ai.complete(
                system='You are a research agent. Given a task, generate exactly 2 specific search queries. Return JSON array only: ["query1", "query2"]',
                user=f"Task: {task}",
                model=AIModel.FAST,
                max_tokens=150,
                temperature=0.2,
            )
            queries = [task]
            if plan_resp and plan_resp.success:
                raw = plan_resp.content.strip()
                if "[" in raw:
                    try:
                        raw = raw[raw.index("[") : raw.rindex("]") + 1]
                        queries = json.loads(raw)[:2]
                    except Exception:
                        pass
            steps_log.append({"step": "plan", "queries": queries})

            # Step 2: Act — execute searches
            for query in queries:
                r = await wt.search_web(query, num_results=5)
                if r.get("success") and r.get("results"):
                    snippets = "\n".join(
                        f"- {res.get('title', '')}: {res.get('snippet', '')[:200]}"
                        for res in r["results"][:4]
                    )
                    context += f"\nSearch: '{query}':\n{snippets}\n"
                    steps_log.append(
                        {"step": "search", "query": query, "results": len(r["results"])}
                    )

            # Step 3: Reason + Synthesize
            synth_resp = await ai.complete(
                system="You are a research synthesizer. Given a task and search results, produce a comprehensive answer in bullet points with key findings and actionable conclusions.",
                user=context[:3000],
                model=AIModel.STRATEGY,
                max_tokens=800,
                temperature=0.3,
            )
            answer = (
                synth_resp.content
                if (synth_resp and synth_resp.success)
                else "No se pudo sintetizar la respuesta."
            )
            steps_log.append({"step": "synthesize", "answer_length": len(answer)})

            return {
                "success": True,
                "task": task,
                "answer": answer,
                "steps": steps_log,
                "steps_count": len(steps_log),
            }
        except Exception as exc:
            logger.error("[HF] run_search_agent error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 27. IMAGE-TEXT-TO-TEXT — Vision Language Models (Multimodal)
    # ══════════════════════════════════════════════════════════════

    async def vision_language(
        self,
        image_bytes: bytes,
        question: str,
        model: str = "meta-llama/Llama-3.2-11B-Vision-Instruct",
    ) -> dict[str, Any]:
        """
        Vision-Language Model: analiza imágenes con razonamiento avanzado.
        Más potente que VQA básico — entiende contexto, razona y explica.
        Modelos: meta-llama/Llama-3.2-11B-Vision-Instruct (potente),
                 HuggingFaceTB/SmolVLM-Instruct (rápido),
                 Qwen/Qwen2.5-VL-3B-Instruct (eficiente)
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            from huggingface_hub import AsyncInferenceClient

            img_b64 = base64.b64encode(image_bytes).decode()
            client = AsyncInferenceClient(provider="hf-inference", api_key=self._token)
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                                },
                                {"type": "text", "text": question},
                            ],
                        }
                    ],
                    max_tokens=512,
                    temperature=0.4,
                ),
                timeout=90.0,
            )
            answer = (response.choices[0].message.content or "").strip()
            if answer:
                return {"success": True, "answer": answer, "model": model, "question": question}
            return {"success": False, "error": "Sin respuesta del modelo de visión"}
        except Exception as exc:
            logger.error("[HF] vision_language error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 28. IMAGE SEGMENTATION — mask2former, briaai RMBG
    # ══════════════════════════════════════════════════════════════

    async def segment_image(
        self,
        image_bytes: bytes,
        model: str = "facebook/mask2former-swin-base-coco-panoptic",
    ) -> dict[str, Any]:
        """
        Segmenta objetos en una imagen con máscaras.
        Modelos: facebook/mask2former-swin-base-coco-panoptic (panoptic),
                 briaai/RMBG-1.4 (remoción de fondo),
                 facebook/mask2former-swin-large-cityscapes-semantic (semántico)
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(model, image_bytes, binary=False, timeout=90.0)
            if result and isinstance(result, list):
                segments = [
                    {
                        "label": s.get("label", ""),
                        "score": round(s.get("score", 0), 3),
                        "mask_b64": s.get("mask", ""),
                    }
                    for s in result[:10]
                ]
                labels = list(dict.fromkeys(s["label"] for s in segments if s["label"]))
                return {
                    "success": True,
                    "segments": segments,
                    "unique_labels": labels,
                    "count": len(segments),
                    "model": model,
                }
            return {"success": False, "error": "Sin segmentación generada"}
        except Exception as exc:
            logger.error("[HF] segment_image error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 29. ZERO-SHOT OBJECT DETECTION — OWL-ViT
    # ══════════════════════════════════════════════════════════════

    async def zero_shot_detect_objects(
        self,
        image_bytes: bytes,
        candidate_labels: list[str],
        threshold: float = 0.1,
        model: str = "google/owlvit-base-patch32",
    ) -> dict[str, Any]:
        """
        Detecta objetos específicos por descripción textual sin entrenamiento (OWL-ViT).
        Modelos: google/owlvit-base-patch32, google/owlvit-large-patch14
        Ejemplo labels: ["a photo of a cat", "a photo of a car", "person running"]
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            img_b64 = base64.b64encode(image_bytes).decode()
            result = await self._call(
                model,
                {"inputs": {"image": img_b64, "candidate_labels": candidate_labels}},
                timeout=60.0,
            )
            if not result:
                result = await self._call(
                    model,
                    image_bytes,
                    binary=False,
                    timeout=60.0,
                )
            if result and isinstance(result, list):
                detected = [
                    {
                        "label": o.get("label", ""),
                        "score": round(o.get("score", 0), 3),
                        "box": o.get("box", {}),
                    }
                    for o in result
                    if o.get("score", 0) >= threshold
                ]
                return {
                    "success": True,
                    "detections": detected,
                    "count": len(detected),
                    "labels_searched": candidate_labels,
                }
            return {"success": False, "error": "Sin detecciones"}
        except Exception as exc:
            logger.error("[HF] zero_shot_detect_objects error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 30. AUDIO-TO-AUDIO — Speech Enhancement & Separation
    # ══════════════════════════════════════════════════════════════

    async def enhance_audio(
        self,
        audio_bytes: bytes,
        model: str = "speechbrain/mtl-mimic-voicebank",
    ) -> dict[str, Any]:
        """
        Mejora calidad de audio: reduce ruido, enhances speech.
        Modelos: speechbrain/mtl-mimic-voicebank (enhancement),
                 speechbrain/sepformer-wham (source separation)
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(model, audio_bytes, binary=True, timeout=90.0)
            if result and isinstance(result, bytes) and len(result) > 100:
                return {
                    "success": True,
                    "audio_bytes": result,
                    "audio_b64": base64.b64encode(result).decode(),
                    "model": model,
                }
            return {"success": False, "error": "Sin audio mejorado"}
        except Exception as exc:
            logger.error("[HF] enhance_audio error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 31. TEXT RANKING — Cross-Encoder (Multimodal Retrieval)
    # ══════════════════════════════════════════════════════════════

    async def rank_texts(
        self,
        query: str,
        passages: list[str],
        model: str = "cross-encoder/ms-marco-MiniLM-L6-v2",
    ) -> dict[str, Any]:
        """
        Ordena documentos/textos por relevancia a un query (reranking).
        Modelo: cross-encoder/ms-marco-MiniLM-L6-v2 (eficiente),
                Alibaba-NLP/gte-multilingual-reranker-base (multilingüe)
        Ideal para: mejorar resultados de búsqueda, RAG reranking.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            pairs = [[query, p] for p in passages]
            result = await self._call(model, {"inputs": pairs})
            if result and isinstance(result, list):
                scored = sorted(
                    [
                        (passages[i], float(result[i]))
                        for i in range(min(len(passages), len(result)))
                    ],
                    key=lambda x: x[1],
                    reverse=True,
                )
                return {
                    "success": True,
                    "query": query,
                    "ranked": [{"text": t[:200], "score": round(s, 4)} for t, s in scored],
                    "top_passage": scored[0][0] if scored else "",
                }
            return {"success": False, "error": "Sin scores de ranking"}
        except Exception as exc:
            logger.error("[HF] rank_texts error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 32. IMAGE FEATURE EXTRACTION — ViT, DINO (Visual Embeddings)
    # ══════════════════════════════════════════════════════════════

    async def extract_image_features(
        self,
        image_bytes: bytes,
        model: str = "facebook/dino-vitb16",
    ) -> dict[str, Any]:
        """
        Extrae embeddings visuales de imágenes para búsqueda semántica visual.
        Modelos: facebook/dino-vitb16 (robusto), google/vit-base-patch16-384 (preciso)
        Útil para: similaridad visual, agrupamiento de imágenes, búsqueda por imagen.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(model, image_bytes, binary=False, timeout=60.0)
            if result and isinstance(result, list):
                flat = result
                if isinstance(flat[0], list):
                    flat = flat[0]
                if isinstance(flat[0], list):
                    flat = flat[0]
                return {
                    "success": True,
                    "features": flat[:100],
                    "dimensions": len(flat),
                    "model": model,
                }
            return {"success": False, "error": "Sin features de imagen"}
        except Exception as exc:
            logger.error("[HF] extract_image_features error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 33. TABLE QUESTION ANSWERING — TAPAS
    # ══════════════════════════════════════════════════════════════

    async def table_question_answering(
        self,
        table: dict[str, list],
        question: str,
        model: str = "google/tapas-base-finetuned-wtq",
    ) -> dict[str, Any]:
        """
        Responde preguntas sobre tablas de datos.
        Modelos: google/tapas-base-finetuned-wtq, microsoft/tapex-base
        Ejemplo: table={"Name":["Alice","Bob"],"Score":["90","85"]}, question="Who has the highest score?"
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(
                model,
                {"inputs": {"table": table, "query": question}},
                timeout=60.0,
            )
            if result and isinstance(result, dict):
                return {
                    "success": True,
                    "answer": result.get("cells", result.get("answer", "")),
                    "aggregator": result.get("aggregator", ""),
                    "question": question,
                }
            return {"success": False, "error": "Sin respuesta de tabla"}
        except Exception as exc:
            logger.error("[HF] table_question_answering error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 34. MASK GENERATION — SAM (Segment Anything Model)
    # ══════════════════════════════════════════════════════════════

    async def generate_masks(
        self,
        image_bytes: bytes,
        model: str = "Zigeng/SlimSAM-uniform-50",
    ) -> dict[str, Any]:
        """
        Genera máscaras para TODOS los objetos en una imagen (SAM).
        Modelos: Zigeng/SlimSAM-uniform-50 (rápido), facebook/sam2-hiera-large (preciso)
        Útil para: separar objetos, remoción de fondo avanzada, edición de imagen.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            result = await self._call(model, image_bytes, binary=False, timeout=90.0)
            if result and isinstance(result, list):
                masks = [
                    {"score": round(m.get("score", 0), 3), "mask_b64": m.get("mask", "")}
                    for m in result[:20]
                ]
                return {
                    "success": True,
                    "masks": masks,
                    "count": len(masks),
                    "model": model,
                }
            return {"success": False, "error": "Sin máscaras generadas"}
        except Exception as exc:
            logger.error("[HF] generate_masks error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def analyze_competitor_content(
        self, content_list: list[str], niche: str
    ) -> dict[str, Any]:
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

        pos = sum(1 for s in sentiments if isinstance(s, dict) and s.get("sentiment") == "positivo")
        neg = sum(1 for s in sentiments if isinstance(s, dict) and s.get("sentiment") == "negativo")

        return {
            "success": True,
            "niche": niche,
            "analyzed": len(content_list),
            "sentiment_distribution": {
                "positive": pos,
                "negative": neg,
                "neutral": len(sentiments) - pos - neg,
            },
            "dominant_content_type": (
                content_types[0].get("best_label", "")
                if content_types and isinstance(content_types[0], dict)
                else ""
            ),
            "key_insights": summary.get("summary", ""),
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # HF SPACES — Free capabilities via Gradio API (no paid GPU required)
    # ═══════════════════════════════════════════════════════════════════════════
    #
    # Each Space is accessed via its Gradio HTTP API (4.x SSE or 3.x /api/predict).
    # HF_TOKEN is passed as Bearer to access ZeroGPU queues.
    # All methods are async and return {"success": bool, ...result_fields}.

    # ── Private Gradio helpers ─────────────────────────────────────────────

    def _space_url(self, space_id: str) -> str:
        """Convert 'owner/space-name' to HF Space base URL."""
        parts = space_id.lower().replace(".", "-").split("/", 1)
        return f"https://{parts[0]}-{parts[1]}.hf.space"

    def _gradio_image_data(self, image_bytes: bytes) -> dict:
        """Wrap bytes as Gradio 4.x FileData dict for image inputs."""
        b64 = base64.b64encode(image_bytes).decode()
        mime = "image/png" if image_bytes[:4] == b"\x89PNG" else "image/jpeg"
        return {
            "url": f"data:{mime};base64,{b64}",
            "orig_name": "image.jpg",
            "size": len(image_bytes),
            "mime_type": mime,
            "is_stream": False,
            "meta": {"_type": "gradio.FileData"},
        }

    def _gradio_audio_data(self, audio_bytes: bytes) -> dict:
        """Wrap bytes as Gradio 4.x FileData dict for audio inputs."""
        b64 = base64.b64encode(audio_bytes).decode()
        return {
            "url": f"data:audio/wav;base64,{b64}",
            "orig_name": "audio.wav",
            "size": len(audio_bytes),
            "mime_type": "audio/wav",
            "is_stream": False,
            "meta": {"_type": "gradio.FileData"},
        }

    async def _gradio_call(
        self,
        space_id: str,
        fn_name: str,
        data: list,
        timeout: float = 120.0,
    ) -> list | None:
        """
        Call a HuggingFace Space via Gradio 4.x API (SSE) with fallback to v3 /api/predict.
        Returns the output data list or None on failure.
        """
        base_url = self._space_url(space_id)
        headers = self._headers({"Content-Type": "application/json"})
        # Try Gradio 4.x: POST /call/{fn} → SSE stream
        try:
            r = await self._http.post(
                f"{base_url}/call/{fn_name}",
                json={"data": data},
                headers=headers,
                timeout=30.0,
            )
            if r.status_code == 200:
                event_id = r.json().get("event_id")
                if event_id:
                    return await self._poll_gradio_sse(
                        f"{base_url}/call/{fn_name}/{event_id}", timeout=timeout
                    )
        except Exception:
            pass
        # Fallback: Gradio 3.x /api/predict
        try:
            r2 = await self._http.post(
                f"{base_url}/api/predict",
                json={"data": data, "fn_index": 0},
                headers=headers,
                timeout=timeout,
            )
            if r2.status_code == 200:
                return r2.json().get("data")
        except Exception:
            pass
        return None

    async def _poll_gradio_sse(self, url: str, timeout: float = 120.0) -> list | None:
        """Read a Gradio SSE stream and return the 'complete' event's data list."""
        result = None
        current_event: str | None = None
        try:
            async with self._http.stream("GET", url, headers=self._headers(), timeout=timeout) as r:
                async for line in r.aiter_lines():
                    line = line.strip()
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                    elif line.startswith("data:"):
                        payload_str = line[5:].strip()
                        if not payload_str:
                            continue
                        if current_event == "error":
                            logger.warning("[HF Space] SSE error: %s", payload_str[:200])
                            break
                        if current_event in ("complete", "generating", None):
                            try:
                                parsed = json.loads(payload_str)
                                if isinstance(parsed, list):
                                    result = parsed
                                    if current_event == "complete":
                                        break
                            except Exception:
                                pass
        except Exception as exc:
            logger.debug("[HF Space] SSE stream: %s", exc)
        return result

    async def _resolve_gradio_item(self, item: Any) -> bytes | str | None:
        """Resolve a Gradio output item to bytes (media) or str (text)."""
        if isinstance(item, dict):
            url = item.get("url", "")
            if url.startswith("data:"):
                try:
                    _, b64_part = url.split(",", 1)
                    return base64.b64decode(b64_part)
                except Exception:
                    pass
            if url.startswith("http"):
                try:
                    r = await self._http.get(url, headers=self._headers(), timeout=60.0)
                    if r.status_code == 200:
                        return r.content
                except Exception:
                    pass
        if isinstance(item, str) and len(item) > 2:
            return item
        return None

    # ── Public Space methods ───────────────────────────────────────────────

    async def remove_background(self, image_bytes: bytes) -> dict[str, Any]:
        """
        Remove image background with BiRefNet (best-in-class matting model).
        Space: not-lain/background-removal — 2.8k likes, always running.
        Returns PNG with transparent background.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            data = [self._gradio_image_data(image_bytes)]
            result = await self._gradio_call(
                "not-lain/background-removal", "predict", data, timeout=90.0
            )
            if result:
                for item in result:
                    resolved = await self._resolve_gradio_item(item)
                    if resolved and isinstance(resolved, bytes):
                        return {"success": True, "image_bytes": resolved, "format": "png"}
            return {"success": False, "error": "Sin resultado del Space"}
        except Exception as exc:
            logger.error("[HF Space] remove_background: %s", exc)
            return {"success": False, "error": str(exc)}

    async def kokoro_tts(
        self, text: str, voice: str = "af_heart", speed: float = 1.0
    ) -> dict[str, Any]:
        """
        Fast high-quality TTS with preset voices (Kokoro 82M model).
        Space: hexgrad/Kokoro-TTS — 3.3k likes, low-latency.
        Voices: af_heart, af_bella, bf_emma, am_adam, bm_lewis, etc.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            data = [text[:500], voice, speed]
            result = await self._gradio_call(
                "hexgrad/Kokoro-TTS", "generate_first", data, timeout=60.0
            )
            if result:
                for item in result:
                    resolved = await self._resolve_gradio_item(item)
                    if resolved and isinstance(resolved, bytes):
                        return {"success": True, "audio_bytes": resolved}
            return {"success": False, "error": "Sin audio generado"}
        except Exception as exc:
            logger.error("[HF Space] kokoro_tts: %s", exc)
            return {"success": False, "error": str(exc)}

    async def clone_voice(
        self, ref_audio_bytes: bytes, ref_text: str, gen_text: str
    ) -> dict[str, Any]:
        """
        Zero-shot voice cloning via F5-TTS / E2-TTS.
        Space: mrfakename/E2-F5-TTS — 2.8k likes.
        Upload 3-10s of any speaker → generate that voice saying gen_text.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            audio_data = self._gradio_audio_data(ref_audio_bytes)
            data = [audio_data, ref_text, gen_text, True]  # True = remove silence
            result = await self._gradio_call("mrfakename/E2-F5-TTS", "infer", data, timeout=120.0)
            if result:
                for item in result:
                    resolved = await self._resolve_gradio_item(item)
                    if resolved and isinstance(resolved, bytes):
                        return {"success": True, "audio_bytes": resolved}
            return {"success": False, "error": "Sin audio generado"}
        except Exception as exc:
            logger.error("[HF Space] clone_voice: %s", exc)
            return {"success": False, "error": str(exc)}

    async def upscale_image(self, image_bytes: bytes, scale: int = 2) -> dict[str, Any]:
        """
        AI image upscaling / quality enhancement (Clarity AI diffusion upscaler).
        Space: finegrain/finegrain-image-enhancer — 2.1k likes.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            data = [self._gradio_image_data(image_bytes), scale]
            result = await self._gradio_call(
                "finegrain/finegrain-image-enhancer", "enhance", data, timeout=120.0
            )
            if result:
                for item in result:
                    resolved = await self._resolve_gradio_item(item)
                    if resolved and isinstance(resolved, bytes):
                        return {"success": True, "image_bytes": resolved, "scale": scale}
            return {"success": False, "error": "Sin imagen mejorada"}
        except Exception as exc:
            logger.error("[HF Space] upscale_image: %s", exc)
            return {"success": False, "error": str(exc)}

    async def ocr_document_space(self, image_bytes: bytes, task: str = "Text") -> dict[str, Any]:
        """
        OCR: extract text, formulas, or table data from images (GLM-OCR).
        Space: prithivMLmods/GLM-OCR-Demo — handles plain text, math, tables.
        task: 'Text' | 'Formula' | 'Table'
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            data = [self._gradio_image_data(image_bytes), task, 512]
            result = await self._gradio_call(
                "prithivMLmods/GLM-OCR-Demo", "generate", data, timeout=90.0
            )
            if result:
                for item in result:
                    resolved = await self._resolve_gradio_item(item)
                    if isinstance(resolved, str) and resolved.strip():
                        return {"success": True, "text": resolved, "task": task}
            return {"success": False, "error": "Sin texto extraído"}
        except Exception as exc:
            logger.error("[HF Space] ocr_document_space: %s", exc)
            return {"success": False, "error": str(exc)}

    async def estimate_pose(self, image_bytes: bytes) -> dict[str, Any]:
        """
        Detect human pose / body keypoints (RTDetr + ViTPose, COCO 17-keypoint format).
        Space: hysts/ViTPose-transformers — returns annotated image + JSON with keypoints.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            data = [self._gradio_image_data(image_bytes), 0.3, True, True]
            result = await self._gradio_call(
                "hysts/ViTPose-transformers", "detect_pose_image", data, timeout=90.0
            )
            if result and len(result) >= 1:
                annotated = await self._resolve_gradio_item(result[0])
                keypoints = (
                    result[1] if len(result) > 1 and isinstance(result[1], (dict, list)) else {}
                )
                return {
                    "success": True,
                    "image_bytes": annotated if isinstance(annotated, bytes) else None,
                    "keypoints": keypoints,
                }
            return {"success": False, "error": "Sin pose detectada"}
        except Exception as exc:
            logger.error("[HF Space] estimate_pose: %s", exc)
            return {"success": False, "error": str(exc)}

    async def generate_3d_model(
        self, image_bytes: bytes | None = None, prompt: str = ""
    ) -> dict[str, Any]:
        """
        Generate 3D mesh from image or text prompt (Hunyuan3D-2).
        Space: tencent/Hunyuan3D-2 — 3.3k likes, outputs GLB format.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            img_data = self._gradio_image_data(image_bytes) if image_bytes else None
            data = [img_data, prompt, 50, 7.5, 1234, True, True]
            result = await self._gradio_call(
                "tencent/Hunyuan3D-2", "shape_generation", data, timeout=180.0
            )
            if result:
                for item in result:
                    if isinstance(item, dict) and item.get("url", "").startswith("http"):
                        model_bytes = await self._resolve_gradio_item(item)
                        if model_bytes and isinstance(model_bytes, bytes):
                            return {"success": True, "model_bytes": model_bytes, "format": "glb"}
                        return {"success": True, "model_url": item["url"], "format": "glb"}
                    resolved = await self._resolve_gradio_item(item)
                    if resolved and isinstance(resolved, bytes):
                        return {"success": True, "model_bytes": resolved, "format": "glb"}
            return {"success": False, "error": "Sin modelo generado"}
        except Exception as exc:
            logger.error("[HF Space] generate_3d_model: %s", exc)
            return {"success": False, "error": str(exc)}

    async def edit_image_kontext(
        self, image_bytes: bytes, prompt: str, seed: int = 42
    ) -> dict[str, Any]:
        """
        Edit / transform an image with text instructions (FLUX.1-Kontext-Dev).
        Space: black-forest-labs/FLUX.1-Kontext-Dev — 1.6k likes.
        Examples: 'change to night', 'add snow', 'make painted', 'remove person'.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            data = [self._gradio_image_data(image_bytes), prompt, seed, 3.5]
            result = await self._gradio_call(
                "black-forest-labs/FLUX.1-Kontext-Dev", "infer", data, timeout=120.0
            )
            if result:
                for item in result:
                    resolved = await self._resolve_gradio_item(item)
                    if resolved and isinstance(resolved, bytes):
                        return {"success": True, "image_bytes": resolved, "prompt": prompt}
            return {"success": False, "error": "Sin imagen editada"}
        except Exception as exc:
            logger.error("[HF Space] edit_image_kontext: %s", exc)
            return {"success": False, "error": str(exc)}

    async def outpaint_image(
        self,
        image_bytes: bytes,
        target_width: int = 1920,
        target_height: int = 1080,
        prompt: str = "",
    ) -> dict[str, Any]:
        """
        Expand image boundaries beyond its original frame (outpainting).
        Space: fffiloni/diffusers-image-outpaint — 2.5k likes, SDXL + ControlNet.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            data = [
                self._gradio_image_data(image_bytes),
                target_width,
                target_height,
                "Middle",
                60,
                8,
                prompt,
            ]
            result = await self._gradio_call(
                "fffiloni/diffusers-image-outpaint", "infer", data, timeout=120.0
            )
            if result:
                for item in result:
                    resolved = await self._resolve_gradio_item(item)
                    if resolved and isinstance(resolved, bytes):
                        return {"success": True, "image_bytes": resolved}
            return {"success": False, "error": "Sin imagen generada"}
        except Exception as exc:
            logger.error("[HF Space] outpaint_image: %s", exc)
            return {"success": False, "error": str(exc)}

    async def colorize_image(self, image_bytes: bytes, description: str = "") -> dict[str, Any]:
        """
        Colorize a grayscale image with text-guided color choices.
        Space: fffiloni/text-guided-image-colorization — only running colorization Space.
        description: e.g. 'make the sky blue and the car red'
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            data = [self._gradio_image_data(image_bytes), description]
            result = await self._gradio_call(
                "fffiloni/text-guided-image-colorization", "predict", data, timeout=90.0
            )
            if result:
                for item in result:
                    resolved = await self._resolve_gradio_item(item)
                    if resolved and isinstance(resolved, bytes):
                        return {"success": True, "image_bytes": resolved}
            return {"success": False, "error": "Sin imagen coloreada"}
        except Exception as exc:
            logger.error("[HF Space] colorize_image: %s", exc)
            return {"success": False, "error": str(exc)}

    async def generate_video_space(
        self,
        prompt: str,
        image_bytes: bytes | None = None,
        width: int = 832,
        height: int = 480,
    ) -> dict[str, Any]:
        """
        Generate video from text+image (Wan2.2 14B FP8, free via ZeroGPU).
        Space: r3gm/wan2-2-fp8da-aoti-preview-2 — 1.8k likes.
        Note: queue times vary; use for async jobs, not real-time.
        """
        if not self._ok():
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            img_data = self._gradio_image_data(image_bytes) if image_bytes else None
            data = [img_data, prompt, 83, 25, 5.0, height, width]
            result = await self._gradio_call(
                "r3gm/wan2-2-fp8da-aoti-preview-2", "generate", data, timeout=300.0
            )
            if result:
                for item in result:
                    if isinstance(item, dict) and item.get("url"):
                        vid_bytes = await self._resolve_gradio_item(item)
                        if vid_bytes and isinstance(vid_bytes, bytes):
                            return {"success": True, "video_bytes": vid_bytes}
                        return {"success": True, "video_url": item["url"]}
                    resolved = await self._resolve_gradio_item(item)
                    if resolved and isinstance(resolved, bytes):
                        return {"success": True, "video_bytes": resolved}
            return {"success": False, "error": "Sin video (ZeroGPU puede tener cola)"}
        except Exception as exc:
            logger.error("[HF Space] generate_video_space: %s", exc)
            return {"success": False, "error": str(exc)}
