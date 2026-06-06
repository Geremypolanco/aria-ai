FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    librandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY apps/core/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium --with-deps

# Code
COPY apps/ apps/

# Environment
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Verify imports work at build time (fails build if there's an import error)
RUN python -c "import apps.core.main; print('Import OK')"

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "apps.core.main:app", "--host", "0.0.0.0", "--port", "8000"]
