"""sales CRM: prospects, their activity timeline and follow-up tasks

Schema only. Existing history is turned into prospects by `python -m app.cli backfill-prospects`
(idempotent), so this migration stays independent of application code.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-25 16:23:31.937355+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = '0011'
down_revision: str | None = '0010'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table('prospects',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('stage', sa.Enum('new', 'contacted', 'engaged', 'conversation', 'claimed', 'won', 'lost', 'do_not_contact', name='prospectstage', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=True),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('score_reasons', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('last_touch_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('stage_changed_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('lost_reason', sa.Text(), nullable=True),
    sa.Column('cooldown_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('score IS NULL OR (score >= 0 AND score <= 100)', name=op.f('ck_prospects_score_range')),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_prospects_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name=op.f('fk_prospects_owner_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prospects')),
    sa.UniqueConstraint('business_id', name=op.f('uq_prospects_business_id'))
    )
    with op.batch_alter_table('prospects', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_prospects_owner_user_id'), ['owner_user_id'], unique=False)
        batch_op.create_index('ix_prospects_stage_last_touch_at', ['stage', 'last_touch_at'], unique=False)

    op.create_table('prospect_activities',
    sa.Column('prospect_id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.Enum('site_published', 'email_sent', 'email_opened', 'link_clicked', 'unsubscribed', 'claim_started', 'claim_approved', 'claim_rejected', 'subscribed', 'churned', 'suppressed', 'call', 'note', 'stage_changed', 'assigned', 'task_done', name='activitytype', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('source', sa.Enum('system', 'manual', 'dialer', name='activitysource', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('external_id', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name=op.f('fk_prospect_activities_actor_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['prospect_id'], ['prospects.id'], name=op.f('fk_prospect_activities_prospect_id_prospects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prospect_activities')),
    sa.UniqueConstraint('external_id', name=op.f('uq_prospect_activities_external_id'))
    )
    with op.batch_alter_table('prospect_activities', schema=None) as batch_op:
        batch_op.create_index('ix_prospect_activities_prospect_id_occurred_at', ['prospect_id', 'occurred_at'], unique=False)

    op.create_table('prospect_tasks',
    sa.Column('prospect_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('assignee_user_id', sa.Uuid(), nullable=True),
    sa.Column('done_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['assignee_user_id'], ['users.id'], name=op.f('fk_prospect_tasks_assignee_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_prospect_tasks_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['prospect_id'], ['prospects.id'], name=op.f('fk_prospect_tasks_prospect_id_prospects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prospect_tasks'))
    )
    with op.batch_alter_table('prospect_tasks', schema=None) as batch_op:
        batch_op.create_index('ix_prospect_tasks_assignee_user_id_done_at_due_at', ['assignee_user_id', 'done_at', 'due_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_prospect_tasks_prospect_id'), ['prospect_id'], unique=False)




def downgrade() -> None:

    with op.batch_alter_table('prospect_tasks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_prospect_tasks_prospect_id'))
        batch_op.drop_index('ix_prospect_tasks_assignee_user_id_done_at_due_at')

    op.drop_table('prospect_tasks')
    with op.batch_alter_table('prospect_activities', schema=None) as batch_op:
        batch_op.drop_index('ix_prospect_activities_prospect_id_occurred_at')

    op.drop_table('prospect_activities')
    with op.batch_alter_table('prospects', schema=None) as batch_op:
        batch_op.drop_index('ix_prospects_stage_last_touch_at')
        batch_op.drop_index(batch_op.f('ix_prospects_owner_user_id'))

    op.drop_table('prospects')

