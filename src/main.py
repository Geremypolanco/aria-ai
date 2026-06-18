"""
ARIA - Main Entry Point (Stable Redirect to Aria OS)
"""

import logging
import asyncio
import os
import sys

# Añadir el path raíz para que las importaciones de apps funcionen
sys.path.append(os.getcwd())

from apps.core.main import app
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aria.main")

def main():
    print("\n" + "="*60)
    print("🚀 ARIA OS - Production Mode (Multimedia Enabled)")
    print("="*60)
    
    port = int(os.getenv("PORT", "8000"))
    
    # Ejecutar la app de FastAPI que contiene el bot avanzado y multimedia
    logger.info(f"Starting Aria OS on port {port}...")
    uvicorn.run("apps.core.main:app", host="0.0.0.0", port=port, reload=False)

if __name__ == "__main__":
    main()
