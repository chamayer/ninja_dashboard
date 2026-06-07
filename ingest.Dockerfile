# =============================================================================
# ninja-dashboard / ingest
# Python service: pulls NinjaRMM v2 API on a schedule, writes Postgres.
# =============================================================================
FROM python:3.12-slim

# Non-root user
RUN groupadd -r ninja && useradd -r -g ninja -d /app ninja

WORKDIR /app

# Python deps first (layer caching — rarely changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code + SQL migrations (everything else excluded by .dockerignore)
COPY ingest/ ./ingest/
COPY sql/   ./sql/
COPY VERSION ./

RUN chown -R ninja:ninja /app
USER ninja

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    INGEST_HTTP_PORT=8090

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=10m --retries=5 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"INGEST_HTTP_PORT\",\"8090\")}/healthz')" || exit 1
# start-period generous because main.py runs DB migrations BEFORE the
# HTTP server starts — a long migration (or a backfill of activities)
# can take several minutes, and a short start-period leads to the
# container being killed mid-migration in a restart loop.

CMD ["python", "-m", "ingest.main"]
