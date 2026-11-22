from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import AppSettings, DbSession, Staff, StaffReader, actor_for
from app.models import OutreachCampaign
from app.repositories.repositories import OutreachRepository
from app.schemas.outreach import CampaignCreate, CampaignRead, CampaignStats, DispatchResult, LaunchResult
from app.services.outreach_service import OutreachService

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
