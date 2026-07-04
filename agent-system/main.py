"""
ARIA Agent System — Entry point.
"""
import uvicorn
from core.config.settings import settings

if __name__ == "__main__":
    uvicorn.run(
        "api.server:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=False,
        log_level=settings.LOG_LEVEL.lower(),
    )