#!/usr/bin/env bash
# One-time local setup without Docker: backend venv + frontend deps.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Backend (Python 3.12+)"
cd "$ROOT/backend"
python -m venv .venv
if [ -f .venv/Scripts/activate ]; then source .venv/Scripts/activate; else source .venv/bin/activate; fi
pip install -q --upgrade pip
pip install -q -r requirements/dev.txt

echo "==> Frontend (pnpm)"
cd "$ROOT/frontend"
pnpm install

[ -f "$ROOT/.env" ] || cp "$ROOT/.env.example" "$ROOT/.env"
echo "Done. Start data services with: docker compose up -d postgres redis mailpit"
echo "Then: scripts/migrate.sh && (cd backend && uvicorn app.main:app --reload)"
