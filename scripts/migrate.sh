#!/usr/bin/env bash
# Apply migrations and idempotent seed data. Pass --demo for fictional demo businesses.
set -euo pipefail
cd "$(dirname "$0")/../backend"
PY=".venv/bin/python"; [ -x "$PY" ] || PY=".venv/Scripts/python"
"$PY" -m alembic upgrade head
"$PY" -m app.cli seed "$@"
