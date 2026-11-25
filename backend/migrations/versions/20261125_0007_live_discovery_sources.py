"""live discovery sources: osm and fixture discovery sources, discover_businesses job kind

Enum values live in named CHECK constraints (ADR-4); autogenerate can't see value changes, so this
migration rewrites them by hand.

Downgrade is lossy by necessity: businesses and runs labelled `osm` or `fixture` are relabelled `manual`
(their `source_ref` keeps the provider id, e.g. "osm:node/123"), and queued discovery jobs are deleted.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-25 09:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SOURCES = ("manual", "csv_import", "dti", "chamber", "yellow_pages", "google_business", "facebook", "sec")
NEW_SOURCES = OLD_SOURCES + ("osm", "fixture")
OLD_JOB_KINDS = ("generate_website", "regenerate_website", "publish_website", "run_automation", "deliver_webhook",
                 "summarize_call", "generate_presence", "check_domains")
NEW_JOB_KINDS = OLD_JOB_KINDS + ("discover_businesses",)


def _set_check(table: str, column: str, constraint: str, values: tuple[str, ...]) -> None:
    condition = f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"
    recreate = "always" if op.get_bind().dialect.name == "sqlite" else "auto"  # SQLite: copy-and-move
    with op.batch_alter_table(table, recreate=recreate) as batch:
        batch.drop_constraint(op.f(f"ck_{table}_{constraint}"), type_="check")
        batch.create_check_constraint(constraint, condition)


def upgrade() -> None:
    _set_check("businesses", "source", "discoverysource", NEW_SOURCES)
    _set_check("discovery_runs", "source", "discoverysource", NEW_SOURCES)
    _set_check("factory_jobs", "kind", "jobkind", NEW_JOB_KINDS)


def downgrade() -> None:
    op.execute("DELETE FROM factory_jobs WHERE kind = 'discover_businesses'")
    op.execute("UPDATE businesses SET source = 'manual' WHERE source IN ('osm', 'fixture')")
    op.execute("UPDATE discovery_runs SET source = 'manual' WHERE source IN ('osm', 'fixture')")
    _set_check("factory_jobs", "kind", "jobkind", OLD_JOB_KINDS)
    _set_check("discovery_runs", "source", "discoverysource", OLD_SOURCES)
    _set_check("businesses", "source", "discoverysource", OLD_SOURCES)
