"""ARIA AI — Main Entry Point.

Boots the FastAPI webhook server and the Telegram bot polling loop
concurrently using asyncio. This is what Fly.io executes.
"""
import asyncio
import logging
import os

import uvicorn
from dotenv import load_dotenv

from aria.bot.telegram import build_application
from aria.api.server import create_app

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("aria.main")


async def run_bot(app):
    """Run Telegram bot in polling mode."""
    logger.info("Starting Telegram bot...")
    async with app:
        await app.start()
        await app.updater.start_polling(allowed_updates=None)
        await asyncio.Event().wait()  # run forever
        await app.updater.stop()
        await app.stop()


async def run_api(fastapi_app):
    """Run FastAPI server."""
    config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        log_level="info",
    )
    server = uvicorn.Server(config)
    logger.info("Starting FastAPI server on port %s...", os.getenv("PORT", "8080"))
    await server.serve()


async def main():
    telegram_app = build_application()
    fastapi_app = create_app()
    await asyncio.gather(
        run_bot(telegram_app),
        run_api(fastapi_app),
    )


if __name__ == "__main__":
    asyncio.run(main())
