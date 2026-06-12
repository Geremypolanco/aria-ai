FROM python:3.12-slim

  WORKDIR /app

  # System dependencies
  RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
      libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxext6 \
      libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
      libcairo2 fonts-liberation \
      && rm -rf /var/lib/apt/lists/*

  # Python dependencies from apps/core (the real requirements)
  COPY apps/core/requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt

  # Application code
  COPY apps/ apps/

  ENV PYTHONPATH=/app
  ENV PYTHONUNBUFFERED=1

  EXPOSE 8000

  CMD ["python", "-m", "uvicorn", "apps.core.main:app", "--host", "0.0.0.0", "--port", "8000"]
  