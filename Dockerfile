FROM python:3.12-slim

WORKDIR /app

# Install all system libraries that Chromium needs
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxext6 \
    libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
    libcairo2 fonts-liberation libx11-6 libxcb1 libxss1 \
    && rm -rf /var/lib/apt/lists/*

COPY apps/core/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download Chromium binary only (no --with-deps since system libs are installed above)
RUN playwright install chromium

COPY apps/ apps/
COPY docs/ docs/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "apps.core.main:app", "--host", "0.0.0.0", "--port", "8080"]
