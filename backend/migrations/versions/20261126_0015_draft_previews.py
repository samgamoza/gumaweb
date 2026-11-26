"""draft previews: polish review + preview images of private drafts, and the prepare_draft job kind (A7b)

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-26 05:26:30.104911+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = '0015'
down_revision: str | None = '0014'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_JOB_KINDS = ("generate_website", "regenerate_website", "publish_website", "run_automation", "deliver_webhook",
                 "summarize_call", "generate_presence", "check_domains", "discover_businesses", "enrich_business",
                 "run_campaign", "scrub_suppression", "run_outbound")
NEW_JOB_KINDS = OLD_JOB_KINDS + ("prepare_draft",)


def _set_job_kinds(values: tuple[str, ...]) -> None:
    """Enum values live in a named CHECK constraint (ADR-4): rewrite it by hand."""
    condition = "kind IN (" + ", ".join(f"'{v}'" for v in values) + ")"
    recreate = "always" if op.get_bind().dialect.name == "sqlite" else "auto"
    with op.batch_alter_table("factory_jobs", recreate=recreate) as batch:
        batch.drop_constraint(op.f("ck_factory_jobs_jobkind"), type_="check")
        batch.create_check_constraint("jobkind", condition)


def upgrade() -> None:
    op.create_table('draft_previews',
    sa.Column('website_id', sa.Uuid(), nullable=False),
    sa.Column('ready', sa.Boolean(), nullable=False),
    sa.Column('review', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('approved_by', sa.Uuid(), nullable=True),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('desktop_key', sa.String(length=500), nullable=True),
    sa.Column('phone_key', sa.String(length=500), nullable=True),
    sa.Column('captured_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('capture_error', sa.String(length=500), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], name=op.f('fk_draft_previews_approved_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['website_id'], ['websites.id'], name=op.f('fk_draft_previews_website_id_websites'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_draft_previews')),
    sa.UniqueConstraint('token', name=op.f('uq_draft_previews_token')),
    sa.UniqueConstraint('website_id', name=op.f('uq_draft_previews_website_id'))
    )
    _set_job_kinds(NEW_JOB_KINDS)


def downgrade() -> None:
    op.execute("DELETE FROM factory_jobs WHERE kind = 'prepare_draft'")
    _set_job_kinds(OLD_JOB_KINDS)
    op.drop_table('draft_previews')
