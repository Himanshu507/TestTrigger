# Backend: FastAPI, workflow graph, SQLite, and ChromaDB.
#
# This is a local development and demo image. It is not hardened for public
# hosting. No secret is ever baked into a layer: OPENAI_API_KEY arrives at
# container runtime from the developer's environment or ignored .env file.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# Dependencies are installed from the pinned project metadata before the source
# is copied, so an application edit does not invalidate the dependency layer.
COPY pyproject.toml README.md ./
COPY app/__init__.py ./app/
RUN pip install --upgrade pip && pip install .

COPY app ./app
COPY data ./data
COPY knowledge_base ./knowledge_base
COPY scripts ./scripts
COPY frontend ./frontend
COPY docker/backend-entrypoint.sh /usr/local/bin/backend-entrypoint
RUN chmod +x /usr/local/bin/backend-entrypoint

# Persistent demo state lives on a mounted volume, not in the container layer.
ENV DATABASE_URL=sqlite:////srv/data-local/test-trigger.db \
    CHROMA_PERSIST_DIRECTORY=/srv/data-local/chroma
RUN mkdir -p /srv/data-local

# Run as an unprivileged user; the volume must stay writable for SQLite.
RUN useradd --create-home --uid 10001 trigger && chown -R trigger /srv
USER trigger

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status < 500 else 1)"

ENTRYPOINT ["backend-entrypoint"]
CMD ["uvicorn", "app.api.main:build", "--factory", "--host", "0.0.0.0", "--port", "8000"]
