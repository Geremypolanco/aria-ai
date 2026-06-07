# Security Policy — ARIA AI

## Versiones Soportadas

| Versión | Soporte de Seguridad |
|---------|---------------------|
| main    | ✅ Activo           |

## Reportar una Vulnerabilidad

Si descubres una vulnerabilidad de seguridad en ARIA AI, por favor **no abras un Issue público**.

### Proceso de Reporte

1. Envía un email a **geremypolancod@gmail.com** con el asunto `[SECURITY] Vulnerabilidad en aria-ai`
2. Incluye:
   - Descripción detallada de la vulnerabilidad
   - Pasos para reproducirla
   - Impacto potencial
   - Sugerencias de mitigación (opcional)

### Tiempos de Respuesta

- **Acuse de recibo**: 48 horas
- **Evaluación inicial**: 7 días
- **Resolución**: 30 días (dependiendo de la severidad)

## Políticas de Seguridad

### Secretos y Credenciales
- Todos los secretos se gestionan via **Fly.io Secrets** y **GitHub Secrets**
- Nunca se commitean credenciales al repositorio
- El archivo `.env` está excluido via `.gitignore`
- Se usa `.env.example` como referencia sin valores reales

### Dependencias
- Las dependencias se revisan semanalmente via **Dependabot**
- Las actualizaciones de seguridad se priorizan sobre las de features

### Acceso
- Los tokens de API tienen permisos mínimos necesarios (principio de mínimo privilegio)
- Los accesos se auditan regularmente por el `compliance_agent`

### CI/CD
- Los deployments requieren pasar el pre-flight check de sintaxis
- Las variables de entorno sensibles se inyectan en runtime, no en build time

## Herramientas de Seguridad Utilizadas

- **GitHub Dependabot**: Actualizaciones automáticas de dependencias
- **GitHub Secrets**: Gestión segura de credenciales en CI/CD
- **Fly.io Secrets**: Gestión segura de variables en producción
- **Compliance Agent**: Auditoría continua de operaciones autónomas
- **Process Auditor**: Auditoría de las 7 macrocapas incluyendo seguridad
