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

# Verify imports work at build time (fails build if there's an import error)
RUN python -c "import apps.core.main; print('Import OK')"

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "apps.core.main:app", "--host", "0.0.0.0", "--port", "8000"]
