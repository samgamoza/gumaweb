# database/

| Path | What it is |
|---|---|
| `schema/schema.sql` | PostgreSQL DDL rendered **from the Alembic migrations** (`scripts/generate-schema-sql.sh`). Reference only. Never edit it by hand or apply it directly. |
| `seeds/sample_businesses.csv` | Fictional businesses for the admin **Import CSV** button or `POST /api/v1/businesses/import`. |

The source of truth for the schema is `backend/app/models/` (SQLAlchemy). Changes ship as Alembic
revisions in `backend/migrations/versions/`. Reference data (plans, templates, the first admin) is seeded
idempotently by `python -m app.cli seed`. See [docs/DATABASE_DESIGN.md](../docs/DATABASE_DESIGN.md).
