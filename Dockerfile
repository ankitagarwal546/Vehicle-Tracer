# Single-container VITRA image: the FastAPI backend serves the built web app on one port.
# Used for Hugging Face Spaces and any other Docker host. docker-compose.yml is still the local two-container setup.

FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi8 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 vitra
WORKDIR /srv/backend

# CPU-only PyTorch keeps the image several GB smaller than the default CUDA build.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=vitra:vitra backend/ ./
COPY --from=web --chown=vitra:vitra /web/dist /srv/web
RUN mkdir -p storage/uploads storage/artifacts storage/models && chown -R vitra:vitra storage

USER vitra
ENV HOME=/home/vitra \
    PORT=7860 \
    DEVICE=cpu \
    FRONTEND_DIST=/srv/web \
    CORS_ORIGINS="" \
    REQUIRE_AUTH=true \
    COOKIE_SECURE=true \
    COOKIE_SAMESITE=none

# Bake the model weights into the image so the server never downloads at startup.
RUN python scripts/download_models.py

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health')"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
