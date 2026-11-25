from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request, Response, status

from app.api.deps import Admin, AppSettings, DbSession, Staff, StaffReader, actor_for
from app.core.exceptions import NotFoundError
from app.domains.outreach.suppression import SuppressionKind
from app.models import OutreachCampaign, OutreachSuppression
from app.repositories.repositories import OutreachRepository
from app.schemas.outreach import (
    CampaignCreate,
    CampaignRead,
    CampaignStats,
    DispatchResult,
    LaunchResult,
    SuppressionCheck,
    SuppressionCreate,
    SuppressionRead,
)
from app.services.outreach_service import OutreachService
from app.services.suppression_service import SuppressionService

router = APIRouter(prefix="/outreach", tags=["Outreach"])


@router.get("/campaigns", response_model=list[CampaignRead])
def list_campaigns(_: StaffReader, db: DbSession) -> list[OutreachCampaign]:
    return list(OutreachRepository(db).all())


@router.post("/campaigns", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
def create_campaign(body: CampaignCreate, request: Request, user: Staff, db: DbSession,
                    settings: AppSettings) -> OutreachCampaign:
    service = OutreachService(db, settings)
    campaign = service.create(body, actor_for(request, user))
    if body.launch:
        service.launch(campaign, actor_for(request, user))
    return campaign


@router.post("/campaign", response_model=LaunchResult, status_code=status.HTTP_201_CREATED,
             summary="Send Campaign: create, enroll targets and schedule the sequence in one call")
def send_campaign(body: CampaignCreate, request: Request, user: Staff, db: DbSession,
                  settings: AppSettings) -> LaunchResult:
    service = OutreachService(db, settings)
    campaign = service.create(body, actor_for(request, user))
    return service.launch(campaign, actor_for(request, user))


@router.get("/campaigns/{campaign_id}", response_model=CampaignRead)
def get_campaign(campaign_id: uuid.UUID, _: StaffReader, db: DbSession) -> OutreachCampaign:
    return OutreachRepository(db).get_or_404(campaign_id)


@router.post("/campaigns/{campaign_id}/launch", response_model=LaunchResult)
def launch_campaign(campaign_id: uuid.UUID, request: Request, user: Staff, db: DbSession,
                    settings: AppSettings) -> LaunchResult:
    campaign = OutreachRepository(db).get_or_404(campaign_id)
    return OutreachService(db, settings).launch(campaign, actor_for(request, user))


@router.post("/campaigns/{campaign_id}/dispatch", response_model=DispatchResult,
             summary="Send all messages of this campaign that are due now")
def dispatch_campaign(campaign_id: uuid.UUID, _: Staff, db: DbSession, settings: AppSettings) -> DispatchResult:
    campaign = OutreachRepository(db).get_or_404(campaign_id)
    return OutreachService(db, settings).dispatch_due(campaign)


@router.get("/campaigns/{campaign_id}/stats", response_model=CampaignStats)
def campaign_stats(campaign_id: uuid.UUID, _: StaffReader, db: DbSession, settings: AppSettings) -> CampaignStats:
    campaign = OutreachRepository(db).get_or_404(campaign_id)
    return OutreachService(db, settings).stats(campaign)


# --- Do-not-contact list ---------------------------------------------------------------------------
# Any staff member may add a suppression (the safe direction). Only an admin may remove one.


@router.get("/suppressions", response_model=list[SuppressionRead])
def list_suppressions(_: StaffReader, db: DbSession, kind: SuppressionKind | None = None) -> list[OutreachSuppression]:
    return list(SuppressionService(db).list(kind))


@router.post("/suppressions", response_model=SuppressionRead,
             summary="Add an email or a whole domain to the do-not-contact list (idempotent)")
def add_suppression(body: SuppressionCreate, request: Request, response: Response, user: Staff,
                    db: DbSession) -> OutreachSuppression:
    entry, created = SuppressionService(db).add(body.kind, body.value, body.reason, actor_for(request, user),
                                                note=body.note)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return entry


@router.delete("/suppressions/{kind}/{value}", status_code=status.HTTP_204_NO_CONTENT)
def remove_suppression(kind: SuppressionKind, value: str, request: Request, user: Admin, db: DbSession) -> None:
    if not SuppressionService(db).remove(kind, value, actor_for(request, user)):
        raise NotFoundError("Suppression not found")


@router.get("/suppressions/check", response_model=SuppressionCheck,
            summary="Would outreach to this email be blocked, and by which entry?")
def check_suppression(_: StaffReader, db: DbSession, email: str = Query(max_length=320)) -> SuppressionCheck:
    match = SuppressionService(db).match(email)
    return SuppressionCheck(email=email, suppressed=match is not None,
                            matched_kind=match.kind if match else None, matched_value=match.value if match else None)
