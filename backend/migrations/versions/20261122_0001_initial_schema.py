"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-11-22 05:28:50.019943+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('domain_events',
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('aggregate_type', sa.String(length=64), nullable=False),
    sa.Column('aggregate_id', sa.String(length=64), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_domain_events'))
    )
    op.create_index(op.f('ix_domain_events_event_type'), 'domain_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_domain_events_processed_at'), 'domain_events', ['processed_at'], unique=False)

    op.create_table('outreach_suppressions',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('reason', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_outreach_suppressions')),
    sa.UniqueConstraint('email', name=op.f('uq_outreach_suppressions_email'))
    )
    op.create_table('plans',
    sa.Column('code', sa.Enum('free', 'professional', 'business', 'ai', 'voice_ai', name='plancode', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('price_monthly_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('features', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_plans'))
    )
    op.create_table('template_components',
    sa.Column('slug', sa.String(length=100), nullable=False),
    sa.Column('component_type', sa.Enum('hero', 'about', 'services', 'gallery', 'testimonials', 'faq', 'cta', 'contact', 'map', 'footer', name='componenttype', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('variant', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('template_path', sa.String(length=255), nullable=False),
    sa.Column('content_schema', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_template_components')),
    sa.UniqueConstraint('component_type', 'variant', name=op.f('uq_template_components_component_type_variant')),
    sa.UniqueConstraint('slug', name=op.f('uq_template_components_slug'))
    )
    op.create_table('templates',
    sa.Column('slug', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.Enum('draft', 'active', 'deprecated', name='templatestatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('pages', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('theme', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('industries', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('preview_image_url', sa.String(length=500), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_templates')),
    sa.UniqueConstraint('slug', name=op.f('uq_templates_slug'))
    )
    op.create_index(op.f('ix_templates_category'), 'templates', ['category'], unique=False)

    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('full_name', sa.String(length=200), nullable=True),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('role', sa.Enum('admin', 'operator', 'customer', 'readonly', name='userrole', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('is_email_verified', sa.Boolean(), nullable=False),
    sa.Column('mfa_enabled', sa.Boolean(), nullable=False),
    sa.Column('oauth_provider', sa.String(length=32), nullable=True),
    sa.Column('oauth_subject', sa.String(length=255), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('oauth_provider', 'oauth_subject', name=op.f('uq_users_oauth_provider_oauth_subject'))
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_role'), 'users', ['role'], unique=False)

    op.create_table('audit_logs',
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('actor_role', sa.String(length=32), nullable=True),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('entity_type', sa.String(length=64), nullable=False),
    sa.Column('entity_id', sa.String(length=64), nullable=True),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_audit_logs_actor_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_actor_id'), 'audit_logs', ['actor_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)
    op.create_index('ix_audit_logs_entity', 'audit_logs', ['entity_type', 'entity_id'], unique=False)

    op.create_table('discovery_runs',
    sa.Column('source', sa.Enum('manual', 'csv_import', 'dti', 'chamber', 'yellow_pages', 'google_business', 'facebook', 'sec', name='discoverysource', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('running', 'completed', 'failed', name='discoveryrunstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('total_records', sa.Integer(), nullable=False),
    sa.Column('created_count', sa.Integer(), nullable=False),
    sa.Column('duplicate_count', sa.Integer(), nullable=False),
    sa.Column('error_count', sa.Integer(), nullable=False),
    sa.Column('errors', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('started_by', sa.Uuid(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['started_by'], ['users.id'], name=op.f('fk_discovery_runs_started_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_discovery_runs'))
    )
    op.create_table('outreach_campaigns',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('channel', sa.Enum('email', 'contact_form', 'sms', 'voice', 'facebook', name='outreachchannel', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('draft', 'active', 'paused', 'completed', name='campaignstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('sequence', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('target_filter', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_outreach_campaigns_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_outreach_campaigns'))
    )
    op.create_table('businesses',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('slug', sa.String(length=63), nullable=False),
    sa.Column('industry', sa.String(length=64), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('city', sa.String(length=120), nullable=True),
    sa.Column('province', sa.String(length=120), nullable=True),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('postal_code', sa.String(length=16), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('website', sa.String(length=500), nullable=True),
    sa.Column('facebook', sa.String(length=500), nullable=True),
    sa.Column('google_business_url', sa.String(length=500), nullable=True),
    sa.Column('source', sa.Enum('manual', 'csv_import', 'dti', 'chamber', 'yellow_pages', 'google_business', 'facebook', 'sec', name='discoverysource', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('source_ref', sa.String(length=255), nullable=True),
    sa.Column('dedupe_key', sa.String(length=255), nullable=False),
    sa.Column('discovery_run_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Enum('discovered', 'scored', 'profiled', 'generated', 'published', 'claimed', 'archived', name='businessstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('score_breakdown', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('generate_candidate', sa.Boolean(), nullable=False),
    sa.Column('scored_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint('score IS NULL OR (score >= 0 AND score <= 100)', name=op.f('ck_businesses_score_range')),
    sa.ForeignKeyConstraint(['discovery_run_id'], ['discovery_runs.id'], name=op.f('fk_businesses_discovery_run_id_discovery_runs'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_businesses')),
    sa.UniqueConstraint('dedupe_key', name=op.f('uq_businesses_dedupe_key')),
    sa.UniqueConstraint('slug', name=op.f('uq_businesses_slug'))
    )
    op.create_index('ix_businesses_candidate_score', 'businesses', ['generate_candidate', 'score'], unique=False)
    op.create_index(op.f('ix_businesses_city'), 'businesses', ['city'], unique=False)
    op.create_index('ix_businesses_industry_city', 'businesses', ['industry', 'city'], unique=False)
    op.create_index(op.f('ix_businesses_status'), 'businesses', ['status'], unique=False)

    op.create_table('business_profiles',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('industry', sa.String(length=64), nullable=False),
    sa.Column('category', sa.String(length=64), nullable=False),
    sa.Column('services', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('keywords', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('local_keywords', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('target_audience', sa.String(length=64), nullable=True),
    sa.Column('brand_voice', sa.String(length=255), nullable=True),
    sa.Column('brand_tone', sa.String(length=32), nullable=True),
    sa.Column('tagline', sa.String(length=255), nullable=True),
    sa.Column('recommended_template', sa.String(length=100), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('source', sa.Enum('rule_based', 'ai', 'manual', name='profilesource', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_business_profiles_business_id_businesses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_business_profiles')),
    sa.UniqueConstraint('business_id', name=op.f('uq_business_profiles_business_id'))
    )
    op.create_index(op.f('ix_business_profiles_category'), 'business_profiles', ['category'], unique=False)

    op.create_table('customers',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('plan', sa.Enum('free', 'professional', 'business', 'ai', 'voice_ai', name='plancode', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('active', 'suspended', 'churned', name='customerstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('activated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_customers_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_customers_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customers')),
    sa.UniqueConstraint('business_id', name=op.f('uq_customers_business_id')),
    sa.UniqueConstraint('user_id', name=op.f('uq_customers_user_id'))
    )
    op.create_index(op.f('ix_customers_plan'), 'customers', ['plan'], unique=False)

    op.create_table('media_assets',
    sa.Column('business_id', sa.Uuid(), nullable=True),
    sa.Column('industry', sa.String(length=64), nullable=True),
    sa.Column('category', sa.String(length=64), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('mime_type', sa.String(length=100), nullable=False),
    sa.Column('tags', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('alt_text', sa.String(length=255), nullable=True),
    sa.Column('quality_score', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_media_assets_business_id_businesses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_media_assets'))
    )
    op.create_index(op.f('ix_media_assets_business_id'), 'media_assets', ['business_id'], unique=False)
    op.create_index(op.f('ix_media_assets_industry'), 'media_assets', ['industry'], unique=False)

    op.create_table('websites',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('template_id', sa.Uuid(), nullable=True),
    sa.Column('subdomain', sa.String(length=63), nullable=False),
    sa.Column('url', sa.String(length=500), nullable=True),
    sa.Column('status', sa.Enum('draft', 'blueprint_ready', 'built', 'published', 'unpublished', 'failed', name='websitestatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('blueprint', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('quality_score', sa.Integer(), nullable=True),
    sa.Column('quality_report', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('is_claimed', sa.Boolean(), nullable=False),
    sa.Column('artifact_path', sa.String(length=500), nullable=True),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_websites_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['template_id'], ['templates.id'], name=op.f('fk_websites_template_id_templates'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_websites')),
    sa.UniqueConstraint('business_id', name=op.f('uq_websites_business_id')),
    sa.UniqueConstraint('subdomain', name=op.f('uq_websites_subdomain'))
    )
    op.create_index(op.f('ix_websites_status'), 'websites', ['status'], unique=False)
    op.create_index(op.f('ix_websites_template_id'), 'websites', ['template_id'], unique=False)

    op.create_table('claims',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('website_id', sa.Uuid(), nullable=True),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('claimant_name', sa.String(length=200), nullable=False),
    sa.Column('claimant_email', sa.String(length=320), nullable=False),
    sa.Column('claimant_phone', sa.String(length=32), nullable=True),
    sa.Column('method', sa.Enum('email', 'sms', 'business_identity', name='verificationmethod', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('pending_verification', 'manual_review', 'approved', 'rejected', 'expired', name='claimstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('verification_token_hash', sa.String(length=64), nullable=True),
    sa.Column('otp_hash', sa.String(length=64), nullable=True),
    sa.Column('verification_attempts', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('risk_score', sa.Integer(), nullable=False),
    sa.Column('risk_factors', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('evidence', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.String(length=500), nullable=True),
    sa.Column('reviewed_by', sa.Uuid(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_claims_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], name=op.f('fk_claims_reviewed_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_claims_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['website_id'], ['websites.id'], name=op.f('fk_claims_website_id_websites'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_claims')),
    sa.UniqueConstraint('verification_token_hash', name=op.f('uq_claims_verification_token_hash'))
    )
    op.create_index('ix_claims_business_status', 'claims', ['business_id', 'status'], unique=False)
    op.create_index(op.f('ix_claims_claimant_email'), 'claims', ['claimant_email'], unique=False)
    op.create_index(op.f('ix_claims_user_id'), 'claims', ['user_id'], unique=False)
    op.create_index('uq_claims_business_approved', 'claims', ['business_id'], unique=True, postgresql_where=sa.text("status = 'approved'"), sqlite_where=sa.text("status = 'approved'"))

    op.create_table('deployments',
    sa.Column('website_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'succeeded', 'failed', name='deploymentstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('storage_backend', sa.String(length=16), nullable=False),
    sa.Column('artifact_path', sa.String(length=500), nullable=True),
    sa.Column('file_count', sa.Integer(), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('triggered_by', sa.Uuid(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['triggered_by'], ['users.id'], name=op.f('fk_deployments_triggered_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['website_id'], ['websites.id'], name=op.f('fk_deployments_website_id_websites'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_deployments'))
    )
    op.create_index(op.f('ix_deployments_website_id'), 'deployments', ['website_id'], unique=False)

    op.create_table('leads',
    sa.Column('website_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('ip_hash', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['website_id'], ['websites.id'], name=op.f('fk_leads_website_id_websites'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_leads'))
    )
    op.create_index(op.f('ix_leads_created_at'), 'leads', ['created_at'], unique=False)
    op.create_index(op.f('ix_leads_website_id'), 'leads', ['website_id'], unique=False)

    op.create_table('outreach_messages',
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('website_id', sa.Uuid(), nullable=True),
    sa.Column('channel', sa.Enum('email', 'contact_form', 'sms', 'voice', 'facebook', name='outreachchannel', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('step', sa.Integer(), nullable=False),
    sa.Column('recipient', sa.String(length=320), nullable=False),
    sa.Column('subject', sa.String(length=255), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('tracking_token', sa.String(length=64), nullable=False),
    sa.Column('status', sa.Enum('scheduled', 'sent', 'failed', 'skipped', name='messagestatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_outreach_messages_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['campaign_id'], ['outreach_campaigns.id'], name=op.f('fk_outreach_messages_campaign_id_outreach_campaigns'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['website_id'], ['websites.id'], name=op.f('fk_outreach_messages_website_id_websites'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_outreach_messages')),
    sa.UniqueConstraint('campaign_id', 'business_id', 'step', name=op.f('uq_outreach_messages_campaign_id_business_id_step')),
    sa.UniqueConstraint('tracking_token', name=op.f('uq_outreach_messages_tracking_token'))
    )
    op.create_index(op.f('ix_outreach_messages_business_id'), 'outreach_messages', ['business_id'], unique=False)
    op.create_index('ix_outreach_messages_status_scheduled', 'outreach_messages', ['status', 'scheduled_at'], unique=False)

    op.create_table('seo_metadata',
    sa.Column('website_id', sa.Uuid(), nullable=False),
    sa.Column('page_title', sa.String(length=255), nullable=False),
    sa.Column('meta_description', sa.String(length=500), nullable=False),
    sa.Column('keywords', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('local_keywords', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('schema_markup', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('seo_score', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['website_id'], ['websites.id'], name=op.f('fk_seo_metadata_website_id_websites'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_seo_metadata')),
    sa.UniqueConstraint('website_id', name=op.f('uq_seo_metadata_website_id'))
    )
    op.create_table('site_events',
    sa.Column('website_id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.Enum('page_view', 'claim_banner_click', 'contact_submit', 'phone_click', name='siteeventtype', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('path', sa.String(length=500), nullable=True),
    sa.Column('referrer', sa.String(length=500), nullable=True),
    sa.Column('visitor_hash', sa.String(length=64), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['website_id'], ['websites.id'], name=op.f('fk_site_events_website_id_websites'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_site_events'))
    )
    op.create_index('ix_site_events_website_type_time', 'site_events', ['website_id', 'event_type', 'occurred_at'], unique=False)

    op.create_table('subscriptions',
    sa.Column('customer_id', sa.Uuid(), nullable=False),
    sa.Column('plan_code', sa.Enum('free', 'professional', 'business', 'ai', 'voice_ai', name='plancode', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('active', 'past_due', 'canceled', name='subscriptionstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('provider_ref', sa.String(length=255), nullable=True),
    sa.Column('current_period_start', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_subscriptions_customer_id_customers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['plan_code'], ['plans.code'], name=op.f('fk_subscriptions_plan_code_plans')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_subscriptions'))
    )
    op.create_index(op.f('ix_subscriptions_customer_id'), 'subscriptions', ['customer_id'], unique=False)
    op.create_index('uq_subscriptions_customer_active', 'subscriptions', ['customer_id'], unique=True, postgresql_where=sa.text("status = 'active'"), sqlite_where=sa.text("status = 'active'"))

    op.create_table('website_content',
    sa.Column('website_id', sa.Uuid(), nullable=False),
    sa.Column('section_key', sa.String(length=64), nullable=False),
    sa.Column('content', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('source', sa.Enum('template', 'ai', 'customer', 'operator', name='contentsource', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_website_content_updated_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['website_id'], ['websites.id'], name=op.f('fk_website_content_website_id_websites'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_website_content')),
    sa.UniqueConstraint('website_id', 'section_key', name=op.f('uq_website_content_website_id_section_key'))
    )
    op.create_table('outreach_events',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=True),
    sa.Column('message_id', sa.Uuid(), nullable=True),
    sa.Column('channel', sa.Enum('email', 'contact_form', 'sms', 'voice', 'facebook', name='outreachchannel', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('event_type', sa.Enum('email_sent', 'email_opened', 'link_clicked', 'website_visited', 'claim_started', 'claim_completed', 'unsubscribed', name='outreacheventtype', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_outreach_events_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['campaign_id'], ['outreach_campaigns.id'], name=op.f('fk_outreach_events_campaign_id_outreach_campaigns'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['message_id'], ['outreach_messages.id'], name=op.f('fk_outreach_events_message_id_outreach_messages'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_outreach_events'))
    )
    op.create_index('ix_outreach_events_business_type', 'outreach_events', ['business_id', 'event_type'], unique=False)
    op.create_index(op.f('ix_outreach_events_campaign_id'), 'outreach_events', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_outreach_events_occurred_at'), 'outreach_events', ['occurred_at'], unique=False)



def downgrade() -> None:
    op.drop_index(op.f('ix_outreach_events_occurred_at'), table_name='outreach_events')
    op.drop_index(op.f('ix_outreach_events_campaign_id'), table_name='outreach_events')
    op.drop_index('ix_outreach_events_business_type', table_name='outreach_events')
    op.drop_table('outreach_events')

    op.drop_table('website_content')
    op.drop_index('uq_subscriptions_customer_active', table_name='subscriptions', postgresql_where=sa.text("status = 'active'"), sqlite_where=sa.text("status = 'active'"))
    op.drop_index(op.f('ix_subscriptions_customer_id'), table_name='subscriptions')
    op.drop_table('subscriptions')

    op.drop_index('ix_site_events_website_type_time', table_name='site_events')
    op.drop_table('site_events')

    op.drop_table('seo_metadata')
    op.drop_index('ix_outreach_messages_status_scheduled', table_name='outreach_messages')
    op.drop_index(op.f('ix_outreach_messages_business_id'), table_name='outreach_messages')
    op.drop_table('outreach_messages')

    op.drop_index(op.f('ix_leads_website_id'), table_name='leads')
    op.drop_index(op.f('ix_leads_created_at'), table_name='leads')
    op.drop_table('leads')

    op.drop_index(op.f('ix_deployments_website_id'), table_name='deployments')
    op.drop_table('deployments')

    op.drop_index('uq_claims_business_approved', table_name='claims', postgresql_where=sa.text("status = 'approved'"), sqlite_where=sa.text("status = 'approved'"))
    op.drop_index(op.f('ix_claims_user_id'), table_name='claims')
    op.drop_index(op.f('ix_claims_claimant_email'), table_name='claims')
    op.drop_index('ix_claims_business_status', table_name='claims')
    op.drop_table('claims')

    op.drop_index(op.f('ix_websites_template_id'), table_name='websites')
    op.drop_index(op.f('ix_websites_status'), table_name='websites')
    op.drop_table('websites')

    op.drop_index(op.f('ix_media_assets_industry'), table_name='media_assets')
    op.drop_index(op.f('ix_media_assets_business_id'), table_name='media_assets')
    op.drop_table('media_assets')

    op.drop_index(op.f('ix_customers_plan'), table_name='customers')
    op.drop_table('customers')

    op.drop_index(op.f('ix_business_profiles_category'), table_name='business_profiles')
    op.drop_table('business_profiles')

    op.drop_index(op.f('ix_businesses_status'), table_name='businesses')
    op.drop_index('ix_businesses_industry_city', table_name='businesses')
    op.drop_index(op.f('ix_businesses_city'), table_name='businesses')
    op.drop_index('ix_businesses_candidate_score', table_name='businesses')
    op.drop_table('businesses')

    op.drop_table('outreach_campaigns')
    op.drop_table('discovery_runs')
    op.drop_index('ix_audit_logs_entity', table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_created_at'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_actor_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_table('audit_logs')

    op.drop_index(op.f('ix_users_role'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')

    op.drop_index(op.f('ix_templates_category'), table_name='templates')
    op.drop_table('templates')

    op.drop_table('template_components')
    op.drop_table('plans')
    op.drop_table('outreach_suppressions')
    op.drop_index(op.f('ix_domain_events_processed_at'), table_name='domain_events')
    op.drop_index(op.f('ix_domain_events_event_type'), table_name='domain_events')
    op.drop_table('domain_events')

