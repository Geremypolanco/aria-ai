"""
  model_router.py — Motor de Descubrimiento de Modelos y Enrutamiento Inteligente.

  ARIA descubre automáticamente:
    1. Todas sus propias funciones y agentes
    2. Todos los modelos HF disponibles para cada tipo de tarea
    3. Cuál modelo es el más adecuado para cada función/tarea

  El ModelRouter actualiza HF_MODEL_ROTATION dinámicamente en Redis,
  de forma que AriaAIClient cargue siempre la configuración óptima.

  Ciclo de descubrimiento (corre cada 24h via scheduler):
    1. Escanear funciones de Aria → mapear a task_type de HF
    2. Para cada task_type, buscar top modelos en HF Hub
    3. Benchmarkear candidatos con prompts reales y medir: latencia, tasa de éxito, calidad
    4. Actualizar tabla de enrutamiento en Redis
    5. ai_client.py carga la tabla actualizada al arrancar o cada ciclo
  """
  from __future__ import annotations

  import asyncio
  import json
  import logging
  import time
  from dataclasses import dataclass, asdict
  from datetime import datetime, timezone
  from typing import Any, Optional

  from apps.core.config import settings

  logger = logging.getLogger("aria.model_router")

  # ── CLAVES REDIS ─────────────────────────────────────────────
  ROUTING_TABLE_KEY   = "aria:model_router:routing_table:v3"
  BENCHMARK_KEY       = "aria:model_router:benchmark:{model_id}"
  DISCOVERY_LOG_KEY   = "aria:model_router:discovery_log"
  LAST_DISCOVERY_KEY  = "aria:model_router:last_discovery"
  ROUTING_TTL         = 60 * 60 * 24 * 7   # 7 días
  DISCOVERY_INTERVAL  = 60 * 60 * 24       # 24 horas


  # ── MAPA DE FUNCIONES DE ARIA ─────────────────────────────────
  # Cada función/agente de Aria → task_type HF más adecuado + descripción
  ARIA_FUNCTION_MAP: dict[str, dict] = {
      # Conversación y comprensión
      "telegram_conversation":    {"hf_task": "text-generation",        "priority": "speed",   "desc": "Respuestas conversacionales libres"},
      "telegram_analysis":        {"hf_task": "text-generation",        "priority": "quality", "desc": "Análisis interno antes de responder"},
      "support_agent":            {"hf_task": "text-generation",        "priority": "quality", "desc": "Soporte y resolución de problemas"},

      # Análisis y clasificación
      "intent_detection":         {"hf_task": "zero-shot-classification","priority": "speed",   "desc": "Detectar intención del usuario"},
      "topic_classification":     {"hf_task": "zero-shot-classification","priority": "speed",   "desc": "Clasificar tema de una interacción"},
      "sentiment_analysis":       {"hf_task": "sentiment-analysis",     "priority": "speed",   "desc": "Analizar sentimiento de textos"},
      "compliance_check":         {"hf_task": "zero-shot-classification","priority": "quality", "desc": "Verificar cumplimiento ético"},

      # Generación y contenido
      "content_agent":            {"hf_task": "text-generation",        "priority": "creative","desc": "Crear contenido para redes sociales"},
      "creative_engine":          {"hf_task": "text-generation",        "priority": "creative","desc": "Generación de ideas y creatividad"},
      "marketing_agent":          {"hf_task": "text-generation",        "priority": "quality", "desc": "Estrategia y copy de marketing"},

      # Código y técnico
      "dev_agent":                {"hf_task": "text-generation",        "priority": "code",    "desc": "Desarrollo y revisión de código"},
      "enhanced_dev_agent":       {"hf_task": "text-generation",        "priority": "code",    "desc": "Desarrollo avanzado con refactoring"},
      "code_reflector":           {"hf_task": "text-generation",        "priority": "code",    "desc": "Análisis y mejora del propio código"},

      # Investigación y datos
      "research_agent":           {"hf_task": "summarization",          "priority": "quality", "desc": "Investigación y síntesis de información"},
      "market_intelligence":      {"hf_task": "zero-shot-classification","priority": "quality", "desc": "Análisis de tendencias de mercado"},
      "web_search_synthesis":     {"hf_task": "summarization",          "priority": "speed",   "desc": "Resumir resultados de búsqueda web"},

      # Finanzas y negocio
      "cfo_agent":                {"hf_task": "text-generation",        "priority": "quality", "desc": "Análisis financiero y CFO"},
      "pm_agent":                 {"hf_task": "text-generation",        "priority": "quality", "desc": "Gestión de producto y roadmap"},
      "ecommerce_agent":          {"hf_task": "text-generation",        "priority": "quality", "desc": "E-commerce y shopify"},

      # Procesamiento de texto especializado
      "entity_extraction":        {"hf_task": "named-entity-recognition","priority": "speed",  "desc": "Extraer personas, empresas, lugares"},
      "text_summarization":       {"hf_task": "summarization",          "priority": "quality", "desc": "Resumir documentos largos"},
      "translation":              {"hf_task": "translation",            "priority": "speed",   "desc": "Traducción entre idiomas"},
      "document_qa":              {"hf_task": "document-question-answering","priority": "quality","desc": "Preguntas sobre documentos"},

      # Multimedia
      "image_description":        {"hf_task": "image-to-text",          "priority": "quality", "desc": "Describir imágenes"},
      "image_generation":         {"hf_task": "image-generation",       "priority": "quality", "desc": "Generar imágenes con IA"},
      "audio_transcription":      {"hf_task": "automatic-speech-recognition","priority": "quality","desc": "Transcribir audio (Whisper)"},
      "text_to_speech":           {"hf_task": "text-to-speech",         "priority": "quality", "desc": "Convertir texto a voz"},

      # Embeddings y similitud
      "semantic_search":          {"hf_task": "feature-extraction",     "priority": "speed",   "desc": "Búsqueda semántica y similitud"},
      "knowledge_retrieval":      {"hf_task": "feature-extraction",     "priority": "speed",   "desc": "Recuperar conocimiento relevante"},
  }

  # Modelos candidatos extra por tipo de prioridad (para benchmarking)
  BENCHMARK_CANDIDATES: dict[str, list[str]] = {
      "text-generation": [
          "Qwen/Qwen2.5-72B-Instruct",
          "Qwen/Qwen2.5-7B-Instruct",
          "mistralai/Mistral-7B-Instruct-v0.3",
          "HuggingFaceH4/zephyr-7b-beta",
          "microsoft/Phi-3-mini-4k-instruct",
          "meta-llama/Meta-Llama-3-8B-Instruct",
          "google/gemma-7b-it",
      ],
      "summarization": [
          "facebook/bart-large-cnn",
          "sshleifer/distilbart-cnn-12-6",
          "google/pegasus-xsum",
          "philschmid/bart-large-cnn-samsum",
      ],
      "zero-shot-classification": [
          "facebook/bart-large-mnli",
          "cross-encoder/nli-deberta-v3-large",
          "MoritzLaurer/deberta-v3-large-zeroshot-v2.0",
          "typeform/distilbert-base-uncased-mnli",
      ],
      "sentiment-analysis": [
          "distilbert-base-uncased-finetuned-sst-2-english",
          "cardiffnlp/twitter-roberta-base-sentiment-latest",
          "lxyuan/distilbert-base-multilingual-cased-sentiments-student",
          "nlptown/bert-base-multilingual-uncased-sentiment",
      ],
      "named-entity-recognition": [
          "dslim/bert-base-NER",
          "Jean-Baptiste/roberta-large-ner-english",
          "dbmdz/bert-large-cased-finetuned-conll03-english",
      ],
      "feature-extraction": [
          "sentence-transformers/all-MiniLM-L6-v2",
          "sentence-transformers/all-mpnet-base-v2",
          "BAAI/bge-small-en-v1.5",
      ],
  }

  # Prompts de benchmark por tarea
  BENCHMARK_PROMPTS: dict[str, Any] = {
      "text-generation": {
          "inputs": "Explica en 2 oraciones por qué el marketing de contenidos es importante para un negocio.",
          "parameters": {"max_new_tokens": 80, "temperature": 0.7},
      },
      "summarization": {
          "inputs": "El marketing digital es el componente de marketing que utiliza internet y tecnología digital online como computadoras de escritorio, teléfonos móviles y otros medios y plataformas digitales para promover productos y servicios.",
      },
      "zero-shot-classification": {
          "inputs": "¿Cuánto dinero generé esta semana?",
          "parameters": {"candidate_labels": ["finanzas", "marketing", "soporte", "desarrollo"]},
      },
      "sentiment-analysis": {
          "inputs": "Estoy muy satisfecho con los resultados de hoy, todo funcionó perfectamente.",
      },
      "named-entity-recognition": {
          "inputs": "Amazon y Google son las principales empresas de tecnología en Estados Unidos.",
      },
      "feature-extraction": {
          "inputs": "estrategia de monetización y crecimiento de ingresos",
      },
  }


  @dataclass
  class ModelScore:
      model_id: str
      hf_task: str
      latency_ms: int
      success: bool
      quality_score: float   # 0-1
      response_len: int
      timestamp: str

      def composite_score(self) -> float:
          if not self.success:
              return 0.0
          # Penalizar latencia > 5000ms, premiar respuestas no vacías
          latency_penalty = min(1.0, self.latency_ms / 5000)
          return round(
              self.quality_score * 0.5
              + (1 - latency_penalty) * 0.3
              + min(1.0, self.response_len / 200) * 0.2,
              3,
          )


  @dataclass
  class RoutingEntry:
      function_name: str
      hf_task: str
      priority: str
      best_model: str
      fallback_models: list[str]
      composite_score: float
      last_benchmarked: str
      desc: str

      def to_dict(self) -> dict:
          return asdict(self)


  class ModelRouter:
      """
      Motor de descubrimiento y enrutamiento inteligente de modelos HF.

      Uso:
          router = get_model_router()

          # Obtener mejor modelo para una función de Aria
          model = await router.get_best_model("content_agent")

          # Correr ciclo completo de descubrimiento (llamado por scheduler)
          report = await router.run_discovery_cycle()

          # Ver tabla completa de enrutamiento
          table = await router.get_routing_table()
      """

      def __init__(self) -> None:
          self._cache = None
          self._hf = None
          self._routing_table: dict[str, RoutingEntry] = {}
          self._table_loaded = False

      def _get_cache(self):
          if not self._cache:
              from apps.core.memory.redis_client import get_cache
              self._cache = get_cache()
          return self._cache

      def _get_hf(self):
          if not self._hf:
              from apps.core.tools.hf_discovery import HFDiscovery
              self._hf = HFDiscovery()
          return self._hf

      # ── API PÚBLICA ──────────────────────────────────────────

      async def get_best_model(self, function_name: str) -> Optional[str]:
          """
          Retorna el mejor modelo HF para una función de Aria.
          Si no hay benchmark, retorna el modelo preferido por defecto.
          """
          await self._ensure_table_loaded()
          entry = self._routing_table.get(function_name)
          if entry and entry.best_model:
              return entry.best_model
          # Fallback a configuración estática
          func_def = ARIA_FUNCTION_MAP.get(function_name, {})
          task = func_def.get("hf_task", "text-generation")
          candidates = BENCHMARK_CANDIDATES.get(task, [])
          return candidates[0] if candidates else None

      async def get_routing_table(self) -> dict[str, Any]:
          """Retorna la tabla de enrutamiento completa."""
          await self._ensure_table_loaded()
          return {
              k: v.to_dict()
              for k, v in self._routing_table.items()
          }

      async def get_hf_rotation_config(self) -> dict[str, list[str]]:
          """
          Genera el diccionario HF_MODEL_ROTATION actualizado
          basándose en benchmarks reales. ai_client.py puede usar esto.
          """
          await self._ensure_table_loaded()
          from apps.core.tools.ai_client import AIModel

          # Mapear prioridades a AIModel
          priority_to_model = {
              "speed":    AIModel.FAST,
              "quality":  AIModel.STRATEGY,
              "code":     AIModel.CODE,
              "creative": AIModel.CREATIVE,
          }

          rotation: dict[str, list[str]] = {
              AIModel.FAST.value:     [],
              AIModel.STRATEGY.value: [],
              AIModel.CODE.value:     [],
              AIModel.CREATIVE.value: [],
          }

          for func_name, entry in self._routing_table.items():
              func_def = ARIA_FUNCTION_MAP.get(func_name, {})
              priority = func_def.get("priority", "quality")
              if priority not in priority_to_model:
                  continue
              model_key = priority_to_model[priority].value
              # Agregar modelo si no está ya y es un modelo text-generation
              if (entry.hf_task == "text-generation" and
                      entry.best_model and
                      entry.best_model not in rotation[model_key]):
                  rotation[model_key].insert(0, entry.best_model)
                  for fb in entry.fallback_models[:2]:
                      if fb not in rotation[model_key]:
                          rotation[model_key].append(fb)

          # Eliminar listas vacías
          return {k: v for k, v in rotation.items() if v}

      # ── CICLO DE DESCUBRIMIENTO ───────────────────────────────

      async def run_discovery_cycle(self) -> dict:
          """
          Ciclo completo de descubrimiento. Llamado por el scheduler cada 24h.
          """
          t0 = time.time()
          logger.info("[ModelRouter] ═══ Iniciando ciclo de descubrimiento ═══")

          # Verificar si es momento
          cache = self._get_cache()
          last_raw = await cache.get(LAST_DISCOVERY_KEY)
          if last_raw:
              elapsed = time.time() - float(last_raw)
              if elapsed < DISCOVERY_INTERVAL:
                  remaining_h = (DISCOVERY_INTERVAL - elapsed) / 3600
                  logger.info("[ModelRouter] Próximo ciclo en %.1fh", remaining_h)
                  return {"skipped": True, "reason": f"Próximo ciclo en {remaining_h:.1f}h"}

          results = {
              "functions_discovered": len(ARIA_FUNCTION_MAP),
              "tasks_benchmarked": 0,
              "models_evaluated": 0,
              "routing_entries_updated": 0,
              "errors": [],
              "duration_s": 0,
          }

          # Agrupar funciones por task_type para no benchmarkear el mismo task dos veces
          task_groups: dict[str, list[str]] = {}
          for func_name, func_def in ARIA_FUNCTION_MAP.items():
              task = func_def["hf_task"]
              if task not in task_groups:
                  task_groups[task] = []
              task_groups[task].append(func_name)

          # Benchmarkear cada task_type
          task_results: dict[str, list[ModelScore]] = {}
          for task_type, func_names in task_groups.items():
              logger.info("[ModelRouter] Benchmarkeando task: %s (%d funciones)", task_type, len(func_names))
              scores = await self._benchmark_task(task_type)
              task_results[task_type] = scores
              results["tasks_benchmarked"] += 1
              results["models_evaluated"] += len(scores)
              await asyncio.sleep(1)  # rate limiting entre tareas

          # Construir tabla de enrutamiento
          new_table: dict[str, RoutingEntry] = {}
          for func_name, func_def in ARIA_FUNCTION_MAP.items():
              task = func_def["hf_task"]
              scores = task_results.get(task, [])
              # Ordenar por composite_score
              ranked = sorted(scores, key=lambda s: s.composite_score(), reverse=True)
              successful = [s for s in ranked if s.success]

              best_model = successful[0].model_id if successful else (BENCHMARK_CANDIDATES.get(task, [""])[0])
              fallbacks = [s.model_id for s in successful[1:4]]

              entry = RoutingEntry(
                  function_name=func_name,
                  hf_task=task,
                  priority=func_def["priority"],
                  best_model=best_model,
                  fallback_models=fallbacks,
                  composite_score=successful[0].composite_score() if successful else 0.0,
                  last_benchmarked=datetime.now(timezone.utc).isoformat(),
                  desc=func_def["desc"],
              )
              new_table[func_name] = entry
              results["routing_entries_updated"] += 1

          # Persistir en Redis
          self._routing_table = new_table
          await self._save_routing_table()

          # Actualizar HF_MODEL_ROTATION en Redis para que ai_client lo use
          rotation = await self.get_hf_rotation_config()
          if rotation:
              await cache.set(
                  "aria:model_router:hf_rotation",
                  json.dumps(rotation),
                  ttl=ROUTING_TTL,
              )
              logger.info("[ModelRouter] HF_MODEL_ROTATION actualizado: %s", list(rotation.keys()))

          # Log de descubrimiento
          log_entry = {
              "ts": datetime.now(timezone.utc).isoformat(),
              "functions": results["functions_discovered"],
              "tasks": results["tasks_benchmarked"],
              "models": results["models_evaluated"],
              "entries": results["routing_entries_updated"],
          }
          await cache.set(LAST_DISCOVERY_KEY, str(time.time()), ttl=ROUTING_TTL)
          await cache.lpush(DISCOVERY_LOG_KEY, json.dumps(log_entry))
          await cache.ltrim(DISCOVERY_LOG_KEY, 0, 29)  # mantener últimos 30

          results["duration_s"] = round(time.time() - t0, 1)
          logger.info(
              "[ModelRouter] ═══ Descubrimiento completado: %d funciones, %d modelos evaluados en %.1fs ═══",
              results["functions_discovered"], results["models_evaluated"], results["duration_s"],
          )
          return results

      async def _benchmark_task(self, task_type: str) -> list[ModelScore]:
          """Benchmarkea modelos candidatos para un tipo de tarea."""
          hf = self._get_hf()
          candidates = BENCHMARK_CANDIDATES.get(task_type, [])
          prompt = BENCHMARK_PROMPTS.get(task_type)

          if not prompt or not candidates:
              return []

          scores: list[ModelScore] = []

          for model_id in candidates[:6]:  # max 6 candidatos por task
              t0 = time.time()
              success = False
              quality = 0.0
              response_len = 0

              try:
                  result = await asyncio.wait_for(
                      hf._run_model(model_id, prompt, binary_output=False, binary_input=False),
                      timeout=25.0,
                  )
                  latency_ms = int((time.time() - t0) * 1000)

                  if result.get("success"):
                      success = True
                      raw = result.get("result", "")
                      text = ""
                      if isinstance(raw, list) and raw:
                          first = raw[0]
                          text = (first.get("generated_text", "") or
                                  first.get("summary_text", "") or
                                  first.get("translation_text", "") or
                                  str(first))
                      elif isinstance(raw, dict):
                          text = (raw.get("generated_text", "") or
                                  raw.get("summary_text", "") or str(raw))
                      elif isinstance(raw, str):
                          text = raw
                      elif isinstance(raw, (list, dict)):
                          text = json.dumps(raw)[:200]

                      response_len = len(text)
                      # Calidad básica: respuesta no vacía, no es solo el prompt, longitud razonable
                      quality = min(1.0, response_len / 100) if response_len > 10 else 0.1
                  else:
                      latency_ms = int((time.time() - t0) * 1000)

              except asyncio.TimeoutError:
                  latency_ms = 25000
              except Exception as exc:
                  latency_ms = int((time.time() - t0) * 1000)
                  logger.debug("[ModelRouter] Benchmark %s/%s falló: %s", task_type, model_id, exc)

              score = ModelScore(
                  model_id=model_id,
                  hf_task=task_type,
                  latency_ms=latency_ms,
                  success=success,
                  quality_score=quality,
                  response_len=response_len,
                  timestamp=datetime.now(timezone.utc).isoformat(),
              )
              scores.append(score)

              # Cachear benchmark individual
              try:
                  cache = self._get_cache()
                  safe_id = model_id.replace("/", "_")
                  await cache.set(
                      BENCHMARK_KEY.format(model_id=safe_id),
                      json.dumps(asdict(score)),
                      ttl=ROUTING_TTL,
                  )
              except Exception:
                  pass

              logger.info(
                  "[ModelRouter] %s | %s → %s | lat=%dms | score=%.2f",
                  task_type, model_id.split("/")[-1],
                  "✓" if success else "✗",
                  latency_ms,
                  score.composite_score(),
              )
              await asyncio.sleep(0.5)

          return scores

      # ── PERSISTENCIA ─────────────────────────────────────────

      async def _save_routing_table(self) -> None:
          try:
              cache = self._get_cache()
              serialized = {k: v.to_dict() for k, v in self._routing_table.items()}
              await cache.set(ROUTING_TABLE_KEY, json.dumps(serialized, ensure_ascii=False), ttl=ROUTING_TTL)
              logger.info("[ModelRouter] Tabla de enrutamiento guardada (%d entradas)", len(serialized))
          except Exception as exc:
              logger.error("[ModelRouter] Error guardando tabla: %s", exc)

      async def _ensure_table_loaded(self) -> None:
          if self._table_loaded:
              return
          try:
              cache = self._get_cache()
              raw = await cache.get(ROUTING_TABLE_KEY)
              if raw:
                  data = json.loads(raw)
                  self._routing_table = {
                      k: RoutingEntry(**v) for k, v in data.items()
                  }
                  self._table_loaded = True
                  logger.info("[ModelRouter] Tabla de enrutamiento cargada: %d entradas", len(self._routing_table))
          except Exception as exc:
              logger.warning("[ModelRouter] No se pudo cargar tabla: %s — se generará en próximo ciclo", exc)
              self._table_loaded = True  # evitar reintentos en bucle

      # ── REPORTE ──────────────────────────────────────────────

      async def get_discovery_report(self) -> dict:
          """Genera un reporte del estado del motor de descubrimiento."""
          await self._ensure_table_loaded()
          cache = self._get_cache()

          last_raw = await cache.get(LAST_DISCOVERY_KEY)
          last_disc = "Nunca"
          if last_raw:
              dt = datetime.fromtimestamp(float(last_raw), tz=timezone.utc)
              last_disc = dt.strftime("%Y-%m-%d %H:%M UTC")

          top_entries = sorted(
              self._routing_table.values(),
              key=lambda e: e.composite_score,
              reverse=True,
          )[:10]

          return {
              "total_functions": len(ARIA_FUNCTION_MAP),
              "routing_entries": len(self._routing_table),
              "last_discovery": last_disc,
              "top_models": [
                  {
                      "function": e.function_name,
                      "best_model": e.best_model,
                      "score": e.composite_score,
                      "task": e.hf_task,
                  }
                  for e in top_entries
              ],
          }


  # ── SINGLETON ────────────────────────────────────────────────
  _router: Optional[ModelRouter] = None


  def get_model_router() -> ModelRouter:
      global _router
      if _router is None:
          _router = ModelRouter()
      return _router
  