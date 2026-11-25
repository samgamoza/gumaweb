"""Lead compiler (outbound engine A1): turn crawler output into private, quality-checked draft sites.

Owner-triggered publishing: nothing is published for a business until its owner claims it. The compiler builds a
**private draft** for each qualifying business (`generate_candidate`: worth a site and reachable). A draft that
passes the quality gate enters the pipeline as a prospect (`draft_ready`). The outreach email shows a preview of
it ("Your website is ready, claim it"), and the site goes live only when the owner claims and verifies
(the onboarding funnel step).

Called when a discovered business is fully known: right after enrichment, or right after discovery when no
enrichment is queued for it. Guarded by `AUTO_COMPILE_ENABLED` and a daily cap counted in Philippine time, so
build cost stays under control. Manual generation (admin batch, CLI) doesn't count toward the cap.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domains.sales import ActivityType
from app.domains.website_factory.jobs import JobKind
from app.models import Business, FactoryJob, Website
from app.services.job_queue import JobQueue

PH_TIME = timezone(timedelta(hours=8))  # Asia/Manila has no daylight saving
AUTO_COMPILE_SOURCE = "auto_compile"
AUTO_COMPILE_PRIORITY = 150  # after interactive work (default 100), before bulk backfills


def day_start(now: datetime | None = None) -> datetime:
    local = (now or datetime.now(UTC)).astimezone(PH_TIME)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def compiled_today(db: Session, now: datetime | None = None) -> int:
    payloads = db.scalars(select(FactoryJob.payload).where(
        FactoryJob.kind == JobKind.GENERATE_WEBSITE, FactoryJob.created_at >= day_start(now))).all()
    return sum(1 for p in payloads if (p or {}).get("source") == AUTO_COMPILE_SOURCE)


def consider(db: Session, settings: Settings, business: Business) -> str:
    """Queue a private draft for this business if it qualifies. Returns the decision, for job results and logs."""
    if not settings.auto_compile_enabled:
        return "disabled"
    if not business.generate_candidate:
        return "not_candidate"
    if db.scalar(select(Website.id).where(Website.business_id == business.id)):
        return "has_site"
    if compiled_today(db) >= settings.auto_compile_daily_limit:
        return "daily_cap"
    job = JobQueue(db).enqueue(
        JobKind.GENERATE_WEBSITE,
        {"business_id": str(business.id), "publish": False, "source": AUTO_COMPILE_SOURCE},
        dedupe_key=f"generate:{business.id}", priority=AUTO_COMPILE_PRIORITY)
    return "queued" if job is not None else "already_queued"


def draft_built(db: Session, website: Website) -> bool:
    """After an auto-compiled draft is generated: a draft that passes the quality gate enters the pipeline.
    One that doesn't stays out until it is improved and regenerated. Returns True when it entered."""
    from app.services.prospect_service import ProspectService  # local: prospect_service is a heavier import

    report = website.quality_report or {}
    if not report.get("publishable"):
        return False
    ProspectService(db).record(website.business_id, ActivityType.DRAFT_READY,
                               external_id=f"website:{website.id}:draft_ready",
                               data={"quality": website.quality_score, "template": report.get("template")})
    return True
