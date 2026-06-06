# 🚀 ARIA — Autonomous Reasoning Intelligence Agent (v2.0.0)

Aria es un sistema de IA autónomo de última generación que combina las capacidades de razonamiento profundo de **Manus** con el entorno de desarrollo interactivo de **Replit**, eliminando las limitaciones de ambas plataformas.

## ✨ Características Principales

### 🧠 Motor de Razonamiento Superior
- **Orquestación Dinámica:** Planificación y descomposición de tareas complejas en sub-tareas ejecutables.
- **Razonamiento Multi-modelo:** Utiliza GPT-4o, Claude 3.5 Sonnet y Qwen 2.5 para diferentes etapas del razonamiento.
- **Auto-corrección:** Capacidad de reflexionar sobre sus propios errores y corregirlos en tiempo real.
- **Contexto Infinito:** Gestión de memoria persistente que supera las limitaciones de ventana de contexto tradicionales.

### 💻 Entorno de Desarrollo (Replit++)
- **Universal Sandbox:** Ejecución segura de código en más de 20 lenguajes (Python, Node.js, Go, Rust, etc.).
- **REPL en Tiempo Real:** Interacción inmediata con el código y terminal integrada.
- **Despliegue Automático:** Despliegue con un clic a Vercel, Fly.io, Netlify o AWS.
- **Análisis de Repositorios:** Capacidad de clonar, entender y modificar repositorios completos de GitHub.

### 🤖 Agente Autónomo (Manus++)
- **Navegación Web Real:** Navegador Chromium headless para interactuar con cualquier sitio web, completar formularios y extraer datos.
- **Investigación Profunda:** Búsqueda web multi-fuente con síntesis automática y citación académica.
- **Gestión de Archivos:** Manipulación completa del sistema de archivos local y remoto.
- **Integraciones Nativas:** GitHub, Docker, Bases de Datos (PostgreSQL, MySQL, Redis), y APIs externas.

## 🛠 Arquitectura

ARIA utiliza una arquitectura de microservicios basada en agentes especializados:

| Agente | Función | Capacidades |
| :--- | :--- | :--- |
| **Orchestrator** | Cerebro Central | Planificación, Razonamiento, Síntesis |
| **Dev Agent** | Desarrollo | Código, Testing, Debugging, Deploy |
| **Research Agent** | Investigación | Búsqueda, Análisis, Reportes |
| **Interaction Agent** | Ejecución | Browser, Shell, Archivos |

## 🚀 Inicio Rápido

### Requisitos
- Python 3.10+
- Node.js 18+
- Docker (opcional, para sandboxing avanzado)

### Instalación
```bash
git clone https://github.com/Geremypolanco/aria-ai.git
cd aria-ai
pip install -r requirements.txt
npm install
```

### Ejecución
```bash
# Iniciar backend
python -m apps.api.main

# Iniciar frontend
npm run dev
```

## 🔒 Seguridad y Privacidad
Aria ejecuta todo el código en entornos sandbox aislados y permite el uso de modelos locales (vía Ollama) para máxima privacidad.

## 📄 Licencia
Este proyecto está bajo la Licencia MIT. Ver el archivo [LICENSE](LICENSE) para más detalles.

---
Creado con ❤️ para superar los límites de la IA autónoma.
