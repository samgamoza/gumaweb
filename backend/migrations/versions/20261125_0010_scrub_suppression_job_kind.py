"""scrub_suppression job kind (retroactive suppression scrub)

Enum values live in a named CHECK constraint (ADR-4); autogenerate can't see value changes, so the constraint
is rewritten by hand. Downgrade deletes queued scrub jobs.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-25 10:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_JOB_KINDS = ("generate_website", "regenerate_website", "publish_website", "run_automation", "deliver_webhook",
                 "summarize_call", "generate_presence", "check_domains", "discover_businesses", "enrich_business",
                 "run_campaign")
NEW_JOB_KINDS = OLD_JOB_KINDS + ("scrub_suppression",)


def _set_job_kinds(values: tuple[str, ...]) -> None:
    condition = "kind IN (" + ", ".join(f"'{v}'" for v in values) + ")"
    recreate = "always" if op.get_bind().dialect.name == "sqlite" else "auto"  # SQLite: copy-and-move
    with op.batch_alter_table("factory_jobs", recreate=recreate) as batch:
        batch.drop_constraint(op.f("ck_factory_jobs_jobkind"), type_="check")
        batch.create_check_constraint("jobkind", condition)


def upgrade() -> None:
    _set_job_kinds(NEW_JOB_KINDS)


def downgrade() -> None:
    op.execute("DELETE FROM factory_jobs WHERE kind = 'scrub_suppression'")
    _set_job_kinds(OLD_JOB_KINDS)
