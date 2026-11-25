"""provider usage ledger and enrich job kind

* `provider_usage`: one row per billable call to a paid data API (Hunter.io), with units and cost.
* `enrich_business` job kind (enum values live in a named CHECK constraint, ADR-4; autogenerate can't
  see value changes, so the constraint is rewritten by hand).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-25 08:25:27.615748+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0008'
down_revision: str | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_JOB_KINDS = ("generate_website", "regenerate_website", "publish_website", "run_automation", "deliver_webhook",
                 "summarize_call", "generate_presence", "check_domains", "discover_businesses")
NEW_JOB_KINDS = OLD_JOB_KINDS + ("enrich_business",)


def _set_job_kinds(values: tuple[str, ...]) -> None:
    condition = "kind IN (" + ", ".join(f"'{v}'" for v in values) + ")"
    recreate = "always" if op.get_bind().dialect.name == "sqlite" else "auto"  # SQLite: copy-and-move
    with op.batch_alter_table("factory_jobs", recreate=recreate) as batch:
        batch.drop_constraint(op.f("ck_factory_jobs_jobkind"), type_="check")
        batch.create_check_constraint("jobkind", condition)


def upgrade() -> None:
    op.create_table('provider_usage',
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('operation', sa.String(length=64), nullable=False),
    sa.Column('units', sa.Integer(), nullable=False),
    sa.Column('cost_micros', sa.BigInteger(), nullable=False),
    sa.Column('business_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_provider_usage_business_id_businesses'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_provider_usage'))
    )
    with op.batch_alter_table('provider_usage', schema=None) as batch_op:
        batch_op.create_index('ix_provider_usage_provider_created_at', ['provider', 'created_at'], unique=False)

    _set_job_kinds(NEW_JOB_KINDS)


def downgrade() -> None:
    op.execute("DELETE FROM factory_jobs WHERE kind = 'enrich_business'")
    _set_job_kinds(OLD_JOB_KINDS)
    with op.batch_alter_table('provider_usage', schema=None) as batch_op:
        batch_op.drop_index('ix_provider_usage_provider_created_at')

    op.drop_table('provider_usage')
