# ARIA AI - Plan de Integración Open Source (Fase 2: Organización Autónoma)

Este plan detalla la integración de la segunda oleada de herramientas para transformar a ARIA de un sistema de agentes a una organización autónoma de alto rendimiento.

## 1. Capa de Evaluación (Self-Judging)
- **OpenEvals / Inspect AI / DeepEval**:
    - **Ubicación**: `apps/core/intelligence/evaluation_engine.py`
    - **Propósito**: Permitir que Aria evalúe sus propias respuestas, estrategias y uso de herramientas antes de ejecutarlas.
    - **Métricas**: Calidad de razonamiento, precisión de herramientas y coherencia de memoria.

## 2. Capa de Conocimiento y Razonamiento Relacional
- **Neo4j**:
    - **Ubicación**: `apps/core/memory/graph_db_client.py`
    - **Propósito**: Gestionar relaciones complejas (Cliente → Campaña → Producto → Ingreso).
    - **Diferencia con Graphiti**: Graphiti es para eventos temporales; Neo4j es para la estructura organizacional y relacional de largo plazo.
- **LlamaIndex**:
    - **Ubicación**: `apps/core/memory/document_engine.py`
    - **Propósito**: RAG avanzado y agentes documentales para investigación profunda.

## 3. Capa de Operación Web (Navegación Real)
- **Browser Use / Playwright**:
    - **Ubicación**: `apps/core/tools/browser_operator.py`
    - **Propósito**: Permitir que Aria opere sitios web reales como un humano, no solo scrapear.
    - **Integración**: Reemplazará o potenciará `web_tools.py` y `browser_sandbox.py`.

## 4. Capa de Workflows tipo CEO (Procesos Largos)
- **Temporal / Prefect / Kestra**:
    - **Ubicación**: `apps/core/orchestration/workflow_manager.py`
    - **Propósito**: Gestionar procesos que duran días o semanas (ej: una campaña de 30 días) con persistencia y reintentos automáticos.

## 5. Capa Económica y Analítica
- **DuckDB**:
    - **Ubicación**: `apps/core/tools/analytics_engine.py`
    - **Propósito**: Análisis de datos ultra-rápido para reporting y métricas económicas.
- **RudderStack**:
    - **Ubicación**: `apps/core/tools/event_router.py`
    - **Propósito**: Enrutamiento de eventos de tracking a múltiples destinos.

## 6. Capa de Auto-Mejora (Self-Evolution)
- **Self-Refine / Reflexion**:
    - **Ubicación**: `apps/core/intelligence/self_improvement.py`
    - **Propósito**: Implementar ciclos de Crítica -> Mejora -> Ejecución dentro de los agentes.

## 7. Capa Multimedia
- **Whisper / ComfyUI**:
    - **Ubicación**: `apps/core/tools/multimedia_engine.py`
    - **Propósito**: Transcripción de audio y generación/edición avanzada de imágenes.

## 8. Infraestructura Unificada
- **Docker Compose**: Actualización para incluir Neo4j, Temporal, DuckDB y servicios multimedia.
- **Requirements**: Actualización con todas las nuevas dependencias.
