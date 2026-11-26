"""claim links: private claim links that open a draft preview, owner answers waiting for verification (A7)

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-26 04:46:37.821086+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = '0014'
down_revision: str | None = '0013'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('claim_links',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('website_id', sa.Uuid(), nullable=False),
    sa.Column('message_id', sa.Uuid(), nullable=True),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('first_opened_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_opened_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('open_count', sa.Integer(), nullable=False),
    sa.Column('form_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('answers', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_claim_links_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['message_id'], ['outreach_messages.id'], name=op.f('fk_claim_links_message_id_outreach_messages'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['website_id'], ['websites.id'], name=op.f('fk_claim_links_website_id_websites'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_claim_links')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_claim_links_token_hash'))
    )
    with op.batch_alter_table('claim_links', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_claim_links_business_id'), ['business_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('claim_links', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_claim_links_business_id'))

    op.drop_table('claim_links')
