# ARIA Agent System — Sandbox (Ejecución Aislada de Comandos)
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /sandbox

# Usuario no-root para seguridad
RUN useradd -m -s /bin/bash sandbox && \
    chown -R sandbox:sandbox /sandbox
USER sandbox

COPY scripts/init.sh /sandbox/init.sh
RUN chmod +x /sandbox/init.sh

ENTRYPOINT ["/sandbox/init.sh"]
