#!/bin/sh
# Prepare persistent demo state, then hand off to the server.
#
# Initialization is idempotent so a restart reuses the mounted volume rather
# than rebuilding it, and a missing API key degrades the demo instead of
# stopping startup.
set -eu

DATA_DIR="${TEST_TRIGGER_DATA_DIR:-/srv/data-local}"
mkdir -p "$DATA_DIR"

python - <<'PY'
from app.config import AppSettings
from app.db.database import Database

settings = AppSettings.from_environment()
Database(settings.database_path).initialize()
print(f"SQLite ready at {settings.database_path}")
PY

if [ -n "${OPENAI_API_KEY:-}" ]; then
  if [ -f "$DATA_DIR/.ingested" ]; then
    echo "Knowledge base already ingested; skipping."
  else
    echo "Ingesting knowledge base..."
    if python scripts/ingest_knowledge_base.py; then
      touch "$DATA_DIR/.ingested"
    else
      echo "WARNING: ingestion failed. Retrieval will return no evidence." >&2
    fi
  fi
else
  echo "NOTICE: OPENAI_API_KEY is not set."
  echo "  Intent extraction and AI analysis are disabled; the deterministic"
  echo "  core still runs and /health reports which features are off."
fi

exec "$@"
