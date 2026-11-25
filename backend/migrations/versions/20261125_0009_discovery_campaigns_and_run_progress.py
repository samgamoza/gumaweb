"""discovery campaigns and run progress

* `discovery_campaigns`: saved sweeps (cities x categories x sources, target, enrichment tiers).
* `discovery_runs` gains `campaign_id`, `progress` (live counters) and `cancel_requested`; existing rows get
  `{}` / false through server defaults.
* Run statuses gain `queued` and `cancelled`; job kinds gain `run_campaign` (named CHECK constraints, ADR-4,
  rewritten by hand since autogenerate can't see enum value changes).

Downgrade is lossy by necessity: queued/cancelled runs become failed, run_campaign jobs are deleted.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-25 08:43:49.243760+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = '0009'
down_revision: str | None = '0008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_RUN_STATUSES = ("running", "completed", "failed")
NEW_RUN_STATUSES = ("queued", "running", "completed", "failed", "cancelled")
OLD_JOB_KINDS = ("generate_website", "regenerate_website", "publish_website", "run_automation", "deliver_webhook",
                 "summarize_call", "generate_presence", "check_domains", "discover_businesses", "enrich_business")
NEW_JOB_KINDS = OLD_JOB_KINDS + ("run_campaign",)


def _set_check(table: str, column: str, constraint: str, values: tuple[str, ...]) -> None:
    condition = f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"
    recreate = "always" if op.get_bind().dialect.name == "sqlite" else "auto"  # SQLite: copy-and-move
    with op.batch_alter_table(table, recreate=recreate) as batch:
        batch.drop_constraint(op.f(f"ck_{table}_{constraint}"), type_="check")
        batch.create_check_constraint(constraint, condition)


def upgrade() -> None:
    op.create_table('discovery_campaigns',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('cities', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('categories', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('sources', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('enrichment_tiers', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=True),
    sa.Column('target', sa.Integer(), nullable=False),
    sa.Column('per_query', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('per_query >= 1 AND per_query <= 500', name=op.f('ck_discovery_campaigns_per_query_range')),
    sa.CheckConstraint('target >= 1 AND target <= 5000', name=op.f('ck_discovery_campaigns_target_range')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_discovery_campaigns_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_discovery_campaigns'))
    )
    with op.batch_alter_table('discovery_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('campaign_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('progress', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'),
                                      server_default=sa.text("'{}'"), nullable=False))
        batch_op.add_column(sa.Column('cancel_requested', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.create_index(batch_op.f('ix_discovery_runs_campaign_id'), ['campaign_id'], unique=False)
        batch_op.create_foreign_key(batch_op.f('fk_discovery_runs_campaign_id_discovery_campaigns'), 'discovery_campaigns', ['campaign_id'], ['id'], ondelete='SET NULL')

    _set_check("discovery_runs", "status", "discoveryrunstatus", NEW_RUN_STATUSES)
    _set_check("factory_jobs", "kind", "jobkind", NEW_JOB_KINDS)


def downgrade() -> None:
    op.execute("DELETE FROM factory_jobs WHERE kind = 'run_campaign'")
    op.execute("UPDATE discovery_runs SET status = 'failed' WHERE status IN ('queued', 'cancelled')")
    _set_check("factory_jobs", "kind", "jobkind", OLD_JOB_KINDS)
    _set_check("discovery_runs", "status", "discoveryrunstatus", OLD_RUN_STATUSES)
    with op.batch_alter_table('discovery_runs', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_discovery_runs_campaign_id_discovery_campaigns'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_discovery_runs_campaign_id'))
        batch_op.drop_column('cancel_requested')
        batch_op.drop_column('progress')
        batch_op.drop_column('campaign_id')

    op.drop_table('discovery_campaigns')
