# ARIA Agent System — Browser (Playwright + Chromium aislado)
FROM mcr.microsoft.com/playwright/python:v1.47.0

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

# Crear directorio de perfiles
RUN mkdir -p /app/profiles && chmod 777 /app/profiles

ENV BROWSER_TIMEOUT_SECONDS=60
ENV BROWSER_HEADLESS=true
ENV DISPLAY=:99

EXPOSE 9222

CMD ["python", "-m", "browser.manager"]
