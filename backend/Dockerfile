# GumaWeb API image. Build from the repository root (the image bundles /templates):
#   docker build -f backend/Dockerfile -t gumaweb/api:dev .
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY backend/requirements/ requirements/
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements/prod.txt

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    TEMPLATES_DIR=/srv/templates \
    GENERATED_SITES_DIR=/srv/generated-sites \
    LOG_JSON=true
RUN groupadd --system --gid 10001 gumaweb && useradd --system --uid 10001 --gid gumaweb --home /app gumaweb \
    && mkdir -p /srv/generated-sites && chown gumaweb:gumaweb /srv/generated-sites
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=gumaweb:gumaweb backend/ /app/
COPY --chown=gumaweb:gumaweb templates/ /srv/templates/
USER gumaweb
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status == 200 else 1)"
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000", "-w", "4", "--access-logfile", "-", "--graceful-timeout", "30"]
