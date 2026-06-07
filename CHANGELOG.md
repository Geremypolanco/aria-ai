# Changelog — ARIA AI

Todos los cambios notables en este proyecto se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.0.0/),
y este proyecto adhiere a [Semantic Versioning](https://semver.org/lang/es/).

---

## [Unreleased]

### Añadido
- `process_auditor.py` — Auditor Universal de Procesos con 7 macrocapas (Estratégica, Operacional, Técnica, Financiera, Seguridad, Analítica, Compliance)
- `.github/workflows/process-audit.yml` — Workflow de GitHub Actions para auditoría automática en cada push
- `.github/dependabot.yml` — Configuración de Dependabot para actualizaciones automáticas de dependencias
- `SECURITY.md` — Política de seguridad y proceso de reporte de vulnerabilidades
- `CHANGELOG.md` — Este archivo de registro de cambios

### Pendiente
- Suite de tests con pytest (cobertura mínima 70%)
- `LICENSE` — Licencia del proyecto
- `PRIVACY.md` — Política de privacidad
- `TERMS.md` — Términos de servicio
- `ROADMAP.md` — Hoja de ruta con milestones trimestrales

---

## [2.0.0] — 2025 (Transformación)

### Añadido
- `aria_orchestrator.py` — Orquestador central con ética y sentimiento
- `ethics_engine.py` — Motor de evaluación ética de acciones
- `evolution_loop.py` — Bucle de aprendizaje evolutivo
- `rd_wing.py` — Ala de Investigación y Desarrollo
- `sentiment_engine.py` — Motor de sentimiento de ARIA
- `ecommerce_agent.py` — Agente de comercio electrónico
- `code_reflector.py` — Reflector y analizador de código
- `deployment_orchestrator.py` — Orquestador de deployments

### Cambiado
- Arquitectura migrada a sistema multi-agente con conciencia ética
- Motor IA: HuggingFace (primario) → Groq → OpenAI (fallback)

---

## [1.0.0] — 2024 (Fundación)

### Añadido
- Sistema base multi-agente: `orchestrator`, `pm_agent`, `dev_agent`, `cfo_agent`, `compliance_agent`, `content_agent`, `marketing_agent`, `research_agent`, `support_agent`
- Integración con Supabase para persistencia de datos
- Deploy en Fly.io con GitHub Actions CI/CD
- Bots: `content_bot`, `finance_bot`, `monitor_bot`, `scheduler_bot`, `social_bot`
- Integraciones: Shopify, LinkedIn, Gmail, Telegram, Zapier
- `base_agent.py` — Clase base con circuit breaker y logging

[Unreleased]: https://github.com/Geremypolanco/aria-ai/compare/HEAD...HEAD
