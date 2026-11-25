"""outbound engine playbooks: playbooks, playbook_enrollments, and the run_outbound job kind (A2)

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-25 18:55:35.130971+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = '0013'
down_revision: str | None = '0012'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_JOB_KINDS = ("generate_website", "regenerate_website", "publish_website", "run_automation", "deliver_webhook",
                 "summarize_call", "generate_presence", "check_domains", "discover_businesses", "enrich_business",
                 "run_campaign", "scrub_suppression")
NEW_JOB_KINDS = OLD_JOB_KINDS + ("run_outbound",)


def _set_job_kinds(values: tuple[str, ...]) -> None:
    """Enum values live in a named CHECK constraint (ADR-4): rewrite it by hand."""
    condition = "kind IN (" + ", ".join(f"'{v}'" for v in values) + ")"
    recreate = "always" if op.get_bind().dialect.name == "sqlite" else "auto"
    with op.batch_alter_table("factory_jobs", recreate=recreate) as batch:
        batch.drop_constraint(op.f("ck_factory_jobs_jobkind"), type_="check")
        batch.create_check_constraint("jobkind", condition)


def upgrade() -> None:
    op.create_table('playbooks',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('steps', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('max_days', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('max_days >= 1 AND max_days <= 180', name=op.f('ck_playbooks_max_days_range')),
    sa.ForeignKeyConstraint(['campaign_id'], ['outreach_campaigns.id'], name=op.f('fk_playbooks_campaign_id_outreach_campaigns'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_playbooks')),
    sa.UniqueConstraint('name', name=op.f('uq_playbooks_name'))
    )
    op.create_table('playbook_enrollments',
    sa.Column('playbook_id', sa.Uuid(), nullable=False),
    sa.Column('prospect_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('active', 'completed', 'stopped', name='enrollmentstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('enrolled_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('steps_done', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('stop_reason', sa.String(length=64), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['playbook_id'], ['playbooks.id'], name=op.f('fk_playbook_enrollments_playbook_id_playbooks'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['prospect_id'], ['prospects.id'], name=op.f('fk_playbook_enrollments_prospect_id_prospects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_playbook_enrollments')),
    sa.UniqueConstraint('playbook_id', 'prospect_id', name=op.f('uq_playbook_enrollments_playbook_id_prospect_id'))
    )
    with op.batch_alter_table('playbook_enrollments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_playbook_enrollments_prospect_id'), ['prospect_id'], unique=False)
        batch_op.create_index('ix_playbook_enrollments_status_playbook_id', ['status', 'playbook_id'], unique=False)
    _set_job_kinds(NEW_JOB_KINDS)


def downgrade() -> None:
    op.execute("DELETE FROM factory_jobs WHERE kind = 'run_outbound'")
    _set_job_kinds(OLD_JOB_KINDS)
    with op.batch_alter_table('playbook_enrollments', schema=None) as batch_op:
        batch_op.drop_index('ix_playbook_enrollments_status_playbook_id')
        batch_op.drop_index(batch_op.f('ix_playbook_enrollments_prospect_id'))

    op.drop_table('playbook_enrollments')
    op.drop_table('playbooks')
