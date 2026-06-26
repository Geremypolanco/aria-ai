# Plan de Integración de Tecnologías Open Source en Aria AI

Este documento describe cómo se integrarán las 15 herramientas open source en la arquitectura actual de Aria AI.

## 1. Executive / Decision Layer
*   **PocketFlow**: Se integrará en `apps/core/orchestration/state_graph.py` para reemplazar o potenciar el `StateGraph` actual con un grafo de decisiones robusto y declarativo.
*   **PydanticAI**: Se usará para definir y validar los agentes en `src/agents/base_agent.py` y `apps/core/agents/base_agent.py`, proporcionando tipado fuerte y workflows auditables en el `ExecutionPipeline`.

## 2. Memory & Knowledge Layer
*   **Graphiti**: Se integrará en `apps/core/memory/evolutionary_memory.py` para construir grafos de conocimiento temporales de las interacciones y el estado del sistema.
*   **Zep**: Se usará como backend de memoria a largo plazo en `apps/core/memory/zep_client.py` complementando a Redis/Supabase.

## 3. Market Intelligence Layer
*   **Crawl4AI**: Se integrará en `apps/core/tools/web_tools.py` para scraping asíncrono y estructurado de sitios web.
*   **Firecrawl**: Se añadirá a `apps/core/tools/market_tools.py` para convertir webs a datos y mapear sitios de competidores.

## 4. Revenue & Growth Layer
*   **GrowthBook**: Se integrará para A/B testing en los flujos de marketing y ventas.
*   **PostHog**: Se usará para analítica de producto, funnels y eventos, integrándose en el `BusinessHub` y `MarketingAgent`.

## 5. Observability Layer
*   **OpenTelemetry**: Instrumentación de FastAPI y agentes en `apps/core/observability/trace_engine.py`.
*   **Prometheus & Grafana**: Métricas y visualización, exportadas desde el backend y configuradas vía `docker-compose`.

## 6. Autonomous Coding Layer
*   **Aider**: Se integrará en `apps/core/agents/dev_agent.py` y `evolution_agent.py` para modificación de código.
*   **SWE-agent**: Se usará para resolver tareas complejas de ingeniería y refactors autónomos.

## 7. Business Intelligence Layer
*   **Metabase & Apache Superset**: Despliegue de dashboards open source para el "Executive Dashboard" de Aria, conectados a Supabase y PostHog.

## Siguientes pasos
1. Añadir dependencias al `requirements.txt`.
2. Implementar cada capa iterativamente.
3. Actualizar `docker-compose.yml` para los servicios adicionales (PostHog, Metabase, Superset, Grafana, Prometheus).
