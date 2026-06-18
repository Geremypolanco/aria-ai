# Agent Personas

Specialist personas that play a single role with a single perspective. Each persona is a Markdown file consumed as a system prompt by your harness (Claude Code, Cursor, Copilot, etc.).

| Persona | Role | Best for |
|---------|------|----------|
| [code-reviewer](code-reviewer.md) | Senior Staff Engineer | Five-axis review before merge |
| [security-auditor](security-auditor.md) | Security Engineer | Vulnerability detection, OWASP-style audit |
| [test-engineer](test-engineer.md) | QA Engineer | Test strategy, coverage analysis, Prove-It pattern |
| [web-performance-auditor](web-performance-auditor.md) | Web Performance Engineer | Core Web Vitals audit, loading/rendering/network analysis |

## 🚀 Integraciones Open Source (Aria Executive Architecture)

Aria AI ha sido expandida con una arquitectura milimétrica de integraciones open source de nivel empresarial, dividida en 7 capas fundamentales:

### 1. Executive / Decision Layer
- **PocketFlow**: Motor de decisiones mediante flujos complejos y árboles de decisión.
- **PydanticAI**: Framework de agentes con tipado fuerte, validación y workflows auditables para agentes críticos.

### 2. Memory & Knowledge Layer
- **Graphiti**: Memoria basada en grafos temporales (vía FalkorDB) ideal para *Revenue Attribution* (ej. video → lead → email → venta).
- **Zep**: Memoria de largo plazo para agentes, complementando a Supabase para historial de interacciones y recuperación de contexto sub-200ms.

### 3. Market Intelligence Layer
- **Crawl4AI**: Scraping asíncrono y estructurado para análisis de competidores y extracción de contenido sin depender de navegación basada en prompts.
- **Firecrawl**: Conversión de webs completas a datos limpios, mapeo de sitios y auditorías SEO automáticas.

### 4. Revenue & Growth Layer
- **GrowthBook**: Motor de A/B testing profesional para experimentar y aprender qué estrategias generan más ingresos.
- **PostHog**: Sistema de analítica de producto (funnels, conversiones, cohortes, retención) obligatorio para un Revenue Engine.

### 5. Observability Layer
- **OpenTelemetry**: Rastreo distribuido (tracing) de absolutamente todas las operaciones y llamadas a LLMs.
- **Prometheus**: Recolección de métricas de negocio (revenue, ventas, leads) y sistema.
- **Grafana**: Visualización de métricas en tiempo real.

### 6. Autonomous Coding Layer
- **Aider**: Modificación autónoma de código, refactors y creación de PRs.
- **SWE-agent**: Resolución autónoma de tareas de ingeniería y GitHub issues.

### 7. Business Intelligence Layer
- **Metabase**: Dashboarding open source accesible para reportes rápidos.
- **Apache Superset**: Análisis multidimensional avanzado para el futuro *Executive Dashboard* de Aria.

### 🛠️ Despliegue de Infraestructura

Todos los servicios de soporte (Graphiti, Metabase, Superset, Prometheus, Grafana, GrowthBook) están configurados vía Docker Compose:

```bash
# Levantar toda la infraestructura de soporte
docker-compose up -d
```

## How personas relate to skills and commands

Three layers, each with a distinct job:

| Layer | What it is | Example | Composition role |
|-------|-----------|---------|------------------|
| **Skill** | A workflow with steps and exit criteria | `code-review-and-quality` | The *how* — invoked from inside a persona or command |
| **Persona** | A role with a perspective and an output format | `code-reviewer` | The *who* — adopts a viewpoint, produces a report |
| **Command** | A user-facing entry point | `/review`, `/ship` | The *when* — composes personas and skills |

The user (or a slash command) is the orchestrator. **Personas do not call other personas.** Skills are mandatory hops inside a persona's workflow.

## When to use each

### Direct persona invocation
Pick this when you want one perspective on the current change and the user is in the loop.

- "Review this PR" → invoke `code-reviewer` directly
- "Are there security issues in `auth.ts`?" → invoke `security-auditor` directly
- "What tests are missing for the checkout flow?" → invoke `test-engineer` directly
- "Audit Core Web Vitals on the product page" → invoke `web-performance-auditor` directly

### Slash command (single persona behind it)
Pick this when there's a repeatable workflow you'd otherwise re-explain every time.

- `/review` → wraps `code-reviewer` with the project's review skill
- `/test` → wraps `test-engineer` with TDD skill
- `/webperf` → wraps `web-performance-auditor` for performance-focused audits on web apps

### Slash command (orchestrator — fan-out)
Pick this only when **independent** investigations can run in parallel and produce reports that a single agent then merges.

- `/ship` → fans out to `code-reviewer` + `security-auditor` + `test-engineer` in parallel, then synthesizes their reports into a go/no-go decision

This is the only orchestration pattern this repo endorses. See [references/orchestration-patterns.md](../references/orchestration-patterns.md) for the full pattern catalog and anti-patterns.

## Decision matrix

```
Is the work a single perspective on a single artifact?
├── Yes → Direct persona invocation
└── No  → Are the sub-tasks independent (no shared mutable state, no ordering)?
         ├── Yes → Slash command with parallel fan-out (e.g. /ship)
         └── No  → Sequential slash commands run by the user (/spec → /plan → /build → /test → /review)
```

## Worked example: valid orchestration

`/ship` is the canonical fan-out orchestrator in this repo:

```
/ship
  ├── (parallel) code-reviewer    → review report
  ├── (parallel) security-auditor → audit report
  └── (parallel) test-engineer    → coverage report
                  ↓
        merge phase (main agent)
                  ↓
        go/no-go decision + rollback plan
```

Why this works:
- Each sub-agent operates on the same diff but produces a **different perspective**
- They have no dependencies on each other → genuine parallelism, real wall-clock savings
- Each runs in a fresh context window → main session stays uncluttered
- The merge step is small and benefits from full context, so it stays in the main agent

## Worked example: invalid orchestration (do not build this)

A `meta-orchestrator` persona whose job is "decide which other persona to call":

```
/work-on-pr → meta-orchestrator
                  ↓ (decides "this needs a review")
              code-reviewer
                  ↓ (returns)
              meta-orchestrator (paraphrases result)
                  ↓
              user
```

Why this fails:
- Pure routing layer with no domain value
- Adds two paraphrasing hops → information loss + 2× token cost
- The user already knows they want a review; let them call `/review` directly
- Replicates work that slash commands and `AGENTS.md` intent-mapping already do

## Rules for personas

1. A persona is a single role with a single output format. If you find yourself adding a second role, create a second persona.
2. **Personas do not invoke other personas.** Composition is the job of slash commands or the user. On Claude Code this is also a hard platform constraint — *"subagents cannot spawn other subagents"* — so the rule is enforced for you.
3. A persona may invoke skills (the *how*).
4. Every persona file ends with a "Composition" block stating where it fits.

## Claude Code interop

The personas in this repo are designed to work as Claude Code subagents and as Agent Teams teammates without modification:

- **As subagents:** auto-discovered when this plugin is enabled (no path config needed). Use the Agent tool with `subagent_type: code-reviewer` (or `security-auditor`, `test-engineer`). `/ship` is the canonical example.
- **As Agent Teams teammates** (experimental, requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`): reference the same persona name when spawning a teammate. The persona's body is **appended to** the teammate's system prompt as additional instructions (not a replacement), so your persona text sits on top of the team-coordination instructions the lead installs (SendMessage, task-list tools, etc.).

Subagents only report results back to the main agent. Agent Teams let teammates message each other directly. Use subagents when reports are enough; use Agent Teams when sub-agents need to challenge each other's findings (e.g. competing-hypothesis debugging). See [references/orchestration-patterns.md](../references/orchestration-patterns.md) for the full mapping.

Plugin agents do not support `hooks`, `mcpServers`, or `permissionMode` frontmatter — those fields are silently ignored. Avoid relying on them when authoring new personas here.

## Adding a new persona

1. Create `agents/<role>.md` with the same frontmatter format used by existing personas.
2. Define the role, scope, output format, and rules.
3. Add a **Composition** block at the bottom (Invoke directly when / Invoke via / Do not invoke from another persona).
4. Add the persona to the table at the top of this file.
5. If the persona enables a new orchestration pattern, document it in `references/orchestration-patterns.md` rather than inventing the pattern in the persona file itself.

## 🚀 Fase 2: Capacidades de Organización Autónoma (Next Level)

Aria ha evolucionado de un sistema de agentes a una organización autónoma con capacidades avanzadas de auto-juicio, razonamiento relacional y operación web real.

### 8. Capa de Evaluación (Self-Judging)
- **OpenEvals / Inspect AI / DeepEval**: Aria ahora puede juzgar la calidad de sus propias respuestas y decisiones antes de ejecutarlas, asegurando un estándar de calidad corporativo.

### 9. Conocimiento y Razonamiento Relacional
- **Neo4j**: Mapeo de relaciones complejas entre clientes, productos y campañas para una visión 360° del negocio.
- **LlamaIndex**: Investigación profunda y agentes documentales para procesar bibliotecas enteras de conocimiento.

### 10. Operación Web (Navegación Humana)
- **Browser Use / Playwright**: Capacidad para operar aplicaciones SaaS y sitios web reales, realizando acciones como clicks, inputs y navegación compleja.

### 11. Workflows tipo CEO (Procesos de Larga Duración)
- **Temporal / Prefect**: Gestión de procesos que duran días o semanas con persistencia garantizada y reintentos automáticos.

### 12. Inteligencia Económica y Multimedia
- **DuckDB**: Análisis de datos ultra-rápido para reporting financiero.
- **Whisper / ComfyUI**: Transcripción de audio y generación avanzada de activos visuales para marketing.
- **Self-Refine / Reflexion**: Bucles de auto-mejora donde Aria critica y perfecciona su propio trabajo.

### 🛠️ Infraestructura Expandida

```bash
# Levantar la infraestructura completa (incluye Neo4j, Temporal y Postgres)
docker-compose up -d
```

## 🚀 Fase 3: Diferenciación Total (Devin / Manus / HubSpot Level)

Aria ha alcanzado el nivel de las plataformas de IA más avanzadas del mundo, integrando capacidades de memoria adaptativa, investigación profunda y orquestación multi-agente.

### 13. Memoria Inteligente y Adaptativa
- **Mem0**: Memoria personalizada que aprende de cada interacción, recordando preferencias y hechos clave de cada usuario para una personalización extrema.
- **Qdrant / Weaviate**: Motores vectoriales de grado industrial para manejar bases de conocimiento masivas.

### 14. Investigación Profunda (Deep Research)
- **GraphRAG (Microsoft)**: Razonamiento avanzado sobre documentos complejos mediante la extracción de grafos de conocimiento.
- **Open Deep Research**: Flujos de investigación autónoma que navegan, analizan y sintetizan reportes técnicos de alto nivel.

### 15. Orquestación Multi-Agente (Agent Teams)
- **CrewAI**: Tripulaciones de agentes especializados con roles definidos (Investigador, Escritor, QA) que colaboran secuencialmente.
- **AutoGen**: Conversaciones dinámicas entre agentes para resolución de problemas complejos y generación de código.

### 16. Observabilidad y Voz Avanzada
- **Langfuse / AgentOps**: Rastreo de nivel empresarial para monitorear costos, latencia y rendimiento de los agentes en tiempo real.
- **Faster Whisper / Piper TTS**: Capacidades de voz ultra-rápidas para una interacción natural y fluida.

### 🛠️ Infraestructura de Grado Industrial

```bash
# Levantar el ecosistema completo (Vectores, Grafos, Workflows, BI)
docker-compose up -d
```

## 🚀 Fase 4: Business Operating System (Aria BOS)

Aria ha completado su transformación en un **Business Operating System** autónomo, capaz de operar empresas completas mediante gemelos digitales, modelos probabilísticos y conectores empresariales.

### 17. Digital Twin & World Model (Estratega de Negocio)
- **NetworkX**: Aria mantiene un gemelo digital vivo de la organización, mapeando clientes, productos, empleados y flujos financieros.
- **PyMC / Pyro**: Razonamiento probabilístico para la toma de decisiones basada en el valor esperado y el riesgo, no solo en intuición.

### 18. Swarm Intelligence & Economic Brain
- **Mesa**: Coordinación de enjambres masivos de agentes (SEO, Ventas, Contenido) que cooperan para alcanzar objetivos globales.
- **Ray / RLlib**: Aprendizaje por refuerzo para la optimización continua de presupuestos, canales y estrategias de precios.

### 19. Market Radar & Global Intelligence
- **GDELT / OpenAlex**: Monitoreo proactivo de eventos globales y literatura técnica para detectar tendencias antes que la competencia.
- **Autonomous Research Division**: Generación proactiva de inteligencia estratégica sin intervención humana.

### 20. Business Operating System (Operación Real)
- **ERPNext / Odoo / CRM**: Conectividad total con software empresarial para ejecutar facturación, gestión de inventarios y CRM de forma autónoma.
- **Organizational Memory**: Memoria histórica que permite a Aria responder preguntas estratégicas sobre éxitos y fracasos de hace meses o años.

### 🛠️ Ecosistema Empresarial Total

```bash
# Desplegar el Business Operating System de Aria
docker-compose up -d
```
