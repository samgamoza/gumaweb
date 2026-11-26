"""Outbound engine pipeline (read side). The cockpit (A6) builds on these."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import Admin, AppSettings, DbSession, StaffReader, actor_for
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.domains.audit.actions import AuditAction
from app.domains.sales import ProspectStage
from app.domains.sales.playbooks import PlaybookError, validate_steps
from app.domains.website_factory.jobs import JobKind
from app.models import (
    Business,
    DraftPreview,
    Playbook,
    PlaybookEnrollment,
    Prospect,
    ProspectActivity,
    ProspectTask,
    Website,
)
from app.models.sales import EnrollmentStatus
from app.schemas.pipeline import (
    ActivityRead,
    DraftRow,
    PipelineSummary,
    PlaybookRead,
    PlaybookStepStats,
    PlaybookUpdate,
    ProspectDetail,
    ProspectRow,
    TaskRead,
)
from app.services import lead_compiler
from app.services.draft_prep import DraftPrep
from app.services.job_queue import JobQueue
from app.services.outbound_engine import OutboundEngine
from app.services.prospect_service import ProspectService
from app.services.support import audit

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])


def _row(prospect: Prospect, business: Business) -> ProspectRow:
    return ProspectRow(business_id=business.id, business_name=business.name, city=business.city,
                       industry=business.industry, stage=prospect.stage, score=prospect.score,
                       score_reasons=prospect.score_reasons or [], channels=prospect.channels or [],
                       last_touch_at=prospect.last_touch_at, stage_changed_at=prospect.stage_changed_at)


@router.get("/summary", response_model=PipelineSummary)
def summary(_: StaffReader, db: DbSession, settings: AppSettings) -> PipelineSummary:
    counts = dict(db.execute(select(Prospect.stage, func.count()).group_by(Prospect.stage)).all())
    ready = db.scalar(select(func.count()).select_from(ProspectService(db).ready_query().subquery())) or 0
    return PipelineSummary(
        stages={stage.value: counts.get(stage, 0) for stage in ProspectStage}, ready=ready,
        auto_compile_enabled=settings.auto_compile_enabled, auto_compiled_today=lead_compiler.compiled_today(db),
        auto_compile_daily_limit=settings.auto_compile_daily_limit)


@router.get("/prospects", response_model=list[ProspectRow], summary="Prospects, highest outbound priority first")
def prospects(_: StaffReader, db: DbSession, stage: ProspectStage | None = None,
              ready: bool = Query(False, description="only prospects the outbound engine may work now"),
              limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)) -> list[ProspectRow]:
    if ready:
        stmt = ProspectService(db).ready_query()
    else:
        stmt = select(Prospect).order_by(Prospect.score.desc().nulls_last(), Prospect.created_at)
    if stage is not None:
        stmt = stmt.where(Prospect.stage == stage)
    stmt = stmt.add_columns(Business).join(Business, Business.id == Prospect.business_id).limit(limit).offset(offset)
    return [_row(prospect, business) for prospect, business in db.execute(stmt).all()]


@router.get("/prospects/{business_id}", response_model=ProspectDetail)
def prospect(business_id: uuid.UUID, _: StaffReader, db: DbSession) -> ProspectDetail:
    found = ProspectService(db).for_business(business_id)
    if found is None:
        raise NotFoundError("Prospect not found")
    activities = db.scalars(select(ProspectActivity).where(ProspectActivity.prospect_id == found.id)
                            .order_by(ProspectActivity.occurred_at.desc(), ProspectActivity.created_at.desc()))
    row = _row(found, db.get(Business, business_id))
    return ProspectDetail(**row.model_dump(), timeline=[ActivityRead.model_validate(a) for a in activities])


# --- Playbooks and the outbound engine (A2) ------------------------------------------------------
def _playbook_read(db, playbook: Playbook) -> PlaybookRead:
    enrollments = db.scalars(select(PlaybookEnrollment).where(PlaybookEnrollment.playbook_id == playbook.id)).all()
    by_status: dict[str, int] = {s.value: 0 for s in EnrollmentStatus}
    stats = {s["key"]: PlaybookStepStats(key=s["key"], channel=s["channel"], when=s["when"]) for s in playbook.steps}
    for enrollment in enrollments:
        by_status[enrollment.status.value] += 1
        for key, outcome in (enrollment.steps_done or {}).items():
            if key in stats and outcome.get("status") in ("sent", "skipped", "failed"):
                setattr(stats[key], outcome["status"], getattr(stats[key], outcome["status"]) + 1)
    return PlaybookRead(id=playbook.id, name=playbook.name, active=playbook.active, max_days=playbook.max_days,
                        steps=playbook.steps, enrollments=by_status, step_stats=list(stats.values()))


@router.get("/playbooks", response_model=list[PlaybookRead])
def playbooks(_: StaffReader, db: DbSession, settings: AppSettings) -> list[PlaybookRead]:
    OutboundEngine(db, settings).ensure_default_playbook()
    db.commit()
    return [_playbook_read(db, p) for p in db.scalars(select(Playbook).order_by(Playbook.created_at))]


@router.patch("/playbooks/{playbook_id}", response_model=PlaybookRead)
def update_playbook(playbook_id: uuid.UUID, data: PlaybookUpdate, user: Admin, request: Request,
                    db: DbSession) -> PlaybookRead:
    playbook = db.get(Playbook, playbook_id)
    if playbook is None:
        raise NotFoundError("Playbook not found")
    changes = data.model_dump(exclude_none=True)
    if "steps" in changes:
        try:
            changes["steps"] = validate_steps(changes["steps"])
        except PlaybookError as exc:
            raise ValidationFailedError(str(exc)) from exc
    for field, value in changes.items():
        setattr(playbook, field, value)
    audit(db, actor_for(request, user), AuditAction.PLAYBOOK_UPDATED, "playbook", playbook.id,
          {"fields": sorted(changes)})
    db.commit()
    return _playbook_read(db, playbook)


@router.post("/outbound/run", status_code=status.HTTP_202_ACCEPTED,
             summary="Queue one outbound engine pass now (runs even while the engine is switched off)")
def run_outbound(_: Admin, db: DbSession) -> dict[str, str | None]:
    job = JobQueue(db).enqueue(JobKind.RUN_OUTBOUND, {"force": True}, dedupe_key="outbound", priority=100)
    db.commit()
    return {"status": "queued" if job else "already_running", "job_id": str(job.id) if job else None}


@router.get("/tasks", response_model=list[TaskRead], summary="Follow-up tasks for people, oldest due first")
def tasks(_: StaffReader, db: DbSession, open_only: bool = Query(True, alias="open"),
          limit: int = Query(100, ge=1, le=500)) -> list[TaskRead]:
    stmt = select(ProspectTask).order_by(ProspectTask.due_at).limit(limit)
    if open_only:
        stmt = stmt.where(ProspectTask.done_at.is_(None))
    return [TaskRead.model_validate(t) for t in db.scalars(stmt)]


# --- A7b: private drafts' outreach readiness -------------------------------------------------------------
def _draft_row(prep: DraftPrep, row: DraftPreview, website: Website, business: Business) -> DraftRow:
    return DraftRow(website_id=website.id, business_id=business.id, business_name=business.name,
                    subdomain=website.subdomain, ready=row.ready, approved=row.approved_by is not None,
                    issues=(row.review or {}).get("issues", []), reviewed_at=row.reviewed_at,
                    images=prep.image_urls(row), capture_error=row.capture_error)


@router.get("/drafts", response_model=list[DraftRow], summary="Private drafts and their polish review")
def list_drafts(_: StaffReader, db: DbSession, settings: AppSettings, held: bool | None = None,
                limit: int = Query(100, ge=1, le=500)) -> list[DraftRow]:
    stmt = (select(DraftPreview, Website, Business).join(Website, Website.id == DraftPreview.website_id)
            .join(Business, Business.id == Website.business_id).where(Website.is_claimed.is_(False))
            .order_by(DraftPreview.reviewed_at.desc()).limit(limit))
    if held is not None:
        stmt = stmt.where(DraftPreview.ready.is_(not held))
    prep = DraftPrep(db, settings)
    return [_draft_row(prep, row, website, business) for row, website, business in db.execute(stmt).all()]


def _website(db, website_id: uuid.UUID) -> Website:
    website = db.get(Website, website_id)
    if website is None or website.is_claimed:
        raise NotFoundError("Draft not found")
    return website


@router.post("/drafts/{website_id}/prepare", response_model=DraftRow,
             summary="Re-run the polish review (and capture) after fixing a draft")
def prepare_draft(website_id: uuid.UUID, _: Admin, db: DbSession, settings: AppSettings) -> DraftRow:
    website = _website(db, website_id)
    prep = DraftPrep(db, settings)
    row = prep.prepare(website)
    db.commit()
    return _draft_row(prep, row, website, website.business)


@router.post("/drafts/{website_id}/approve", response_model=DraftRow,
             summary="Approve a held draft for outreach despite its review")
def approve_draft(website_id: uuid.UUID, user: Admin, request: Request, db: DbSession,
                  settings: AppSettings) -> DraftRow:
    website = _website(db, website_id)
    prep = DraftPrep(db, settings)
    row = prep.approve(website, actor_for(request, user))
    audit(db, actor_for(request, user), AuditAction.DRAFT_APPROVED, "website", website.id,
          {"issues": (row.review or {}).get("issues", [])})
    db.commit()
    return _draft_row(prep, row, website, website.business)
