# Investigación Técnica: MCP y Zapier NLA para Aria v2.1.0

## Model Context Protocol (MCP)
- **Arquitectura**: Cliente-Servidor sobre JSON-RPC 2.0.
- **Transportes**: 
  - `stdio`: Para servidores locales (procesos hijo).
  - `http`: Para servidores remotos (usando SSE para streaming).
- **Primitivas**:
  - `Tools`: Funciones ejecutables (schema JSON).
  - `Resources`: Datos de solo lectura (URIs).
  - `Prompts`: Plantillas predefinidas.
- **Ciclo de vida**: `initialize` -> `initialized` -> `list_tools` -> `call_tool`.

## Zapier Natural Language Actions (NLA) / Zapier MCP
- **API NLA**: Permite ejecutar acciones de Zapier usando lenguaje natural.
- **Zapier MCP Server**: Zapier ahora ofrece un servidor MCP oficial (`https://mcp.zapier.com/mcp`).
- **Autenticación**: Requiere API Key o OAuth2 para acceder a las acciones configuradas en la cuenta del usuario.
- **Capacidad**: Acceso a >6000 apps y >20,000 acciones.

## Estrategia para Aria
1. **MCP Client**: Implementar un cliente genérico en `apps/core/tools/mcp_client.py` que soporte tanto `stdio` como `http`.
2. **Zapier Connector**: Integrar el servidor MCP de Zapier como un conector estándar.
3. **Secret Management**: Implementar un almacén seguro para las API Keys de Zapier y otros servicios.
