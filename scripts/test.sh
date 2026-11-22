#!/usr/bin/env bash
# Full quality gate: backend lint + tests + migration drift check, frontend typecheck + build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
PY=".venv/bin/python"; [ -x "$PY" ] || PY=".venv/Scripts/python"

echo "==> ruff";   "$PY" -m ruff check app tests
echo "==> pytest (SQLite)"; env -u TEST_DATABASE_URL "$PY" -m pytest -q -o addopts=""
if [ -n "${TEST_DATABASE_URL:-}" ]; then
  # e.g. TEST_DATABASE_URL=postgresql+psycopg://gumaweb:gumaweb@localhost:5432/gumaweb_test (disposable DB)
  echo "==> pytest (PostgreSQL)"; "$PY" -m pytest -q -o addopts=""
fi

echo "==> migration drift check (fresh SQLite)"
TMP_DB="$(mktemp -d)/drift.db"
command -v cygpath >/dev/null && TMP_DB="$(cygpath -m "$TMP_DB")"  # Git Bash on Windows
DATABASE_URL="sqlite:///$TMP_DB" "$PY" -m alembic upgrade head >/dev/null
DATABASE_URL="sqlite:///$TMP_DB" "$PY" -m alembic check

echo "==> frontend"
cd "$ROOT/frontend"
node node_modules/typescript/bin/tsc --noEmit
NEXT_TELEMETRY_DISABLED=1 node node_modules/next/dist/bin/next build
