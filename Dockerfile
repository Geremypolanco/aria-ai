FROM python:3.12-slim

WORKDIR /app

# System dependencies
# bubblewrap (bwrap) provides the real OS-level sandbox for execute_code
# (apps/core/tools/code_runner.py) — unprivileged mount/pid/net/ipc/uts
# namespaces around AI-generated code. CodeRunner probes at runtime
# whether it actually works in this environment and falls back to
# unsandboxed execution (still with real ulimit resource limits) if not.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc ffmpeg libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxext6 \
    libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
    libcairo2 fonts-liberation libx11-6 libxcb1 libxss1 bubblewrap \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY apps/core/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# `pip install playwright` only installs the Python driver — it does NOT
# bundle a browser. Without this step, every Playwright launch()
# (human_browser.py's stealth browsing, browser_sandbox.py) fails at
# runtime with "Executable doesn't exist" because no browser binary was
# ever downloaded into the image. The apt packages above provide the OS
# shared libraries Chromium needs; this downloads the browser itself.
# PLAYWRIGHT_BROWSERS_PATH is set before install so the browser lands in a
# path the non-root `aria` user (created below) can read — the default
# /root/.cache/ms-playwright wouldn't be.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-browsers
RUN playwright install chromium && chmod -R a+rX /ms-browsers

# Copy entire project
COPY . .

RUN useradd --system --create-home --uid 10001 aria && chown -R aria:aria /app
USER aria

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "apps.core.main:app", "--host", "0.0.0.0", "--port", "8080"]