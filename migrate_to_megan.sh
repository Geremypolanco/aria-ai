#!/bin/bash
# Script para migrar el repositorio aria-ai a la arquitectura MEGAN

echo "Iniciando migración a MEGAN..."

# 1. Crear directorios necesarios si no existen
mkdir -p src/core/config src/core/events src/core/runtime src/core/memory src/agents src/tools/external src/cognition src/api

# 2. Mover archivos de la fase de desarrollo a sus posiciones finales (ya están en src/)
# Nota: En este entorno ya los hemos creado directamente en src/

# 3. Crear el archivo de requerimientos actualizado
cat <<EOF > requirements.txt
asyncio
aiosqlite
httpx
fastapi
uvicorn
pydantic
python-dotenv
python-telegram-bot
redis
EOF

# 4. Crear un archivo .env de ejemplo
cat <<EOF > .env.example
TELEGRAM_TOKEN=tu_token_aqui
SHOPIFY_ADMIN_TOKEN=tu_token_aqui
SHOPIFY_URL=tu_tienda.myshopify.com
HF_TOKEN=tu_token_huggingface
EOF

echo "Migración completada. El sistema MEGAN está listo en el directorio src/."
