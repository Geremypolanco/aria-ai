# Standalone image for Lingua — built from this directory only (`language-app/`
# is its own build context), independent from the root ARIA Dockerfile/image.

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

RUN useradd --system --create-home --uid 10001 lingua \
    && mkdir -p /app/data \
    && chown -R lingua:lingua /app
USER lingua

ENV PYTHONUNBUFFERED=1
ENV LINGUA_PORT=8100
ENV LINGUA_DB_PATH=/app/data/lingua.db
ENV LINGUA_CACHE_DIR=/app/data/media_cache

EXPOSE 8100

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8100"]
