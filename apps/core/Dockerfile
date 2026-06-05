FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY apps/core/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code
COPY apps/ apps/

# Environment
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Verify all imports work at build time — this fails the build if any import is broken
RUN python -c "
import sys, traceback
print('=== Build-time import check ===')
failures = []
checks = [
    'from apps.core.config import settings',
    'from apps.core.memory.redis_client import get_cache',
    'from apps.core.memory.supabase_client import get_db',
    'from apps.core.tools.ai_client import AIModel, get_ai_client',
    'from apps.core.tools.telegram_bot import AriaTelegramBot, get_bot',
    'import apps.core.main',
]
for stmt in checks:
    try:
        exec(compile(stmt, '<check>', 'exec'))
        print('  OK:', stmt[:60])
    except Exception as e:
        print('  FAIL:', stmt[:60])
        traceback.print_exc()
        failures.append(stmt)
if failures:
    print('IMPORT ERRORS FOUND - fix before deploying')
    sys.exit(1)
print('=== All imports OK ===')
"

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "apps.core.main:app", "--host", "0.0.0.0", "--port", "8000"]
