"""contact provenance and domain suppressions

* New `business_contacts`: every email/phone/owner learned about a business, with its provenance.
* `outreach_suppressions` goes from one `email` column to (`kind`, `value`): a suppression is now an email
  or a whole domain. Existing rows become kind='email' with the address normalized (trimmed, lowercased);
  rows that collide after normalizing are merged, keeping the oldest. Also adds `note` and `created_by`.

Downgrade is lossy by necessity: domain suppressions have no place in the old schema and are dropped.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-25 06:36:08.322368+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('business_contacts',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Enum('email', 'phone', 'owner', name='contactkind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('value', sa.String(length=320), nullable=False),
    sa.Column('source', sa.String(length=64), nullable=False),
    sa.Column('source_ref', sa.String(length=500), nullable=True),
    sa.Column('value_type', sa.Enum('observed', 'derived', 'predicted', 'user_supplied', name='valuetype', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('verification_status', sa.Enum('unverified', 'verified', 'invalid', name='verificationstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('purpose', sa.Enum('lead_qualification', 'contact_enrichment', 'compliance_check', 'technical_verification', name='contactpurpose', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('policy_decision', sa.Enum('allow', 'redacted', 'blocked', name='policydecision', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('reason_code', sa.String(length=64), nullable=True),
    sa.Column('acquired_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('retention_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('discovery_run_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name=op.f('ck_business_contacts_confidence_range')),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_business_contacts_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['discovery_run_id'], ['discovery_runs.id'], name=op.f('fk_business_contacts_discovery_run_id_discovery_runs'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_business_contacts')),
    sa.UniqueConstraint('business_id', 'kind', 'value', name=op.f('uq_business_contacts_business_id_kind_value'))
    )
    with op.batch_alter_table('business_contacts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_business_contacts_business_id'), ['business_id'], unique=False)
        batch_op.create_index('ix_business_contacts_kind_value', ['kind', 'value'], unique=False)

    _upgrade_suppressions()


def _upgrade_suppressions() -> None:
    kind_type = sa.Enum('email', 'domain', name='suppressionkind', native_enum=False, create_constraint=True,
                        length=32)
    # 1. New columns, nullable so existing rows survive until backfilled.
    with op.batch_alter_table('outreach_suppressions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kind', kind_type, nullable=True))
        batch_op.add_column(sa.Column('value', sa.String(length=320), nullable=True))
        batch_op.add_column(sa.Column('note', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('created_by', sa.Uuid(), nullable=True))

    # 2. Backfill: normalize each address; merge rows that collide after normalizing (keep the oldest).
    bind = op.get_bind()
    table = sa.table('outreach_suppressions', sa.column('id', sa.Uuid()), sa.column('email', sa.String()),
                     sa.column('created_at', sa.DateTime(timezone=True)), sa.column('kind', sa.String()),
                     sa.column('value', sa.String()))
    rows = bind.execute(sa.select(table.c.id, table.c.email).order_by(table.c.created_at, table.c.id)).all()
    seen: set[str] = set()
    for row_id, email in rows:
        value = (email or '').strip().lower()
        if not value or value in seen:
            bind.execute(sa.delete(table).where(table.c.id == row_id))
            continue
        seen.add(value)
        bind.execute(sa.update(table).where(table.c.id == row_id).values(kind='email', value=value))

    # 3. Tighten: NOT NULL, swap the unique constraint, drop the old column.
    with op.batch_alter_table('outreach_suppressions', schema=None) as batch_op:
        batch_op.alter_column('kind', existing_type=kind_type, nullable=False)
        batch_op.alter_column('value', existing_type=sa.String(length=320), nullable=False)
        batch_op.drop_constraint(batch_op.f('uq_outreach_suppressions_email'), type_='unique')
        batch_op.create_unique_constraint(batch_op.f('uq_outreach_suppressions_kind_value'), ['kind', 'value'])
        batch_op.create_foreign_key(batch_op.f('fk_outreach_suppressions_created_by_users'), 'users', ['created_by'],
                                    ['id'], ondelete='SET NULL')
        batch_op.drop_column('email')


def downgrade() -> None:
    bind = op.get_bind()
    table = sa.table('outreach_suppressions', sa.column('kind', sa.String()), sa.column('value', sa.String()),
                     sa.column('email', sa.String()))
    bind.execute(sa.delete(table).where(table.c.kind != 'email'))  # lossy: no domain rows in the old schema
    with op.batch_alter_table('outreach_suppressions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email', sa.VARCHAR(length=320), nullable=True))
    bind.execute(sa.update(table).values(email=table.c.value))
    with op.batch_alter_table('outreach_suppressions', schema=None) as batch_op:
        batch_op.alter_column('email', existing_type=sa.VARCHAR(length=320), nullable=False)
        batch_op.drop_constraint(batch_op.f('fk_outreach_suppressions_created_by_users'), type_='foreignkey')
        batch_op.drop_constraint(batch_op.f('uq_outreach_suppressions_kind_value'), type_='unique')
        batch_op.create_unique_constraint(batch_op.f('uq_outreach_suppressions_email'), ['email'])
        # SQLite's copy-and-move keeps a CHECK that names a dropped column, so drop it explicitly first.
        batch_op.drop_constraint(batch_op.f('ck_outreach_suppressions_suppressionkind'), type_='check')
        batch_op.drop_column('created_by')
        batch_op.drop_column('note')
        batch_op.drop_column('value')
        batch_op.drop_column('kind')

    with op.batch_alter_table('business_contacts', schema=None) as batch_op:
        batch_op.drop_index('ix_business_contacts_kind_value')
        batch_op.drop_index(batch_op.f('ix_business_contacts_business_id'))

    op.drop_table('business_contacts')
