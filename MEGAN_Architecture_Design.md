# MEGAN: Arquitectura Cognitiva Persistente para ARIA-AI

## 1. Visión General

Este documento detalla la re-arquitectura completa de ARIA-AI, transformándola en MEGAN, una arquitectura cognitiva persistente inspirada en sistemas avanzados de IA. El objetivo es crear un sistema autónomo, modular, escalable y con capacidades de auto-evolución, priorizando la estabilidad, fiabilidad y eficiencia de recursos.

## 2. Principios Arquitectónicos Clave

MEGAN se construirá bajo los siguientes principios:

*   **Orquestación sobre Tamaño del Modelo:** La inteligencia reside en la coordinación de agentes y la gestión del contexto, no solo en el tamaño de los modelos subyacentes.
*   **Memoria sobre Respuestas sin Estado:** Implementación de un sistema de memoria multinivel para una cognición persistente.
*   **Cognición sobre Generación Simple:** Enfoque en razonamiento reflexivo, planificación adaptativa y conciencia contextual.
*   **Modularidad sobre Monolítico:** Componentes desacoplados para facilitar la evolución y el mantenimiento.
*   **Persistencia sobre Interacción Basada en Sesiones:** Mantenimiento del estado y la identidad a largo plazo.
*   **Eficiencia de Recursos:** Optimización para CPU, modelos cuantizados/locales y despliegue ligero.

## 3. Estructura del Repositorio (Propuesta)

La nueva estructura del repositorio reflejará la modularidad y las capas cognitivas de MEGAN:

```
aria-ai/
├── .github/                 # Workflows de CI/CD, plantillas de issues
├── .fly/                    # Configuraciones de Fly.io
├── docs/                    # Documentación de arquitectura, agentes, memoria
├── tests/                   # Pruebas unitarias, de integración y de sistema
├── src/                     # Código fuente principal de MEGAN
│   ├── core/                # Núcleo del sistema cognitivo
│   │   ├── config/          # Gestión de configuración y secretos
│   │   ├── events/          # Definiciones del Event Bus
│   │   ├── runtime/         # Bucle de ejecución persistente, State Synchronization
│   │   ├── memory/          # Implementación de todos los tipos de memoria
│   │   ├── world_model/     # Mantenimiento del estado del mundo
│   │   ├── self_model/      # Representación interna de MEGAN
│   │   └── logging/         # Logging estructurado y observabilidad
│   ├── agents/              # Definiciones y lógica de agentes especializados
│   │   ├── base_agent.py    # Clase base para todos los agentes
│   │   ├── planner_agent.py # Planificación y jerarquía de objetivos
│   │   ├── research_agent.py# Investigación y adquisición de conocimiento
│   │   ├── coding_agent.py  # Generación y refactorización de código
│   │   ├── memory_agent.py  # Gestión activa de la memoria
│   │   ├── reflection_agent.py# Análisis de fallos y mejora continua
│   │   ├── orchestration_agent.py # Coordinación de agentes y tareas
│   │   ├── voice_agent.py   # Interacción por voz
│   │   ├── vision_agent.py  # Procesamiento de visión
│   │   ├── task_agent.py    # Ejecución de tareas atómicas
│   │   ├── monitoring_agent.py# Monitoreo de runtime
│   │   └── safety_agent.py  # Permisos y sistemas de seguridad
│   ├── tools/               # Framework de ejecución de herramientas
│   │   ├── base_tool.py     # Clase base para herramientas
│   │   ├── external/        # Integraciones con APIs externas (Shopify, HF, etc.)
│   │   ├── internal/        # Herramientas internas (ejecución de código, gestión de archivos)
│   │   └── dynamic_loader.py# Carga dinámica de herramientas
│   ├── orchestration/       # Capa de orquestación principal (Task Orchestration Layer)
│   │   ├── planner.py       # Planificación adaptativa
│   │   ├── goal_manager.py  # Gestión de jerarquía de objetivos
│   │   └── task_manager.py  # Gestión del ciclo de vida de las tareas
│   ├── cognition/           # Pipelines cognitivos internos
│   │   ├── reflection_engine.py # Motor de reflexión y autoevaluación
│   │   ├── planning_engine.py   # Motor de planificación
│   │   └── context_engine.py    # Ingeniería de contexto dinámico
│   └── interfaces/          # Puntos de entrada y salida (Telegram, Webhooks, CLI)
│       ├── telegram/        # Lógica del bot de Telegram
│       ├── webhooks/        # Gestión de webhooks entrantes/salientes
│       └── cli/             # Interfaz de línea de comandos
├── main.py                  # Punto de entrada principal de la aplicación
├── requirements.txt         # Dependencias del proyecto
└── README.md                # Descripción del proyecto
```

## 4. Sistemas Mandatorios (Implementación por Fases)

La implementación se realizará en fases, priorizando la estabilidad y la coherencia arquitectónica:

1.  **Persistent Runtime Loop:** El corazón de MEGAN, asegurando ejecución continua y gestión del estado.
2.  **Core Event Bus:** Un sistema de comunicación asíncrona para todos los componentes.
3.  **Multi-Level Memory System:** Implementación de Short-Term, Working, Episodic, Semantic, User, Identity, Project, Goal y World-State Memory.
4.  **World Model Engine:** Mantenimiento de una representación interna persistente del entorno.
5.  **Self-Model System:** Representación interna de las capacidades, estado y objetivos de MEGAN.
6.  **Multi-Agent Architecture:** Desarrollo de agentes especializados con responsabilidades claras y comunicación estructurada.
7.  **Tool Execution Framework:** Un sistema robusto para la ejecución y gestión de herramientas internas y externas.
8.  **Reflection & Self-Evaluation Engine:** Mecanismos para analizar el rendimiento y mejorar de forma autónoma.
9.  **Planning & Goal Hierarchy System:** Para la planificación adaptativa y la gestión de objetivos complejos.
10. **Task Orchestration Layer:** Coordinación de tareas a través de los agentes.
11. **State Synchronization Layer:** Para mantener la coherencia del estado a través de componentes distribuidos.
12. **Internal Cognitive Logging & Runtime Monitoring:** Para observabilidad y diagnóstico.
13. **Permission & Safety Systems:** Garantizar operaciones éticas y seguras.
14. **Recovery & Rollback Systems:** Para resiliencia ante fallos.
15. **Local-first Operational Logic:** Priorizar la ejecución local cuando sea posible.
16. **Distributed Node Coordination:** Para escalabilidad horizontal.
17. **Dynamic Context Engineering:** Gestión inteligente del contexto para agentes.
18. **Voice Interaction Layer:** Para interfaces de voz.
19. **Vision Processing Layer:** Para comprensión visual.

## 5. Consideraciones de Infraestructura

*   **GitHub:** Control de versiones y CI/CD.
*   **Fly.io:** Despliegue principal, aprovechando su escalabilidad y eficiencia.
*   **Bases de Datos:** PostgreSQL para memoria persistente (Episodic, Semantic, World Model) y SQLite para memoria local/caché.
*   **Modelos:** Prioridad a modelos cuantizados o más pequeños que se ejecuten eficientemente en CPU.

## 6. Próximos Pasos

La siguiente fase se centrará en la implementación del `Persistent Runtime Loop` y el `Core Event Bus` como la base de la nueva arquitectura. Esto sentará las bases para todos los demás sistemas cognitivos.
