"""Factory job queue vocabulary and retry policy (pure domain rules)."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum


class JobKind(StrEnum):
    GENERATE_WEBSITE = "generate_website"
    REGENERATE_WEBSITE = "regenerate_website"
    PUBLISH_WEBSITE = "publish_website"
    RUN_AUTOMATION = "run_automation"  # Phase 4
    DELIVER_WEBHOOK = "deliver_webhook"  # Phase 4
    SUMMARIZE_CALL = "summarize_call"  # Phase 4
    GENERATE_PRESENCE = "generate_presence"  # Phase 5
    CHECK_DOMAINS = "check_domains"  # Phase 5
    DISCOVER_BUSINESSES = "discover_businesses"  # Guma OS port step 3
    ENRICH_BUSINESS = "enrich_business"  # Guma OS port step 4
    RUN_CAMPAIGN = "run_campaign"  # Guma OS port step 5
    SCRUB_SUPPRESSION = "scrub_suppression"  # Guma OS port step 6


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


ACTIVE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING)

BASE_BACKOFF_SECONDS = 30
MAX_BACKOFF_SECONDS = 3600
STALE_LOCK_AFTER = timedelta(minutes=15)


def retry_delay(attempts: int) -> timedelta:
    """Exponential backoff: 30s, 60s, 120s ... capped at one hour."""
    return timedelta(seconds=min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * 2 ** max(0, attempts - 1)))
