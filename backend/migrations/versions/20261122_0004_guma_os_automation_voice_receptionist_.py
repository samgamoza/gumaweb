"""guma os: automation, voice receptionist, api keys, webhooks, lead scores

contacts.score_reasons gets a server default so the upgrade works on populated databases.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-22 09:40:47.668517+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_JOB_KINDS = ("generate_website", "regenerate_website", "publish_website")
NEW_JOB_KINDS = OLD_JOB_KINDS + ("run_automation", "deliver_webhook", "summarize_call")


def _set_job_kinds(values: tuple[str, ...]) -> None:
    """Enum values live in a named CHECK constraint (ADR-4); autogenerate can't see value changes."""
    condition = "kind IN (" + ", ".join(f"'{v}'" for v in values) + ")"
    recreate = "always" if op.get_bind().dialect.name == "sqlite" else "auto"  # SQLite: copy-and-move
    with op.batch_alter_table("factory_jobs", recreate=recreate) as batch:
        batch.drop_constraint(op.f("ck_factory_jobs_jobkind"), type_="check")
        batch.create_check_constraint("jobkind", condition)


def upgrade() -> None:
    op.create_table('api_keys',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('prefix', sa.String(length=16), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('read_only', sa.Boolean(), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_api_keys_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_api_keys_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_api_keys')),
    sa.UniqueConstraint('key_hash', name=op.f('uq_api_keys_key_hash'))
    )
    op.create_index(op.f('ix_api_keys_business_id'), 'api_keys', ['business_id'], unique=False)
    op.create_table('automation_rules',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('trigger', sa.Enum('lead_captured', 'lead_became_hot', 'stage_changed', 'appointment_booked', 'appointment_cancelled', 'appointment_reminder', 'contact_idle', 'call_completed', name='trigger', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('config', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('conditions', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('actions', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('preset_key', sa.String(length=64), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_automation_rules_business_id_businesses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_automation_rules'))
    )
    op.create_index('ix_automation_rules_business_trigger', 'automation_rules', ['business_id', 'trigger', 'enabled'], unique=False)
    op.create_table('voice_settings',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('phone_number', sa.String(length=32), nullable=True),
    sa.Column('forward_number', sa.String(length=32), nullable=True),
    sa.Column('take_messages', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_voice_settings_business_id_businesses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('business_id', name=op.f('pk_voice_settings')),
    sa.UniqueConstraint('phone_number', name=op.f('uq_voice_settings_phone_number'))
    )
    op.create_table('webhook_endpoints',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('url', sa.String(length=500), nullable=False),
    sa.Column('events', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('secret_version', sa.Integer(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('consecutive_failures', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_webhook_endpoints_business_id_businesses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_webhook_endpoints'))
    )
    op.create_index(op.f('ix_webhook_endpoints_business_id'), 'webhook_endpoints', ['business_id'], unique=False)
    op.create_table('automation_runs',
    sa.Column('rule_id', sa.Uuid(), nullable=False),
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=200), nullable=False),
    sa.Column('subject_type', sa.String(length=32), nullable=False),
    sa.Column('subject_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('results', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_automation_runs_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rule_id'], ['automation_rules.id'], name=op.f('fk_automation_runs_rule_id_automation_rules'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_automation_runs')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_automation_runs_idempotency_key'))
    )
    op.create_index(op.f('ix_automation_runs_business_id'), 'automation_runs', ['business_id'], unique=False)
    op.create_index(op.f('ix_automation_runs_created_at'), 'automation_runs', ['created_at'], unique=False)
    op.create_index(op.f('ix_automation_runs_rule_id'), 'automation_runs', ['rule_id'], unique=False)
    op.create_table('webhook_deliveries',
    sa.Column('endpoint_id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('response_status', sa.Integer(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['endpoint_id'], ['webhook_endpoints.id'], name=op.f('fk_webhook_deliveries_endpoint_id_webhook_endpoints'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_webhook_deliveries'))
    )
    op.create_index(op.f('ix_webhook_deliveries_created_at'), 'webhook_deliveries', ['created_at'], unique=False)
    op.create_index(op.f('ix_webhook_deliveries_endpoint_id'), 'webhook_deliveries', ['endpoint_id'], unique=False)
    op.create_table('calls',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('caller_number', sa.String(length=32), nullable=True),
    sa.Column('is_test', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('state', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('transcript', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('outcome', sa.String(length=16), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('contact_id', sa.Uuid(), nullable=True),
    sa.Column('appointment_id', sa.Uuid(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duration_seconds', sa.Integer(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], name=op.f('fk_calls_appointment_id_appointments'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_calls_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_calls_contact_id_contacts'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_calls'))
    )
    op.create_index('ix_calls_business_started', 'calls', ['business_id', 'started_at'], unique=False)
    op.add_column('contacts', sa.Column('lead_score', sa.Integer(), nullable=True))
    op.add_column('contacts', sa.Column('lead_temperature', sa.String(length=16), nullable=True))
    op.add_column('contacts', sa.Column('score_reasons', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), server_default='[]', nullable=False))
    op.create_index(op.f('ix_contacts_lead_score'), 'contacts', ['lead_score'], unique=False)

    _set_job_kinds(NEW_JOB_KINDS)


def downgrade() -> None:
    op.execute("DELETE FROM factory_jobs WHERE kind IN ('run_automation', 'deliver_webhook', 'summarize_call')")
    _set_job_kinds(OLD_JOB_KINDS)
    op.drop_index(op.f('ix_contacts_lead_score'), table_name='contacts')
    op.drop_column('contacts', 'score_reasons')
    op.drop_column('contacts', 'lead_temperature')
    op.drop_column('contacts', 'lead_score')
    op.drop_index('ix_calls_business_started', table_name='calls')
    op.drop_table('calls')
    op.drop_index(op.f('ix_webhook_deliveries_endpoint_id'), table_name='webhook_deliveries')
    op.drop_index(op.f('ix_webhook_deliveries_created_at'), table_name='webhook_deliveries')
    op.drop_table('webhook_deliveries')
    op.drop_index(op.f('ix_automation_runs_rule_id'), table_name='automation_runs')
    op.drop_index(op.f('ix_automation_runs_created_at'), table_name='automation_runs')
    op.drop_index(op.f('ix_automation_runs_business_id'), table_name='automation_runs')
    op.drop_table('automation_runs')
    op.drop_index(op.f('ix_webhook_endpoints_business_id'), table_name='webhook_endpoints')
    op.drop_table('webhook_endpoints')
    op.drop_table('voice_settings')
    op.drop_index('ix_automation_rules_business_trigger', table_name='automation_rules')
    op.drop_table('automation_rules')
    op.drop_index(op.f('ix_api_keys_business_id'), table_name='api_keys')
    op.drop_table('api_keys')
