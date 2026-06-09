"""
ARIA/MEGAN - Main Entry Point (Stable)
"""

import logging
from src.core.config import settings

from src.telegram.bot import main as run_telegram_bot

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL))
logger = logging.getLogger("aria.main")

def main():
    print("\n" + "="*60)
    print("🚀 ARIA/MEGAN - Stable Mode")
    print("="*60)
    logger.info("Starting Telegram Bot...")
    run_telegram_bot()

if __name__ == "__main__":
    main()