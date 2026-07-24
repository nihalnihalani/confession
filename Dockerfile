FROM node:22-bookworm-slim AS dashboard

WORKDIR /build/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build


FROM node:22-bookworm-slim AS runtime

ENV PATH="/opt/confession-venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    CONFESSION_ENV=production \
    CONFESSION_AUTH_REQUIRED=true \
    CONFESSION_SERVE_UI=true \
    CONFESSION_UI_DIST=/app/ui/dist \
    CONFESSION_STATE_DIR=/data \
    CONFESSION_DATABASE_PATH=/data/confession.sqlite3

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/confession-venv

WORKDIR /app
COPY engine/requirements.txt ./engine/requirements.txt
RUN pip install --no-cache-dir -r engine/requirements.txt

COPY --chown=node:node engine/ ./engine/
COPY --chown=node:node target-app/TASKS.md ./target-app/TASKS.md
COPY --chown=node:node --from=dashboard /build/ui/dist ./ui/dist

RUN mkdir -p /data /home/node/.npm \
    && chown -R node:node /data /home/node/.npm

USER node
EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)"

CMD ["uvicorn", "confession.server:app", "--app-dir", "engine", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-graceful-shutdown", "5"]
