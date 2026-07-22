FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc ffmpeg libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxext6 \
    libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
    libcairo2 fonts-liberation libx11-6 libxcb1 libxss1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY apps/core/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy entire project
COPY . .

RUN useradd --system --create-home --uid 10001 aria && chown -R aria:aria /app
USER aria

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "apps.core.main:app", "--host", "0.0.0.0", "--port", "8080"]