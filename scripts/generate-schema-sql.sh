#!/usr/bin/env bash
# Regenerate database/schema/schema.sql (PostgreSQL DDL) from the Alembic migrations, offline.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
PY=".venv/bin/python"; [ -x "$PY" ] || PY=".venv/Scripts/python"
DATABASE_URL="postgresql+psycopg://gumaweb@localhost/gumaweb" \
  "$PY" -m alembic upgrade head --sql > "$ROOT/database/schema/schema.sql"
echo "wrote database/schema/schema.sql"
