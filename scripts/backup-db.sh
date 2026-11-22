#!/usr/bin/env bash
# Logical backup of the GumaWeb database (daily backups, 19-security-compliance).
# Production should rely on CloudNativePG continuous archiving (RPO 1h); this covers ad-hoc/dev use.
#   DATABASE_URL=postgresql://gumaweb:...@host:5432/gumaweb scripts/backup-db.sh /backups
set -euo pipefail
OUT_DIR="${1:-./backups}"
URL="${DATABASE_URL:?set DATABASE_URL}"
URL="${URL/postgresql+psycopg:/postgresql:}"
mkdir -p "$OUT_DIR"
FILE="$OUT_DIR/gumaweb-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_dump --format=custom --no-owner "$URL" > "$FILE"
echo "backup written to $FILE"
