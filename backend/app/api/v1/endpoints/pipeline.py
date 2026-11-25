"""Outbound engine pipeline (read side). The cockpit (A6) builds on these."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import AppSettings, DbSession, StaffReader
from app.core.exceptions import NotFoundError
from app.domains.sales import ProspectStage
from app.models import Business, Prospect, ProspectActivity
from app.schemas.pipeline import ActivityRead, PipelineSummary, ProspectDetail, ProspectRow
from app.services import lead_compiler
from app.services.prospect_service import ProspectService

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
