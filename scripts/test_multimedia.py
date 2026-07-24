
import asyncio
import logging
import sys
from pathlib import Path

# Add the repo root so apps.* imports work.
sys.path.append(str(Path(__file__).parent.parent))

from apps.core.config import settings
from apps.core.tools.huggingface_suite import HuggingFaceSuite
from apps.core.tools.creative_engine import CreativeEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_multimedia")

async def test_all():
    logger.info("=== ARIA MULTIMEDIA TEST ===")

    # 1. Check configuration
    hf_token = settings.hf_key
    logger.info(f"HF_TOKEN configured: {'YES' if hf_token else 'NO'}")
    if hf_token:
        logger.info(f"HF_TOKEN (first 5): {hf_token[:5]}...")

    hf = HuggingFaceSuite()
    creative = CreativeEngine()

    # 2. Image test
    logger.info("\n--- Image Generation Test ---")
    img_res = await hf.generate_image("A futuristic robot holding a sign that says ARIA OS", width=512, height=512)
    if img_res.get("success"):
        logger.info(f"✅ Image generated successfully. Size: {len(img_res.get('image_bytes', b''))} bytes")
    else:
        logger.error(f"❌ Image failed: {img_res.get('error')}")

    # 3. Music test
    logger.info("\n--- Music Generation Test ---")
    music_res = await creative.generate_music("Upbeat electronic music for a tech startup", duration=5)
    if music_res.get("success"):
        logger.info(f"✅ Music generated successfully.")
        # Check for audio_base64 or audio_b64
        ab64 = music_res.get("audio_base64") or music_res.get("audio_b64")
        if ab64:
            logger.info(f"✅ Audio base64 found ({len(ab64)} chars)")
        else:
            logger.error("❌ No audio base64 found in the response")
    else:
        logger.error(f"❌ Music failed: {music_res.get('error')}")

    # 4. Video test
    logger.info("\n--- Video Generation Test ---")
    video_res = await creative.generate_video("A sunset over a digital ocean")
    if video_res.get("success"):
        logger.info(f"✅ Video generated successfully.")
        v64 = video_res.get("video_base64") or video_res.get("video_b64")
        if v64:
            logger.info(f"✅ Video base64 found ({len(v64)} chars)")
        else:
            logger.error("❌ No video base64 found in the response")
    else:
        logger.error(f"❌ Video failed: {video_res.get('error')}")

if __name__ == "__main__":
    asyncio.run(test_all())
