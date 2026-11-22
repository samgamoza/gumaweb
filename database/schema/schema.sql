BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001

CREATE TABLE domain_events (
    event_type VARCHAR(100) NOT NULL, 
    aggregate_type VARCHAR(64) NOT NULL, 
    aggregate_id VARCHAR(64) NOT NULL, 
    payload JSONB NOT NULL, 
    occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    processed_at TIMESTAMP WITH TIME ZONE, 
    id UUID NOT NULL, 
    CONSTRAINT pk_domain_events PRIMARY KEY (id)
);

CREATE INDEX ix_domain_events_event_type ON domain_events (event_type);

CREATE INDEX ix_domain_events_processed_at ON domain_events (processed_at);

CREATE TABLE outreach_suppressions (
    email VARCHAR(320) NOT NULL, 
    reason VARCHAR(64) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_outreach_suppressions PRIMARY KEY (id), 
    CONSTRAINT uq_outreach_suppressions_email UNIQUE (email)
);

CREATE TABLE plans (
    code VARCHAR(32) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    description TEXT, 
    price_monthly_cents INTEGER NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    features JSONB NOT NULL, 
    sort_order INTEGER NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_plans PRIMARY KEY (code), 
    CONSTRAINT ck_plans_plancode CHECK (code IN ('free', 'professional', 'business', 'ai', 'voice_ai'))
);

CREATE TABLE template_components (
    slug VARCHAR(100) NOT NULL, 
    component_type VARCHAR(32) NOT NULL, 
    variant VARCHAR(64) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    template_path VARCHAR(255) NOT NULL, 
    content_schema JSONB NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_template_components PRIMARY KEY (id), 
    CONSTRAINT uq_template_components_component_type_variant UNIQUE (component_type, variant), 
    CONSTRAINT uq_template_components_slug UNIQUE (slug), 
    CONSTRAINT ck_template_components_componenttype CHECK (component_type IN ('hero', 'about', 'services', 'gallery', 'testimonials', 'faq', 'cta', 'contact', 'map', 'footer'))
);

CREATE TABLE templates (
    slug VARCHAR(100) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    category VARCHAR(64) NOT NULL, 
    version INTEGER NOT NULL, 
    description TEXT, 
    status VARCHAR(32) NOT NULL, 
    is_default BOOLEAN NOT NULL, 
    pages JSONB NOT NULL, 
    theme JSONB NOT NULL, 
    industries JSONB NOT NULL, 
    preview_image_url VARCHAR(500), 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_templates PRIMARY KEY (id), 
    CONSTRAINT uq_templates_slug UNIQUE (slug), 
    CONSTRAINT ck_templates_templatestatus CHECK (status IN ('draft', 'active', 'deprecated'))
);

CREATE INDEX ix_templates_category ON templates (category);

CREATE TABLE users (
    email VARCHAR(320) NOT NULL, 
    password_hash VARCHAR(255), 
    full_name VARCHAR(200), 
    phone VARCHAR(32), 
    role VARCHAR(32) NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    is_email_verified BOOLEAN NOT NULL, 
    mfa_enabled BOOLEAN NOT NULL, 
    oauth_provider VARCHAR(32), 
    oauth_subject VARCHAR(255), 
    last_login_at TIMESTAMP WITH TIME ZONE, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_users PRIMARY KEY (id), 
    CONSTRAINT uq_users_oauth_provider_oauth_subject UNIQUE (oauth_provider, oauth_subject), 
    CONSTRAINT ck_users_userrole CHECK (role IN ('admin', 'operator', 'customer', 'readonly'))
);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE INDEX ix_users_role ON users (role);

CREATE TABLE audit_logs (
    actor_id UUID, 
    actor_role VARCHAR(32), 
    action VARCHAR(100) NOT NULL, 
    entity_type VARCHAR(64) NOT NULL, 
    entity_id VARCHAR(64), 
    data JSONB NOT NULL, 
    ip_address VARCHAR(45), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_audit_logs PRIMARY KEY (id), 
    CONSTRAINT fk_audit_logs_actor_id_users FOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_audit_logs_action ON audit_logs (action);

CREATE INDEX ix_audit_logs_actor_id ON audit_logs (actor_id);

CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);

CREATE INDEX ix_audit_logs_entity ON audit_logs (entity_type, entity_id);

CREATE TABLE discovery_runs (
    source VARCHAR(32) NOT NULL, 
    status VARCHAR(32) NOT NULL, 
    total_records INTEGER NOT NULL, 
    created_count INTEGER NOT NULL, 
    duplicate_count INTEGER NOT NULL, 
    error_count INTEGER NOT NULL, 
    errors JSONB NOT NULL, 
    started_by UUID, 
    started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    finished_at TIMESTAMP WITH TIME ZONE, 
    id UUID NOT NULL, 
    CONSTRAINT pk_discovery_runs PRIMARY KEY (id), 
    CONSTRAINT fk_discovery_runs_started_by_users FOREIGN KEY(started_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT ck_discovery_runs_discoverysource CHECK (source IN ('manual', 'csv_import', 'dti', 'chamber', 'yellow_pages', 'google_business', 'facebook', 'sec')), 
    CONSTRAINT ck_discovery_runs_discoveryrunstatus CHECK (status IN ('running', 'completed', 'failed'))
);

CREATE TABLE outreach_campaigns (
    name VARCHAR(200) NOT NULL, 
    channel VARCHAR(32) NOT NULL, 
    status VARCHAR(32) NOT NULL, 
    sequence JSONB NOT NULL, 
    target_filter JSONB NOT NULL, 
    created_by UUID, 
    started_at TIMESTAMP WITH TIME ZONE, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_outreach_campaigns PRIMARY KEY (id), 
    CONSTRAINT fk_outreach_campaigns_created_by_users FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT ck_outreach_campaigns_outreachchannel CHECK (channel IN ('email', 'contact_form', 'sms', 'voice', 'facebook')), 
    CONSTRAINT ck_outreach_campaigns_campaignstatus CHECK (status IN ('draft', 'active', 'paused', 'completed'))
);

CREATE TABLE businesses (
    name VARCHAR(255) NOT NULL, 
    slug VARCHAR(63) NOT NULL, 
    industry VARCHAR(64), 
    description TEXT, 
    address TEXT, 
    city VARCHAR(120), 
    province VARCHAR(120), 
    country VARCHAR(2) NOT NULL, 
    postal_code VARCHAR(16), 
    latitude FLOAT, 
    longitude FLOAT, 
    phone VARCHAR(32), 
    email VARCHAR(320), 
    website VARCHAR(500), 
    facebook VARCHAR(500), 
    google_business_url VARCHAR(500), 
    source VARCHAR(32) NOT NULL, 
    source_ref VARCHAR(255), 
    dedupe_key VARCHAR(255) NOT NULL, 
    discovery_run_id UUID, 
    status VARCHAR(32) NOT NULL, 
    score INTEGER, 
    score_breakdown JSONB, 
    generate_candidate BOOLEAN NOT NULL, 
    scored_at TIMESTAMP WITH TIME ZONE, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_businesses PRIMARY KEY (id), 
    CONSTRAINT ck_businesses_score_range CHECK (score IS NULL OR (score >= 0 AND score <= 100)), 
    CONSTRAINT fk_businesses_discovery_run_id_discovery_runs FOREIGN KEY(discovery_run_id) REFERENCES discovery_runs (id) ON DELETE SET NULL, 
    CONSTRAINT uq_businesses_dedupe_key UNIQUE (dedupe_key), 
    CONSTRAINT uq_businesses_slug UNIQUE (slug), 
    CONSTRAINT ck_businesses_discoverysource CHECK (source IN ('manual', 'csv_import', 'dti', 'chamber', 'yellow_pages', 'google_business', 'facebook', 'sec')), 
    CONSTRAINT ck_businesses_businessstatus CHECK (status IN ('discovered', 'scored', 'profiled', 'generated', 'published', 'claimed', 'archived'))
);

CREATE INDEX ix_businesses_candidate_score ON businesses (generate_candidate, score);

CREATE INDEX ix_businesses_city ON businesses (city);

CREATE INDEX ix_businesses_industry_city ON businesses (industry, city);

CREATE INDEX ix_businesses_status ON businesses (status);

CREATE TABLE business_profiles (
    business_id UUID NOT NULL, 
    industry VARCHAR(64) NOT NULL, 
    category VARCHAR(64) NOT NULL, 
    services JSONB NOT NULL, 
    keywords JSONB NOT NULL, 
    local_keywords JSONB NOT NULL, 
    target_audience VARCHAR(64), 
    brand_voice VARCHAR(255), 
    brand_tone VARCHAR(32), 
    tagline VARCHAR(255), 
    recommended_template VARCHAR(100), 
    confidence FLOAT NOT NULL, 
    source VARCHAR(32) NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_business_profiles PRIMARY KEY (id), 
    CONSTRAINT fk_business_profiles_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE CASCADE, 
    CONSTRAINT uq_business_profiles_business_id UNIQUE (business_id), 
    CONSTRAINT ck_business_profiles_profilesource CHECK (source IN ('rule_based', 'ai', 'manual'))
);

CREATE INDEX ix_business_profiles_category ON business_profiles (category);

CREATE TABLE customers (
    user_id UUID NOT NULL, 
    business_id UUID NOT NULL, 
    plan VARCHAR(32) NOT NULL, 
    status VARCHAR(32) NOT NULL, 
    activated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_customers PRIMARY KEY (id), 
    CONSTRAINT fk_customers_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE CASCADE, 
    CONSTRAINT fk_customers_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_customers_business_id UNIQUE (business_id), 
    CONSTRAINT uq_customers_user_id UNIQUE (user_id), 
    CONSTRAINT ck_customers_plancode CHECK (plan IN ('free', 'professional', 'business', 'ai', 'voice_ai')), 
    CONSTRAINT ck_customers_customerstatus CHECK (status IN ('active', 'suspended', 'churned'))
);

CREATE INDEX ix_customers_plan ON customers (plan);

CREATE TABLE media_assets (
    business_id UUID, 
    industry VARCHAR(64), 
    category VARCHAR(64) NOT NULL, 
    storage_key VARCHAR(500) NOT NULL, 
    mime_type VARCHAR(100) NOT NULL, 
    tags JSONB NOT NULL, 
    alt_text VARCHAR(255), 
    quality_score INTEGER, 
    source VARCHAR(32) NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_media_assets PRIMARY KEY (id), 
    CONSTRAINT fk_media_assets_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE CASCADE
);

CREATE INDEX ix_media_assets_business_id ON media_assets (business_id);

CREATE INDEX ix_media_assets_industry ON media_assets (industry);

CREATE TABLE websites (
    business_id UUID NOT NULL, 
    template_id UUID, 
    subdomain VARCHAR(63) NOT NULL, 
    url VARCHAR(500), 
    status VARCHAR(32) NOT NULL, 
    version INTEGER NOT NULL, 
    blueprint JSONB, 
    quality_score INTEGER, 
    quality_report JSONB, 
    is_claimed BOOLEAN NOT NULL, 
    artifact_path VARCHAR(500), 
    generated_at TIMESTAMP WITH TIME ZONE, 
    published_at TIMESTAMP WITH TIME ZONE, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_websites PRIMARY KEY (id), 
    CONSTRAINT fk_websites_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE CASCADE, 
    CONSTRAINT fk_websites_template_id_templates FOREIGN KEY(template_id) REFERENCES templates (id) ON DELETE SET NULL, 
    CONSTRAINT uq_websites_business_id UNIQUE (business_id), 
    CONSTRAINT uq_websites_subdomain UNIQUE (subdomain), 
    CONSTRAINT ck_websites_websitestatus CHECK (status IN ('draft', 'blueprint_ready', 'built', 'published', 'unpublished', 'failed'))
);

CREATE INDEX ix_websites_status ON websites (status);

CREATE INDEX ix_websites_template_id ON websites (template_id);

CREATE TABLE claims (
    business_id UUID NOT NULL, 
    website_id UUID, 
    user_id UUID, 
    claimant_name VARCHAR(200) NOT NULL, 
    claimant_email VARCHAR(320) NOT NULL, 
    claimant_phone VARCHAR(32), 
    method VARCHAR(32) NOT NULL, 
    status VARCHAR(32) NOT NULL, 
    verification_token_hash VARCHAR(64), 
    otp_hash VARCHAR(64), 
    verification_attempts INTEGER NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    verified_at TIMESTAMP WITH TIME ZONE, 
    risk_score INTEGER NOT NULL, 
    risk_factors JSONB NOT NULL, 
    evidence JSONB NOT NULL, 
    ip_address VARCHAR(45), 
    user_agent VARCHAR(500), 
    reviewed_by UUID, 
    reviewed_at TIMESTAMP WITH TIME ZONE, 
    review_notes TEXT, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_claims PRIMARY KEY (id), 
    CONSTRAINT fk_claims_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE CASCADE, 
    CONSTRAINT fk_claims_reviewed_by_users FOREIGN KEY(reviewed_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_claims_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_claims_website_id_websites FOREIGN KEY(website_id) REFERENCES websites (id) ON DELETE SET NULL, 
    CONSTRAINT uq_claims_verification_token_hash UNIQUE (verification_token_hash), 
    CONSTRAINT ck_claims_verificationmethod CHECK (method IN ('email', 'sms', 'business_identity')), 
    CONSTRAINT ck_claims_claimstatus CHECK (status IN ('pending_verification', 'manual_review', 'approved', 'rejected', 'expired'))
);

CREATE INDEX ix_claims_business_status ON claims (business_id, status);

CREATE INDEX ix_claims_claimant_email ON claims (claimant_email);

CREATE INDEX ix_claims_user_id ON claims (user_id);

CREATE UNIQUE INDEX uq_claims_business_approved ON claims (business_id) WHERE status = 'approved';

CREATE TABLE deployments (
    website_id UUID NOT NULL, 
    version INTEGER NOT NULL, 
    status VARCHAR(32) NOT NULL, 
    storage_backend VARCHAR(16) NOT NULL, 
    artifact_path VARCHAR(500), 
    file_count INTEGER NOT NULL, 
    size_bytes BIGINT NOT NULL, 
    error TEXT, 
    triggered_by UUID, 
    started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    finished_at TIMESTAMP WITH TIME ZONE, 
    id UUID NOT NULL, 
    CONSTRAINT pk_deployments PRIMARY KEY (id), 
    CONSTRAINT fk_deployments_triggered_by_users FOREIGN KEY(triggered_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_deployments_website_id_websites FOREIGN KEY(website_id) REFERENCES websites (id) ON DELETE CASCADE, 
    CONSTRAINT ck_deployments_deploymentstatus CHECK (status IN ('pending', 'succeeded', 'failed'))
);

CREATE INDEX ix_deployments_website_id ON deployments (website_id);

CREATE TABLE leads (
    website_id UUID NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    email VARCHAR(320), 
    phone VARCHAR(32), 
    message TEXT NOT NULL, 
    ip_hash VARCHAR(64), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_leads PRIMARY KEY (id), 
    CONSTRAINT fk_leads_website_id_websites FOREIGN KEY(website_id) REFERENCES websites (id) ON DELETE CASCADE
);

CREATE INDEX ix_leads_created_at ON leads (created_at);

CREATE INDEX ix_leads_website_id ON leads (website_id);

CREATE TABLE outreach_messages (
    campaign_id UUID NOT NULL, 
    business_id UUID NOT NULL, 
    website_id UUID, 
    channel VARCHAR(32) NOT NULL, 
    step INTEGER NOT NULL, 
    recipient VARCHAR(320) NOT NULL, 
    subject VARCHAR(255), 
    body TEXT NOT NULL, 
    tracking_token VARCHAR(64) NOT NULL, 
    status VARCHAR(32) NOT NULL, 
    scheduled_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    sent_at TIMESTAMP WITH TIME ZONE, 
    error TEXT, 
    id UUID NOT NULL, 
    CONSTRAINT pk_outreach_messages PRIMARY KEY (id), 
    CONSTRAINT fk_outreach_messages_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE CASCADE, 
    CONSTRAINT fk_outreach_messages_campaign_id_outreach_campaigns FOREIGN KEY(campaign_id) REFERENCES outreach_campaigns (id) ON DELETE CASCADE, 
    CONSTRAINT fk_outreach_messages_website_id_websites FOREIGN KEY(website_id) REFERENCES websites (id) ON DELETE SET NULL, 
    CONSTRAINT uq_outreach_messages_campaign_id_business_id_step UNIQUE (campaign_id, business_id, step), 
    CONSTRAINT uq_outreach_messages_tracking_token UNIQUE (tracking_token), 
    CONSTRAINT ck_outreach_messages_outreachchannel CHECK (channel IN ('email', 'contact_form', 'sms', 'voice', 'facebook')), 
    CONSTRAINT ck_outreach_messages_messagestatus CHECK (status IN ('scheduled', 'sent', 'failed', 'skipped'))
);

CREATE INDEX ix_outreach_messages_business_id ON outreach_messages (business_id);

CREATE INDEX ix_outreach_messages_status_scheduled ON outreach_messages (status, scheduled_at);

CREATE TABLE seo_metadata (
    website_id UUID NOT NULL, 
    page_title VARCHAR(255) NOT NULL, 
    meta_description VARCHAR(500) NOT NULL, 
    keywords JSONB NOT NULL, 
    local_keywords JSONB NOT NULL, 
    schema_markup JSONB NOT NULL, 
    seo_score INTEGER NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_seo_metadata PRIMARY KEY (id), 
    CONSTRAINT fk_seo_metadata_website_id_websites FOREIGN KEY(website_id) REFERENCES websites (id) ON DELETE CASCADE, 
    CONSTRAINT uq_seo_metadata_website_id UNIQUE (website_id)
);

CREATE TABLE site_events (
    website_id UUID NOT NULL, 
    event_type VARCHAR(32) NOT NULL, 
    path VARCHAR(500), 
    referrer VARCHAR(500), 
    visitor_hash VARCHAR(64), 
    occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_site_events PRIMARY KEY (id), 
    CONSTRAINT fk_site_events_website_id_websites FOREIGN KEY(website_id) REFERENCES websites (id) ON DELETE CASCADE, 
    CONSTRAINT ck_site_events_siteeventtype CHECK (event_type IN ('page_view', 'claim_banner_click', 'contact_submit', 'phone_click'))
);

CREATE INDEX ix_site_events_website_type_time ON site_events (website_id, event_type, occurred_at);

CREATE TABLE subscriptions (
    customer_id UUID NOT NULL, 
    plan_code VARCHAR(32) NOT NULL, 
    status VARCHAR(32) NOT NULL, 
    provider VARCHAR(32) NOT NULL, 
    provider_ref VARCHAR(255), 
    current_period_start TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    current_period_end TIMESTAMP WITH TIME ZONE, 
    canceled_at TIMESTAMP WITH TIME ZONE, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_subscriptions PRIMARY KEY (id), 
    CONSTRAINT fk_subscriptions_customer_id_customers FOREIGN KEY(customer_id) REFERENCES customers (id) ON DELETE CASCADE, 
    CONSTRAINT fk_subscriptions_plan_code_plans FOREIGN KEY(plan_code) REFERENCES plans (code), 
    CONSTRAINT ck_subscriptions_plancode CHECK (plan_code IN ('free', 'professional', 'business', 'ai', 'voice_ai')), 
    CONSTRAINT ck_subscriptions_subscriptionstatus CHECK (status IN ('active', 'past_due', 'canceled'))
);

CREATE INDEX ix_subscriptions_customer_id ON subscriptions (customer_id);

CREATE UNIQUE INDEX uq_subscriptions_customer_active ON subscriptions (customer_id) WHERE status = 'active';

CREATE TABLE website_content (
    website_id UUID NOT NULL, 
    section_key VARCHAR(64) NOT NULL, 
    content JSONB NOT NULL, 
    source VARCHAR(32) NOT NULL, 
    updated_by UUID, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_website_content PRIMARY KEY (id), 
    CONSTRAINT fk_website_content_updated_by_users FOREIGN KEY(updated_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_website_content_website_id_websites FOREIGN KEY(website_id) REFERENCES websites (id) ON DELETE CASCADE, 
    CONSTRAINT uq_website_content_website_id_section_key UNIQUE (website_id, section_key), 
    CONSTRAINT ck_website_content_contentsource CHECK (source IN ('template', 'ai', 'customer', 'operator'))
);

CREATE TABLE outreach_events (
    business_id UUID NOT NULL, 
    campaign_id UUID, 
    message_id UUID, 
    channel VARCHAR(32) NOT NULL, 
    event_type VARCHAR(32) NOT NULL, 
    data JSONB NOT NULL, 
    occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_outreach_events PRIMARY KEY (id), 
    CONSTRAINT fk_outreach_events_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE CASCADE, 
    CONSTRAINT fk_outreach_events_campaign_id_outreach_campaigns FOREIGN KEY(campaign_id) REFERENCES outreach_campaigns (id) ON DELETE SET NULL, 
    CONSTRAINT fk_outreach_events_message_id_outreach_messages FOREIGN KEY(message_id) REFERENCES outreach_messages (id) ON DELETE SET NULL, 
    CONSTRAINT ck_outreach_events_outreachchannel CHECK (channel IN ('email', 'contact_form', 'sms', 'voice', 'facebook')), 
    CONSTRAINT ck_outreach_events_outreacheventtype CHECK (event_type IN ('email_sent', 'email_opened', 'link_clicked', 'website_visited', 'claim_started', 'claim_completed', 'unsubscribed'))
);

CREATE INDEX ix_outreach_events_business_type ON outreach_events (business_id, event_type);

CREATE INDEX ix_outreach_events_campaign_id ON outreach_events (campaign_id);

CREATE INDEX ix_outreach_events_occurred_at ON outreach_events (occurred_at);

INSERT INTO alembic_version (version_num) VALUES ('0001') RETURNING alembic_version.version_num;

-- Running upgrade 0001 -> 0002

CREATE TABLE ai_generations (
    cache_key VARCHAR(64) NOT NULL, 
    task VARCHAR(64) NOT NULL, 
    model VARCHAR(128) NOT NULL, 
    prompt_version VARCHAR(32) NOT NULL, 
    request JSONB NOT NULL, 
    response JSONB, 
    accepted BOOLEAN NOT NULL, 
    rejection_reasons JSONB NOT NULL, 
    prompt_tokens INTEGER NOT NULL, 
    completion_tokens INTEGER NOT NULL, 
    latency_ms INTEGER NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_ai_generations PRIMARY KEY (id), 
    CONSTRAINT uq_ai_generations_cache_key UNIQUE (cache_key)
);

CREATE INDEX ix_ai_generations_created_at ON ai_generations (created_at);

CREATE INDEX ix_ai_generations_task ON ai_generations (task);

CREATE TABLE factory_jobs (
    kind VARCHAR(32) NOT NULL, 
    status VARCHAR(32) NOT NULL, 
    payload JSONB NOT NULL, 
    dedupe_key VARCHAR(128), 
    priority INTEGER NOT NULL, 
    attempts INTEGER NOT NULL, 
    max_attempts INTEGER NOT NULL, 
    run_after TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    locked_at TIMESTAMP WITH TIME ZONE, 
    locked_by VARCHAR(128), 
    finished_at TIMESTAMP WITH TIME ZONE, 
    last_error TEXT, 
    result JSONB, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_factory_jobs PRIMARY KEY (id), 
    CONSTRAINT ck_factory_jobs_jobkind CHECK (kind IN ('generate_website', 'regenerate_website', 'publish_website')), 
    CONSTRAINT ck_factory_jobs_jobstatus CHECK (status IN ('queued', 'running', 'succeeded', 'failed'))
);

CREATE INDEX ix_factory_jobs_pickup ON factory_jobs (status, run_after, priority);

CREATE UNIQUE INDEX uq_factory_jobs_active_dedupe ON factory_jobs (dedupe_key) WHERE status IN ('queued', 'running') AND dedupe_key IS NOT NULL;

ALTER TABLE media_assets ADD COLUMN sha256 VARCHAR(64);

ALTER TABLE media_assets ADD COLUMN size_bytes INTEGER DEFAULT '0' NOT NULL;

ALTER TABLE media_assets ADD COLUMN width INTEGER;

ALTER TABLE media_assets ADD COLUMN height INTEGER;

ALTER TABLE media_assets ADD COLUMN usage_count INTEGER DEFAULT '0' NOT NULL;

CREATE INDEX ix_media_assets_sha256 ON media_assets (sha256);

ALTER TABLE seo_metadata ADD COLUMN pages JSONB DEFAULT '{}' NOT NULL;

ALTER TABLE seo_metadata ADD COLUMN audit JSONB;

UPDATE alembic_version SET version_num='0002' WHERE alembic_version.version_num = '0001';

-- Running upgrade 0002 -> 0003

CREATE TABLE booking_settings (
    business_id UUID NOT NULL, 
    enabled BOOLEAN NOT NULL, 
    timezone VARCHAR(64) NOT NULL, 
    slot_minutes INTEGER NOT NULL, 
    buffer_minutes INTEGER NOT NULL, 
    lead_time_hours INTEGER NOT NULL, 
    max_days_ahead INTEGER NOT NULL, 
    auto_confirm BOOLEAN NOT NULL, 
    weekly_hours JSONB NOT NULL, 
    services JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_booking_settings PRIMARY KEY (business_id), 
    CONSTRAINT fk_booking_settings_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE CASCADE
);

CREATE TABLE chatbot_settings (
    business_id UUID NOT NULL, 
    enabled BOOLEAN NOT NULL, 
    greeting VARCHAR(300) NOT NULL, 
    handoff_message VARCHAR(300) NOT NULL, 
    collect_leads BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_chatbot_settings PRIMARY KEY (business_id), 
    CONSTRAINT fk_chatbot_settings_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE CASCADE
);

CREATE TABLE contacts (
    business_id UUID NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    email VARCHAR(320), 
    phone VARCHAR(32), 
    source VARCHAR(32) NOT NULL, 
    stage VARCHAR(32) NOT NULL, 
    value_cents INTEGER, 
    tags JSONB NOT NULL, 
    notes TEXT, 
    last_activity_at TIMESTAMP WITH TIME ZONE, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_contacts PRIMARY KEY (id), 
    CONSTRAINT fk_contacts_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE CASCADE, 
    CONSTRAINT ck_contacts_contactsource CHECK (source IN ('contact_form', 'booking', 'chatbot', 'manual', 'phone')), 
    CONSTRAINT ck_contacts_contactstage CHECK (stage IN ('new', 'contacted', 'qualified', 'won', 'lost'))
);

CREATE INDEX ix_contacts_business_stage ON contacts (business_id, stage);

CREATE INDEX ix_contacts_last_activity_at ON contacts (last_activity_at);

CREATE UNIQUE INDEX uq_contacts_business_email ON contacts (business_id, email) WHERE email IS NOT NULL;

CREATE UNIQUE INDEX uq_contacts_business_phone ON contacts (business_id, phone) WHERE phone IS NOT NULL;

CREATE TABLE knowledge_entries (
    business_id UUID NOT NULL, 
    source VARCHAR(16) NOT NULL, 
    section VARCHAR(64), 
    title VARCHAR(300) NOT NULL, 
    content TEXT NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_knowledge_entries PRIMARY KEY (id), 
    CONSTRAINT fk_knowledge_entries_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE CASCADE
);

CREATE INDEX ix_knowledge_entries_business_id ON knowledge_entries (business_id);

CREATE TABLE appointments (
    business_id UUID NOT NULL, 
    contact_id UUID, 
    service_name VARCHAR(120) NOT NULL, 
    starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    ends_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    status VARCHAR(32) NOT NULL, 
    customer_name VARCHAR(200) NOT NULL, 
    customer_email VARCHAR(320), 
    customer_phone VARCHAR(32), 
    notes TEXT, 
    manage_token_hash VARCHAR(64) NOT NULL, 
    cancelled_at TIMESTAMP WITH TIME ZONE, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_appointments PRIMARY KEY (id), 
    CONSTRAINT fk_appointments_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE CASCADE, 
    CONSTRAINT fk_appointments_contact_id_contacts FOREIGN KEY(contact_id) REFERENCES contacts (id) ON DELETE SET NULL, 
    CONSTRAINT uq_appointments_manage_token_hash UNIQUE (manage_token_hash), 
    CONSTRAINT ck_appointments_appointmentstatus CHECK (status IN ('pending', 'confirmed', 'cancelled', 'completed', 'no_show'))
);

CREATE INDEX ix_appointments_business_start ON appointments (business_id, starts_at);

CREATE UNIQUE INDEX uq_appointments_business_start_active ON appointments (business_id, starts_at) WHERE status IN ('pending', 'confirmed');

CREATE TABLE chat_conversations (
    business_id UUID NOT NULL, 
    session_token_hash VARCHAR(64) NOT NULL, 
    contact_id UUID, 
    message_count INTEGER NOT NULL, 
    lead_captured BOOLEAN NOT NULL, 
    visitor_hash VARCHAR(64), 
    started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    last_message_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_chat_conversations PRIMARY KEY (id), 
    CONSTRAINT fk_chat_conversations_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE CASCADE, 
    CONSTRAINT fk_chat_conversations_contact_id_contacts FOREIGN KEY(contact_id) REFERENCES contacts (id) ON DELETE SET NULL, 
    CONSTRAINT uq_chat_conversations_session_token_hash UNIQUE (session_token_hash)
);

CREATE INDEX ix_chat_conversations_business_id ON chat_conversations (business_id);

CREATE INDEX ix_chat_conversations_last_message_at ON chat_conversations (last_message_at);

CREATE TABLE contact_activities (
    contact_id UUID NOT NULL, 
    type VARCHAR(32) NOT NULL, 
    body TEXT, 
    data JSONB NOT NULL, 
    created_by UUID, 
    occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_contact_activities PRIMARY KEY (id), 
    CONSTRAINT fk_contact_activities_contact_id_contacts FOREIGN KEY(contact_id) REFERENCES contacts (id) ON DELETE CASCADE, 
    CONSTRAINT fk_contact_activities_created_by_users FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT ck_contact_activities_activitytype CHECK (type IN ('note', 'call', 'email', 'meeting', 'stage_change', 'form_submission', 'booking', 'chat'))
);

CREATE INDEX ix_contact_activities_contact_id ON contact_activities (contact_id);

CREATE TABLE chat_messages (
    conversation_id UUID NOT NULL, 
    role VARCHAR(16) NOT NULL, 
    content TEXT NOT NULL, 
    strategy VARCHAR(16), 
    sources JSONB NOT NULL, 
    model VARCHAR(128), 
    prompt_tokens INTEGER NOT NULL, 
    completion_tokens INTEGER NOT NULL, 
    latency_ms INTEGER NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_chat_messages PRIMARY KEY (id), 
    CONSTRAINT fk_chat_messages_conversation_id_chat_conversations FOREIGN KEY(conversation_id) REFERENCES chat_conversations (id) ON DELETE CASCADE
);

CREATE INDEX ix_chat_messages_conversation_id ON chat_messages (conversation_id);

ALTER TABLE leads ADD COLUMN contact_id UUID;

ALTER TABLE leads ADD CONSTRAINT fk_leads_contact_id_contacts FOREIGN KEY(contact_id) REFERENCES contacts (id) ON DELETE SET NULL;

ALTER TABLE template_components DROP CONSTRAINT ck_template_components_componenttype;

ALTER TABLE template_components ADD CONSTRAINT ck_template_components_componenttype CHECK (component_type IN ('hero', 'about', 'services', 'gallery', 'testimonials', 'faq', 'cta', 'contact', 'map', 'footer', 'booking'));

UPDATE alembic_version SET version_num='0003' WHERE alembic_version.version_num = '0002';

COMMIT;

