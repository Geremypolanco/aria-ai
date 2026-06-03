FROM python:3.12-slim

WORKDIR /app

# Dependencias del sistema
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Dependencias Python
COPY apps/core/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código
COPY apps/ apps/

# Variables de entorno
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "apps.core.main:app", "--host", "0.0.0.0", "--port", "8000"]
