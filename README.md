# 🚀 ARIA — Autonomous Reasoning Intelligence Agent (v2.1.0)

Aria es un sistema de IA autónomo de última generación que combina las capacidades de razonamiento profundo de **Manus** con el entorno de desarrollo interactivo de **Replit**, eliminando las limitaciones de ambas plataformas.

## ✨ Características Principales (v2.1.0)

### 🧠 Motor de Razonamiento Superior
- **Orquestación Dinámica:** Planificación y descomposición de tareas complejas en sub-tareas ejecutables.
- **MCP Connector (Extensibilidad Infinita):** Soporte nativo para el *Model Context Protocol*, permitiendo conectar Aria a cualquier servidor de herramientas MCP.
- **Integración con Zapier (Zanier):** Acceso a más de 6,000 aplicaciones y 20,000 acciones para automatizar flujos de trabajo en el mundo real.
- **Contexto Infinito:** Gestión de memoria persistente que supera las limitaciones de ventana de contexto tradicionales.

### 💻 Entorno de Desarrollo (Replit++)
- **Universal Sandbox:** Ejecución segura de código en más de 20 lenguajes (Python, Node.js, Go, Rust, etc.).
- **Gestión Avanzada de Secretos:** Almacenamiento encriptado de API keys y credenciales con auditoría de acceso (estilo Replit Secrets).
- **Orquestación Multi-Cloud:** Despliegue y monitoreo en tiempo real en Vercel, Fly.io, AWS, GCP y Azure con rollback automático.
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
| **Orchestrator** | Cerebro Central | Planificación, Razonamiento, Gestión MCP |
| **Dev Agent** | Desarrollo | Código, Testing, Debugging, Secrets |
| **Research Agent** | Investigación | Búsqueda, Análisis, Zapier Actions |
| **Interaction Agent** | Ejecución | Browser, Shell, Multi-Cloud Deploy |

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
Aria ejecuta todo el código en entornos sandbox aislados y protege tus credenciales mediante un sistema de encriptación Fernet de grado industrial.

## 📄 Licencia
Este proyecto está bajo la Licencia MIT. Ver el archivo [LICENSE](LICENSE) para más detalles.

---
Creado con ❤️ para superar los límites de la IA autónoma.
