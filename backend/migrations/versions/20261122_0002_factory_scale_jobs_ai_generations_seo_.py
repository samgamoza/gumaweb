"""factory scale: jobs, ai generations, seo pages, asset metadata

New NOT NULL columns on existing tables carry server defaults so the upgrade works on populated databases.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22 06:02:39.520561+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('ai_generations',
    sa.Column('cache_key', sa.String(length=64), nullable=False),
    sa.Column('task', sa.String(length=64), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('prompt_version', sa.String(length=32), nullable=False),
    sa.Column('request', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('response', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('accepted', sa.Boolean(), nullable=False),
    sa.Column('rejection_reasons', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_generations')),
    sa.UniqueConstraint('cache_key', name=op.f('uq_ai_generations_cache_key'))
    )
    op.create_index(op.f('ix_ai_generations_created_at'), 'ai_generations', ['created_at'], unique=False)
    op.create_index(op.f('ix_ai_generations_task'), 'ai_generations', ['task'], unique=False)
    op.create_table('factory_jobs',
    sa.Column('kind', sa.Enum('generate_website', 'regenerate_website', 'publish_website', name='jobkind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('queued', 'running', 'succeeded', 'failed', name='jobstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('dedupe_key', sa.String(length=128), nullable=True),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('run_after', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_by', sa.String(length=128), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('result', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_factory_jobs'))
    )
    op.create_index('ix_factory_jobs_pickup', 'factory_jobs', ['status', 'run_after', 'priority'], unique=False)
    op.create_index('uq_factory_jobs_active_dedupe', 'factory_jobs', ['dedupe_key'], unique=True, postgresql_where=sa.text("status IN ('queued', 'running') AND dedupe_key IS NOT NULL"), sqlite_where=sa.text("status IN ('queued', 'running') AND dedupe_key IS NOT NULL"))
    op.add_column('media_assets', sa.Column('sha256', sa.String(length=64), nullable=True))
    op.add_column('media_assets', sa.Column('size_bytes', sa.Integer(), server_default='0', nullable=False))
    op.add_column('media_assets', sa.Column('width', sa.Integer(), nullable=True))
    op.add_column('media_assets', sa.Column('height', sa.Integer(), nullable=True))
    op.add_column('media_assets', sa.Column('usage_count', sa.Integer(), server_default='0', nullable=False))
    op.create_index(op.f('ix_media_assets_sha256'), 'media_assets', ['sha256'], unique=False)
    op.add_column('seo_metadata', sa.Column('pages', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), server_default='{}', nullable=False))
    op.add_column('seo_metadata', sa.Column('audit', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True))


def downgrade() -> None:
    op.drop_column('seo_metadata', 'audit')
    op.drop_column('seo_metadata', 'pages')
    op.drop_index(op.f('ix_media_assets_sha256'), table_name='media_assets')
    op.drop_column('media_assets', 'usage_count')
    op.drop_column('media_assets', 'height')
    op.drop_column('media_assets', 'width')
    op.drop_column('media_assets', 'size_bytes')
    op.drop_column('media_assets', 'sha256')
    op.drop_index('uq_factory_jobs_active_dedupe', table_name='factory_jobs', postgresql_where=sa.text("status IN ('queued', 'running') AND dedupe_key IS NOT NULL"), sqlite_where=sa.text("status IN ('queued', 'running') AND dedupe_key IS NOT NULL"))
    op.drop_index('ix_factory_jobs_pickup', table_name='factory_jobs')
    op.drop_table('factory_jobs')
    op.drop_index(op.f('ix_ai_generations_task'), table_name='ai_generations')
    op.drop_index(op.f('ix_ai_generations_created_at'), table_name='ai_generations')
    op.drop_table('ai_generations')
