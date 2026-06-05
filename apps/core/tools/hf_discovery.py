"""
hf_discovery.py — Motor de descubrimiento y uso de herramientas HuggingFace.

ARIA usa este módulo cuando necesita una capacidad que no tiene.
En lugar de simular o fallar, ARIA busca en HF Hub el mejor modelo
disponible para esa tarea y lo usa inmediatamente via Inference API.

Flujo:
  1. ARIA necesita hacer algo (transcribir audio, detectar idioma, etc.)
  2. Llama a discover_and_run(task="automatic-speech-recognition", input=...)
  3. Este módulo busca el mejor modelo en HF Hub
  4. Lo llama via Inference API
  5. Cachea el modelo ganador para la próxima vez
  6. Retorna el resultado real

Tareas soportadas (y más que se descubren automáticamente):
  - text-generation          → generar texto, código, ideas
  - text2text-generation     → reescribir, resumir, traducir
  - translation              → traducción entre idiomas
  - summarization            → resúmenes de artículos
  - sentiment-analysis       → análisis de sentimiento
  - zero-shot-classification → clasificar sin entrenamiento
  - named-entity-recognition → extraer personas, lugares, empresas
  - question-answering       → responder preguntas con contexto
  - automatic-speech-recognition → transcribir audio (Whisper)
  - text-to-speech           → voz sintetizada
  - image-generation         → crear imágenes (FLUX, SDXL)
  - image-to-text            → describir imágenes (BLIP-2)
  - object-detection         → detectar objetos en imágenes
  - image-classification     → clasificar imágenes
  - feature-extraction       → embeddings de texto o imagen
  - token-classification     → tagging de tokens
  - fill-mask                → completar texto con [MASK]
  - table-question-answering → preguntas sobre tablas
  - document-question-answering → preguntas sobre PDFs/documentos
  - depth-estimation         → profundidad de imagen
  - audio-classification     → clasificar audio
  - visual-question-answering → preguntas sobre imágenes
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any, Optional

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.hf_discovery")

HF_API = "https://api-inference.huggingface.co/models"
HF_HUB = "https://huggingface.co/api"

# Modelos preferidos por tarea (probados, confiables, gratuitos con HF_TOKEN)
# ARIA usa estos primero. Si fallan, busca alternativas en HF Hub.
PREFERRED_MODELS: dict[str, list[str]] = {
    "text-generation": [
        "Qwen/Qwen2.5-Coder-32B-Instruct",
        "meta-llama/Meta-Llama-3-8B-Instruct",
        "mistralai/Mistral-7B-Instruct-v0.3",
    ],
    "text2text-generation": [
        "google/flan-t5-large",
        "facebook/bart-large-cnn",
        "t5-base",
    ],
    "summarization": [
        "facebook/bart-large-cnn",
        "sshleifer/distilbart-cnn-12-6",
        "google/pegasus-xsum",
    ],
    "translation": [
        "Helsinki-NLP/opus-mt-en-es",
        "Helsinki-NLP/opus-mt-es-en",
        "Helsinki-NLP/opus-mt-en-fr",
        "Helsinki-NLP/opus-mt-en-de",
        "Helsinki-NLP/opus-mt-en-zh",
        "Helsinki-NLP/opus-mt-en-ja",
        "Helsinki-NLP/opus-mt-en-pt",
        "Helsinki-NLP/opus-mt-en-ar",
        "Helsinki-NLP/opus-mt-en-ru",
        "Helsinki-NLP/opus-mt-en-it",
    ],
    "sentiment-analysis": [
        "distilbert-base-uncased-finetuned-sst-2-english",
        "cardiffnlp/twitter-roberta-base-sentiment-latest",
        "nlptown/bert-base-multilingual-uncased-sentiment",
        "lxyuan/distilbert-base-multilingual-cased-sentiments-student",
    ],
    "zero-shot-classification": [
        "facebook/bart-large-mnli",
        "cross-encoder/nli-deberta-v3-large",
        "MoritzLaurer/deberta-v3-large-zeroshot-v2.0",
    ],
    "named-entity-recognition": [
        "dbmdz/bert-large-cased-finetuned-conll03-english",
        "Jean-Baptiste/roberta-large-ner-english",
        "dslim/bert-base-NER",
    ],
    "question-answering": [
        "deepset/roberta-base-squad2",
        "distilbert-base-cased-distilled-squad",
        "deepset/deberta-v3-base-squad2",
    ],
    "automatic-speech-recognition": [
        "openai/whisper-large-v3",
        "openai/whisper-medium",
        "openai/whisper-small",
    ],
    "text-to-speech": [
        "suno/bark-small",
        "facebook/mms-tts-eng",
        "espnet/kan-bayashi_ljspeech_vits",
    ],
    "image-generation": [
        "black-forest-labs/FLUX.1-schnell",
        "stabilityai/stable-diffusion-xl-base-1.0",
        "runwayml/stable-diffusion-v1-5",
    ],
    "image-to-text": [
        "Salesforce/blip-image-captioning-large",
        "nlpconnect/vit-gpt2-image-captioning",
        "microsoft/git-base",
    ],
    "object-detection": [
        "facebook/detr-resnet-50",
        "hustvl/yolos-tiny",
        "microsoft/table-transformer-detection",
    ],
    "image-classification": [
        "google/vit-base-patch16-224",
        "microsoft/resnet-50",
        "nateraw/food",
    ],
    "feature-extraction": [
        "sentence-transformers/all-MiniLM-L6-v2",
        "sentence-transformers/all-mpnet-base-v2",
        "BAAI/bge-small-en-v1.5",
    ],
    "fill-mask": [
        "bert-base-uncased",
        "roberta-base",
        "distilbert-base-uncased",
    ],
    "table-question-answering": [
        "google/tapas-large-finetuned-wtq",
        "microsoft/tapex-large",
    ],
    "document-question-answering": [
        "impira/layoutlm-document-qa",
        "naver-clova-ix/donut-base-finetuned-docvqa",
    ],
    "depth-estimation": [
        "LiheYoung/depth-anything-small-hf",
        "Intel/dpt-large",
    ],
    "audio-classification": [
        "facebook/wav2vec2-base",
        "superb/hubert-base-superb-ks",
    ],
    "visual-question-answering": [
        "dandelin/vilt-b32-finetuned-vqa",
        "Salesforce/blip-vqa-base",
    ],
    "language-detection": [
        "papluca/xlm-roberta-base-language-detection",
        "qanastek/51-languages-classifier",
    ],
    "translation_auto": [
        "Helsinki-NLP/opus-mt-mul-en",
        "facebook/nllb-200-distilled-600M",
    ],
}


class HFDiscovery:
    """
    Motor de descubrimiento y uso de herramientas HuggingFace.
    ARIA llama a este módulo cuando necesita una capacidad que no tiene.
    """

    def __init__(self) -> None:
        self._token = settings.hf_key
        self._http = httpx.AsyncClient(timeout=120.0)
        self._model_cache: dict[str, str] = {}  # task -> mejor modelo probado
        self._failure_cache: dict[str, set] = {}  # task -> modelos fallidos

    def _available(self) -> bool:
        if not self._token:
            logger.warning("[HFDiscovery] HF_TOKEN no configurado")
            return False
        return True

    def _headers(self, is_binary: bool = False) -> dict:
        h: dict[str, str] = {"Authorization": f"Bearer {self._token}"}
        if not is_binary:
            h["Content-Type"] = "application/json"
        h["X-Wait-For-Model"] = "true"
        return h

    # ══════════════════════════════════════════════════════════════
    # PUNTO DE ENTRADA PRINCIPAL
    # ══════════════════════════════════════════════════════════════

    async def discover_and_run(
        self,
        task: str,
        payload: Any,
        binary_output: bool = False,
        binary_input: bool = False,
        force_rediscover: bool = False,
    ) -> dict[str, Any]:
        """
        Punto de entrada universal. ARIA llama esto cuando necesita
        cualquier capacidad de ML.

        Args:
            task: Tipo de tarea HF (ej: "summarization", "translation")
            payload: Datos de entrada para el modelo
            binary_output: True si el resultado es binario (imagen, audio)
            binary_input: True si el input es binario (imagen, audio)
            force_rediscover: Ignora caché y busca modelo nuevamente

        Returns:
            dict con success, result, model_used, task
        """
        if not self._available():
            return {
                "success": False,
                "error": "HF_TOKEN no configurado. Obtén uno gratis en huggingface.co",
                "task": task,
            }

        # 1. Usar modelo cacheado si hay uno
        if not force_rediscover and task in self._model_cache:
            model = self._model_cache[task]
            result = await self._run_model(model, payload, binary_output, binary_input)
            if result["success"]:
                return result

        # 2. Intentar modelos preferidos en orden
        preferred = PREFERRED_MODELS.get(task, [])
        failed = self._failure_cache.get(task, set())

        for model in preferred:
            if model in failed:
                continue
            logger.info("[HFDiscovery] Probando modelo preferido: %s para '%s'", model, task)
            result = await self._run_model(model, payload, binary_output, binary_input)
            if result["success"]:
                self._model_cache[task] = model
                return result
            failed.add(model)
            self._failure_cache[task] = failed
            await asyncio.sleep(1)

        # 3. Buscar en HF Hub si todos los preferidos fallaron
        logger.info("[HFDiscovery] Buscando modelos alternativos en HF Hub para '%s'", task)
        hub_models = await self._search_hub(task, exclude=failed)

        for model in hub_models[:5]:
            if model in failed:
                continue
            logger.info("[HFDiscovery] Probando modelo del Hub: %s", model)
            result = await self._run_model(model, payload, binary_output, binary_input)
            if result["success"]:
                self._model_cache[task] = model
                return result
            failed.add(model)
            self._failure_cache[task] = failed
            await asyncio.sleep(2)

        return {
            "success": False,
            "error": f"Ningún modelo disponible funcionó para '{task}'. Todos fallaron: {list(failed)[:5]}",
            "task": task,
            "models_tried": list(failed),
        }

    # ══════════════════════════════════════════════════════════════
    # BÚSQUEDA EN HF HUB
    # ══════════════════════════════════════════════════════════════

    async def _search_hub(self, task: str, exclude: set = None, limit: int = 10) -> list[str]:
        """
        Busca los modelos más descargados en HF Hub para una tarea.
        Retorna lista de IDs de modelo ordenados por popularidad.
        """
        try:
            params = {
                "pipeline_tag": task,
                "sort": "downloads",
                "direction": "-1",
                "limit": limit,
                "full": "false",
            }
            res = await self._http.get(f"{HF_HUB}/models", params=params, timeout=15.0)
            if res.status_code == 200:
                models = res.json()
                ids = [m["modelId"] for m in models if isinstance(m, dict)]
                if exclude:
                    ids = [m for m in ids if m not in exclude]
                logger.info("[HFDiscovery] Hub encontró %d modelos para '%s'", len(ids), task)
                return ids
            logger.warning("[HFDiscovery] HF Hub HTTP %d para tarea '%s'", res.status_code, task)
        except Exception as exc:
            logger.error("[HFDiscovery] Error buscando en Hub: %s", exc)
        return []

    async def search_models_for_task(
        self,
        task: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        API pública: busca modelos en HF Hub para una tarea dada.
        ARIA usa esto para explorar qué herramientas existen.
        """
        try:
            res = await self._http.get(
                f"{HF_HUB}/models",
                params={
                    "pipeline_tag": task,
                    "sort": "downloads",
                    "direction": "-1",
                    "limit": limit,
                    "full": "false",
                },
                timeout=15.0,
            )
            if res.status_code == 200:
                models = res.json()
                return {
                    "success": True,
                    "task": task,
                    "models": [
                        {
                            "id": m.get("modelId", ""),
                            "downloads": m.get("downloads", 0),
                            "likes": m.get("likes", 0),
                            "tags": m.get("tags", [])[:5],
                        }
                        for m in models
                        if isinstance(m, dict)
                    ],
                    "count": len(models),
                }
            return {"success": False, "error": f"HF Hub HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def search_models_by_keyword(self, keyword: str, limit: int = 10) -> dict[str, Any]:
        """Busca modelos por keyword en HF Hub."""
        try:
            res = await self._http.get(
                f"{HF_HUB}/models",
                params={"search": keyword, "sort": "downloads", "direction": "-1", "limit": limit},
                timeout=15.0,
            )
            if res.status_code == 200:
                models = res.json()
                return {
                    "success": True,
                    "keyword": keyword,
                    "models": [
                        {
                            "id": m.get("modelId", ""),
                            "pipeline_tag": m.get("pipeline_tag", ""),
                            "downloads": m.get("downloads", 0),
                            "likes": m.get("likes", 0),
                        }
                        for m in models
                        if isinstance(m, dict)
                    ],
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # EJECUCIÓN DE MODELOS
    # ══════════════════════════════════════════════════════════════

    async def _run_model(
        self,
        model: str,
        payload: Any,
        binary_output: bool = False,
        binary_input: bool = False,
    ) -> dict[str, Any]:
        """Ejecuta un modelo específico via HF Inference API."""
        url = f"{HF_API}/{model}"
        headers = self._headers(is_binary=binary_input)

        try:
            if binary_input:
                if isinstance(payload, bytes):
                    raw_payload = payload
                elif isinstance(payload, str) and payload.startswith("data:"):
                    raw_payload = base64.b64decode(payload.split(",")[1])
                else:
                    raw_payload = payload
                res = await self._http.post(url, headers=headers, content=raw_payload, timeout=120.0)
            else:
                res = await self._http.post(url, headers=headers, json=payload, timeout=120.0)

            if res.status_code == 200:
                output = res.content if binary_output else res.json()
                return {
                    "success": True,
                    "model_used": model,
                    "result": output,
                    "binary": binary_output,
                }

            if res.status_code == 503:
                # Modelo cargando — esperar y reintentar una vez
                try:
                    est = res.json().get("estimated_time", 20)
                except Exception:
                    est = 20
                logger.info("[HFDiscovery] %s cargando, esperando %ss...", model, min(est, 25))
                await asyncio.sleep(min(est, 25))
                res2 = await self._http.post(url, headers=headers,
                    content=raw_payload if binary_input else None,
                    json=None if binary_input else payload,
                    timeout=120.0)
                if res2.status_code == 200:
                    out = res2.content if binary_output else res2.json()
                    return {"success": True, "model_used": model, "result": out, "binary": binary_output}

            logger.warning("[HFDiscovery] %s HTTP %d: %s", model, res.status_code, res.text[:150])
            return {"success": False, "model_used": model, "error": f"HTTP {res.status_code}"}

        except Exception as exc:
            logger.error("[HFDiscovery] Error con %s: %s", model, exc)
            return {"success": False, "model_used": model, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # MÉTODOS DE ALTO NIVEL (ARIA los usa directamente)
    # ══════════════════════════════════════════════════════════════

    async def summarize(self, text: str, max_length: int = 200) -> dict[str, Any]:
        """Resume texto largo. Ideal para artículos, informes."""
        result = await self.discover_and_run(
            "summarization",
            {"inputs": text[:2000], "parameters": {"max_length": max_length, "min_length": 40}},
        )
        if result["success"] and isinstance(result["result"], list):
            result["summary"] = result["result"][0].get("summary_text", "")
        return result

    async def translate(self, text: str, source_lang: str = "en", target_lang: str = "es") -> dict[str, Any]:
        """Traduce texto. Soporta 100+ pares de idiomas via Helsinki-NLP."""
        model_key = f"Helsinki-NLP/opus-mt-{source_lang}-{target_lang}"
        result = await self._run_model(model_key, {"inputs": text})
        if not result["success"]:
            # Fallback: buscar modelo de traducción alternativo
            result = await self.discover_and_run(
                "translation",
                {"inputs": text},
            )
        if result["success"] and isinstance(result["result"], list):
            result["translation"] = result["result"][0].get("translation_text", "")
        return result

    async def analyze_sentiment(self, text: str) -> dict[str, Any]:
        """Analiza el sentimiento de un texto. Útil para monitorear menciones."""
        result = await self.discover_and_run(
            "sentiment-analysis",
            {"inputs": text[:512]},
        )
        if result["success"] and isinstance(result["result"], list):
            r = result["result"][0] if isinstance(result["result"][0], dict) else result["result"][0][0]
            result["label"] = r.get("label", "")
            result["score"] = round(r.get("score", 0), 3)
        return result

    async def classify_text(self, text: str, labels: list[str]) -> dict[str, Any]:
        """
        Clasifica texto en categorías personalizadas sin entrenamiento previo.
        Útil para categorizar contenido, leads, oportunidades.
        """
        result = await self.discover_and_run(
            "zero-shot-classification",
            {"inputs": text[:512], "parameters": {"candidate_labels": labels}},
        )
        if result["success"] and isinstance(result["result"], dict):
            scores = result["result"].get("scores", [])
            labels_out = result["result"].get("labels", [])
            result["rankings"] = [
                {"label": l, "score": round(s, 3)}
                for l, s in zip(labels_out, scores)
            ]
            if result["rankings"]:
                result["best_label"] = result["rankings"][0]["label"]
                result["confidence"] = result["rankings"][0]["score"]
        return result

    async def extract_entities(self, text: str) -> dict[str, Any]:
        """
        Extrae personas, organizaciones, lugares de un texto.
        Útil para análisis de mercado, leads, competidores.
        """
        result = await self.discover_and_run(
            "named-entity-recognition",
            {"inputs": text[:512]},
        )
        if result["success"] and isinstance(result["result"], list):
            entities: dict[str, list[str]] = {}
            for ent in result["result"]:
                if isinstance(ent, dict):
                    ent_type = ent.get("entity_group", ent.get("entity", "OTHER"))
                    word = ent.get("word", "").replace("##", "")
                    if word:
                        entities.setdefault(ent_type, [])
                        if word not in entities[ent_type]:
                            entities[ent_type].append(word)
            result["entities"] = entities
        return result

    async def transcribe_audio(self, audio_bytes: bytes) -> dict[str, Any]:
        """Transcribe audio a texto usando Whisper."""
        result = await self.discover_and_run(
            "automatic-speech-recognition",
            audio_bytes,
            binary_input=True,
        )
        if result["success"] and isinstance(result["result"], dict):
            result["transcription"] = result["result"].get("text", "")
        return result

    async def generate_image(self, prompt: str) -> dict[str, Any]:
        """Genera imagen a partir de texto usando FLUX o SDXL."""
        result = await self.discover_and_run(
            "image-generation",
            {"inputs": prompt},
            binary_output=True,
        )
        if result["success"] and isinstance(result["result"], bytes):
            result["image_base64"] = base64.b64encode(result["result"]).decode("utf-8")
            result["image_bytes"] = result["result"]
        return result

    async def describe_image(self, image_bytes: bytes) -> dict[str, Any]:
        """Genera descripción textual de una imagen (BLIP-2)."""
        result = await self.discover_and_run(
            "image-to-text",
            image_bytes,
            binary_input=True,
        )
        if result["success"] and isinstance(result["result"], list):
            result["caption"] = result["result"][0].get("generated_text", "")
        return result

    async def detect_language(self, text: str) -> dict[str, Any]:
        """Detecta el idioma de un texto."""
        result = await self.discover_and_run(
            "language-detection",
            {"inputs": text[:200]},
        )
        if result["success"] and isinstance(result["result"], list):
            if result["result"]:
                top = result["result"][0] if isinstance(result["result"][0], dict) else result["result"][0][0]
                result["language"] = top.get("label", "")
                result["confidence"] = round(top.get("score", 0), 3)
        return result

    async def get_embeddings(self, texts: list[str]) -> dict[str, Any]:
        """
        Genera embeddings de texto para búsqueda semántica, similitud.
        Útil para comparar contenido, detectar duplicados, recomendar.
        """
        result = await self.discover_and_run(
            "feature-extraction",
            {"inputs": texts},
        )
        return result

    async def answer_question(self, question: str, context: str) -> dict[str, Any]:
        """Responde una pregunta dado un contexto de texto."""
        result = await self.discover_and_run(
            "question-answering",
            {"inputs": {"question": question[:200], "context": context[:1000]}},
        )
        if result["success"] and isinstance(result["result"], dict):
            result["answer"] = result["result"].get("answer", "")
            result["score"] = round(result["result"].get("score", 0), 3)
        return result

    async def generate_speech(self, text: str) -> dict[str, Any]:
        """Convierte texto a voz (Bark/MMS)."""
        result = await self.discover_and_run(
            "text-to-speech",
            {"inputs": text[:500]},
            binary_output=True,
        )
        if result["success"] and isinstance(result["result"], bytes):
            result["audio_base64"] = base64.b64encode(result["result"]).decode("utf-8")
        return result

    async def detect_objects(self, image_bytes: bytes) -> dict[str, Any]:
        """Detecta objetos en una imagen (DETR, YOLO)."""
        result = await self.discover_and_run(
            "object-detection",
            image_bytes,
            binary_input=True,
        )
        if result["success"] and isinstance(result["result"], list):
            result["objects"] = [
                {
                    "label": obj.get("label", ""),
                    "score": round(obj.get("score", 0), 3),
                    "box": obj.get("box", {}),
                }
                for obj in result["result"]
            ]
        return result

    # ══════════════════════════════════════════════════════════════
    # DISCOVERY INTELIGENTE — ARIA busca herramientas nuevas
    # ══════════════════════════════════════════════════════════════

    async def find_tool_for_capability(self, capability_description: str) -> dict[str, Any]:
        """
        ARIA describe qué necesita hacer en lenguaje natural.
        Este método encuentra el modelo más apropiado en HF Hub.

        Ejemplo:
            "quiero detectar spam en emails"
            "necesito traducir chino a inglés"
            "quiero analizar si una imagen tiene texto"
        """
        # Mapeo de keywords a tareas HF
        keyword_task_map = [
            (["traduc", "translat"], "translation"),
            (["resume", "summar", "resumen"], "summarization"),
            (["sentimient", "sentiment", "opinion", "emoci"], "sentiment-analysis"),
            (["clasif", "categor", "classify", "detectar si"], "zero-shot-classification"),
            (["entidad", "entity", "persona", "empresa", "lugar"], "named-entity-recognition"),
            (["transcrib", "audio", "voz a texto", "speech"], "automatic-speech-recognition"),
            (["imagen", "image", "foto", "generar visual"], "image-generation"),
            (["describir imagen", "caption", "que hay en"], "image-to-text"),
            (["pregunta", "question", "responde sobre"], "question-answering"),
            (["objeto", "detectar en imagen", "object detect"], "object-detection"),
            (["idioma", "language", "qué idioma"], "language-detection"),
            (["embedding", "similitud", "semantic"], "feature-extraction"),
            (["código", "code", "programar", "script"], "text-generation"),
            (["texto a voz", "text to speech", "hablar", "voz"], "text-to-speech"),
            (["finanza", "financ", "banc", "dinero", "stock", "mercado"], "text-classification"),
            (["legal", "jurid", "contrato", "ley", "norma"], "text-classification"),
            (["logistica", "logistic", "transporte", "ruta", "entrega"], "text-classification"),
            (["manufactura", "industria", "fabrica", "maquina"], "image-classification"),
            (["agricultura", "cultivo", "campo", "suelo", "planta"], "image-classification"),
            (["bioquimica", "proteina", "biologia", "medicina", "molecula"], "text-classification"),
        ]

        cap_lower = capability_description.lower()
        matched_task = None
        for keywords, task in keyword_task_map:
            if any(k in cap_lower for k in keywords):
                matched_task = task
                break

        if not matched_task:
            # Búsqueda genérica en Hub por keyword
            search_result = await self.search_models_by_keyword(capability_description, limit=5)
            return {
                "success": search_result.get("success", False),
                "capability": capability_description,
                "recommended_task": "unknown",
                "models_found": search_result.get("models", []),
                "note": "No encontré tarea exacta. Busqué por keyword en HF Hub.",
            }

        models_result = await self.search_models_for_task(matched_task, limit=5)
        return {
            "success": True,
            "capability": capability_description,
            "recommended_task": matched_task,
            "recommended_models": PREFERRED_MODELS.get(matched_task, [])[:3],
            "hub_models": models_result.get("models", [])[:3],
            "how_to_use": f"await hf.discover_and_run('{matched_task}', {{...}})",
        }

    async def capability_report(self) -> dict[str, Any]:
        """
        Reporta qué puede hacer ARIA con HuggingFace ahora mismo.
        ARIA usa esto para saber qué herramientas tiene disponibles.
        """
        if not self._available():
            return {
                "available": False,
                "error": "HF_TOKEN no configurado",
                "how_to_fix": "Obtén token gratis en huggingface.co → Settings → Access Tokens",
            }

        all_tasks = list(PREFERRED_MODELS.keys())
        cached = list(self._model_cache.keys())

        return {
            "available": True,
            "token_configured": True,
            "supported_tasks": all_tasks,
            "tasks_count": len(all_tasks),
            "cached_models": {k: v for k, v in self._model_cache.items()},
            "cached_count": len(cached),
            "categories": {
                "texto": ["summarization", "translation", "sentiment-analysis",
                          "zero-shot-classification", "named-entity-recognition",
                          "question-answering", "fill-mask", "language-detection"],
                "imagen": ["image-generation", "image-to-text", "object-detection",
                           "image-classification", "depth-estimation", "visual-question-answering"],
                "audio": ["automatic-speech-recognition", "text-to-speech", "audio-classification"],
                "embeddings": ["feature-extraction"],
                "codigo": ["text-generation"],
                "sectores_economia_circular": ["finanzas", "legal", "logística", "manufactura", "agricultura", "bioquímica"],
            },
        }


# ── SINGLETON ─────────────────────────────────────────────────────

_instance: Optional[HFDiscovery] = None


def get_hf() -> HFDiscovery:
    global _instance
    if _instance is None:
        _instance = HFDiscovery()
    return _instance
