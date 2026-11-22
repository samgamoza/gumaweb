"""digital presence: presence kits, custom domains, business email

Also adds the generate_presence and check_domains job kinds.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-22 12:10:12.947065+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_JOB_KINDS = ("generate_website", "regenerate_website", "publish_website", "run_automation", "deliver_webhook",
                 "summarize_call")
NEW_JOB_KINDS = OLD_JOB_KINDS + ("generate_presence", "check_domains")


def _set_job_kinds(values: tuple[str, ...]) -> None:
    """Enum values live in a named CHECK constraint (ADR-4); autogenerate can't see value changes."""
    condition = "kind IN (" + ", ".join(f"'{v}'" for v in values) + ")"
    recreate = "always" if op.get_bind().dialect.name == "sqlite" else "auto"  # SQLite: copy-and-move
    with op.batch_alter_table("factory_jobs", recreate=recreate) as batch:
        batch.drop_constraint(op.f("ck_factory_jobs_jobkind"), type_="check")
        batch.create_check_constraint("jobkind", condition)


def upgrade() -> None:
    op.create_table('custom_domains',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('domain', sa.String(length=253), nullable=False),
    sa.Column('status', sa.Enum('pending', 'verified', 'failed', name='domainstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('verification_token', sa.String(length=64), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.String(length=500), nullable=True),
    sa.Column('serve_website', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_custom_domains_business_id_businesses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_custom_domains')),
    sa.UniqueConstraint('domain', name=op.f('uq_custom_domains_domain'))
    )
    with op.batch_alter_table('custom_domains', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_custom_domains_business_id'), ['business_id'], unique=False)

    op.create_table('presence_kits',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('website_version', sa.Integer(), nullable=True),
    sa.Column('brand', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('social', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('google', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('seo', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('rendered', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('checklist', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_presence_kits_business_id_businesses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_presence_kits')),
    sa.UniqueConstraint('business_id', name=op.f('uq_presence_kits_business_id'))
    )
    op.create_table('mail_domains',
    sa.Column('domain_id', sa.Uuid(), nullable=False),
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('dkim_selector', sa.String(length=32), nullable=False),
    sa.Column('dkim_private_key', sa.Text(), nullable=False),
    sa.Column('dkim_public_key', sa.Text(), nullable=False),
    sa.Column('provider_status', sa.String(length=16), nullable=False),
    sa.Column('provider_error', sa.String(length=500), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_mail_domains_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['domain_id'], ['custom_domains.id'], name=op.f('fk_mail_domains_domain_id_custom_domains'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mail_domains')),
    sa.UniqueConstraint('domain_id', name=op.f('uq_mail_domains_domain_id'))
    )
    with op.batch_alter_table('mail_domains', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_mail_domains_business_id'), ['business_id'], unique=False)

    op.create_table('mailboxes',
    sa.Column('mail_domain_id', sa.Uuid(), nullable=False),
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('local_part', sa.String(length=64), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=True),
    sa.Column('kind', sa.Enum('mailbox', 'forward', name='mailboxkind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('forward_to', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('quota_mb', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_mailboxes_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['mail_domain_id'], ['mail_domains.id'], name=op.f('fk_mailboxes_mail_domain_id_mail_domains'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mailboxes')),
    sa.UniqueConstraint('mail_domain_id', 'local_part', name='uq_mailboxes_domain_local_part')
    )
    with op.batch_alter_table('mailboxes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_mailboxes_business_id'), ['business_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mailboxes_mail_domain_id'), ['mail_domain_id'], unique=False)

    _set_job_kinds(NEW_JOB_KINDS)


def downgrade() -> None:
    op.execute("DELETE FROM factory_jobs WHERE kind IN ('generate_presence', 'check_domains')")
    _set_job_kinds(OLD_JOB_KINDS)
    with op.batch_alter_table('mailboxes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_mailboxes_mail_domain_id'))
        batch_op.drop_index(batch_op.f('ix_mailboxes_business_id'))

    op.drop_table('mailboxes')
    with op.batch_alter_table('mail_domains', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_mail_domains_business_id'))

    op.drop_table('mail_domains')
    op.drop_table('presence_kits')
    with op.batch_alter_table('custom_domains', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_custom_domains_business_id'))

    op.drop_table('custom_domains')
