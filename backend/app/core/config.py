"""Application settings, loaded from environment variables (12-factor)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/app/core/config.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[3]

_INSECURE_DEFAULT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Application -------------------------------------------------------
    app_name: str = "GumaWeb"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    log_json: bool = False

    # --- Persistence -------------------------------------------------------
    database_url: str = "postgresql+psycopg://gumaweb:gumaweb@localhost:5432/gumaweb"
    database_pool_size: int = 10
    database_echo: bool = False
    redis_url: str | None = None

    # --- Security ----------------------------------------------------------
    jwt_secret_key: str = _INSECURE_DEFAULT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- Public URLs -------------------------------------------------------
    frontend_url: str = "http://localhost:3000"
    api_public_url: str = "http://localhost:8000"
    # {subdomain} is substituted. Production: https://{subdomain}.gumaweb.io/
    site_url_template: str = "http://localhost:8080/{subdomain}/"
    public_site_domain: str = "gumaweb.io"

    # --- Custom domains (Phase 5) ------------------------------------------
    # Owners point www.<domain> here (CNAME) and the bare domain at custom_domain_ipv4 (A record),
    # both reaching the TLS edge (Caddy on-demand certificates, see infrastructure/caddy).
    custom_domain_cname_target: str = "domains.gumaweb.io"
    custom_domain_ipv4: str | None = None
    custom_domain_scheme: Literal["https", "http"] = "https"
    max_custom_domains: int = 3
    domain_pending_days: int = 7  # unverified domains are released after this, so nobody can squat a name
    domain_recheck_hours: int = 24

    # --- Business email (Phase 5) --------------------------------------------
    # "stalwart": self-hosted Stalwart mail server managed through its JMAP API; "disabled": email is
    # honestly unavailable (endpoints answer 503).
    mail_provider: Literal["disabled", "stalwart"] = "disabled"
    stalwart_url: str = "http://stalwart:8080"
    stalwart_username: str = "admin"
    stalwart_secret: str | None = None
    mail_client_host: str = "mail.gumaweb.io"  # what owners enter in their mail apps (IMAP/SMTP)
    mailbox_quota_mb: int = 2048

    # --- Filesystem / storage ---------------------------------------------
    templates_dir: Path = REPO_ROOT / "templates"
    generated_sites_dir: Path = REPO_ROOT / "generated-sites"
    storage_backend: Literal["local", "s3"] = "local"
    s3_endpoint_url: str | None = None
    s3_bucket: str = "gumaweb-sites"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"

    # --- Notifications -----------------------------------------------------
    email_backend: Literal["console", "smtp"] = "console"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = False
    email_from: str = "GumaWeb <hello@gumaweb.io>"
    sms_backend: Literal["console"] = "console"

    # --- Business rules ----------------------------------------------------
    score_generate_threshold: int = 60
    claim_token_ttl_hours: int = 48
    claim_max_verification_attempts: int = 5
    claim_manual_review_threshold: int = 60
    claim_rate_limit_per_hour: int = 5
    default_country_code: str = "63"  # Philippines

    # --- AI content (Phase 2; local, OpenAI-compatible: vLLM / Ollama / llama.cpp) ---
    ai_enabled: bool = False
    llm_base_url: str = "http://localhost:8001/v1"
    llm_api_key: str | None = None
    llm_primary_model: str = "qwen2.5-14b-instruct"  # copywriting (doc 07 primary)
    llm_secondary_model: str = "deepseek-r1-distill-qwen-14b"  # review / rewrite (doc 07 secondary)
    ai_review_enabled: bool = True
    llm_timeout_seconds: float = 120.0
    llm_chat_timeout_seconds: float = 45.0  # live website chat; batch generation uses llm_timeout_seconds
    llm_json_mode: bool = True
    # Content quality gates for AI copy (doc 07). Flesch reading ease target; the effective gate per section
    # is min(target, readability of the template copy it would replace) - AI copy may never read worse.
    content_min_readability: float = 50.0
    content_max_spam: int = 10
    embedding_model: str = "BAAI/bge-m3"

    # --- Image factory (Phase 2) ----------------------------------------------
    # procedural: deterministic SVG artwork in the template palette (zero cost, always available)
    # http: OpenAI-compatible /images/generations on a local FLUX/SDXL server (LocalAI, ComfyUI bridge)
    image_backend: Literal["procedural", "http"] = "procedural"
    image_api_url: str = "http://localhost:8002/v1"
    image_model: str = "black-forest-labs/FLUX.1-schnell"
    image_library_variants: int = 3  # distinct library images per (industry, category) before reuse
    max_upload_mb: int = 5

    # --- Guma OS integration (Phase 4) ---------------------------------------
    # Shared secret the telephony gateway (Asterisk + Whisper + Piper adapter) sends as X-Voice-Gateway-Token.
    voice_gateway_token: str | None = None
    webhook_allow_private: bool = False  # True only for local development (targets on localhost / LAN)
    webhook_timeout_seconds: float = 10.0
    webhook_max_attempts: int = 6
    webhook_disable_after_failures: int = 20

    # --- Bootstrap ---------------------------------------------------------
    first_admin_email: str = "admin@gumaweb.io"
    first_admin_password: str = "ChangeMe!2026"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _enforce_production_secrets(self) -> Settings:
        if self.environment == "production" and self.jwt_secret_key == _INSECURE_DEFAULT_SECRET:
            raise ValueError("JWT_SECRET_KEY must be set in production")
        return self

    def site_url(self, subdomain: str) -> str:
        return self.site_url_template.format(subdomain=subdomain)


@lru_cache
def get_settings() -> Settings:
    return Settings()
