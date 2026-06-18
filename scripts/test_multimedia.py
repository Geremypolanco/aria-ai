
import asyncio
import logging
import os
import sys
from pathlib import Path

# Añadir el path raíz para que las importaciones de apps funcionen
sys.path.append(str(Path(__file__).parent.parent))

from apps.core.config import settings
from apps.core.tools.huggingface_suite import HuggingFaceSuite
from apps.core.tools.creative_engine import CreativeEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_multimedia")

async def test_all():
    logger.info("=== TEST DE MULTIMEDIA ARIA ===")
    
    # 1. Verificar Configuración
    hf_token = settings.hf_key
    logger.info(f"HF_TOKEN configurado: {'SÍ' if hf_token else 'NO'}")
    if hf_token:
        logger.info(f"HF_TOKEN (primeros 5): {hf_token[:5]}...")
    
    hf = HuggingFaceSuite()
    creative = CreativeEngine()
    
    # 2. Test Imagen
    logger.info("\n--- Test Generación de Imagen ---")
    img_res = await hf.generate_image("A futuristic robot holding a sign that says ARIA OS", width=512, height=512)
    if img_res.get("success"):
        logger.info(f"✅ Imagen generada exitosamente. Tamaño: {len(img_res.get('image_bytes', b''))} bytes")
    else:
        logger.error(f"❌ Fallo en imagen: {img_res.get('error')}")
    
    # 3. Test Música
    logger.info("\n--- Test Generación de Música ---")
    music_res = await creative.generate_music("Upbeat electronic music for a tech startup", duration=5)
    if music_res.get("success"):
        logger.info(f"✅ Música generada exitosamente.")
        # Verificar si hay audio_base64 o audio_b64
        ab64 = music_res.get("audio_base64") or music_res.get("audio_b64")
        if ab64:
            logger.info(f"✅ Base64 de audio encontrado ({len(ab64)} chars)")
        else:
            logger.error("❌ No se encontró base64 de audio en la respuesta")
    else:
        logger.error(f"❌ Fallo en música: {music_res.get('error')}")

    # 4. Test Video
    logger.info("\n--- Test Generación de Video ---")
    video_res = await creative.generate_video("A sunset over a digital ocean")
    if video_res.get("success"):
        logger.info(f"✅ Video generado exitosamente.")
        v64 = video_res.get("video_base64") or video_res.get("video_b64")
        if v64:
            logger.info(f"✅ Base64 de video encontrado ({len(v64)} chars)")
        else:
            logger.error("❌ No se encontró base64 de video en la respuesta")
    else:
        logger.error(f"❌ Fallo en video: {video_res.get('error')}")

if __name__ == "__main__":
    asyncio.run(test_all())
