"""Discovery campaigns: saved, re-runnable sweeps with run history and live progress (port step 5)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import Admin, AppSettings, DbSession, Staff, StaffReader, actor_for
from app.core.exceptions import NotFoundError
from app.models import DiscoveryCampaign, DiscoveryRun
from app.schemas.business import CampaignRead, CampaignWrite, DiscoveryRunRead
from app.services.campaign_service import CampaignService

router = APIRouter(prefix="/discovery", tags=["Discovery"])


def _read(service: CampaignService, campaign: DiscoveryCampaign) -> CampaignRead:
    runs = service.runs(campaign.id, limit=1)
    return CampaignRead.model_validate(campaign).model_copy(
        update={"last_run": DiscoveryRunRead.model_validate(runs[0]) if runs else None})


def _run_or_404(db: DbSession, run_id: uuid.UUID) -> DiscoveryRun:
    run = db.get(DiscoveryRun, run_id)
    if run is None:
        raise NotFoundError("Discovery run not found")
    return run


@router.get("/campaigns", response_model=list[CampaignRead])
def list_campaigns(_: StaffReader, db: DbSession, settings: AppSettings) -> list[CampaignRead]:
    service = CampaignService(db, settings)
    return [_read(service, c) for c in service.list()]


@router.post("/campaigns", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
def create_campaign(body: CampaignWrite, request: Request, user: Staff, db: DbSession,
                    settings: AppSettings) -> CampaignRead:
    service = CampaignService(db, settings)
    return _read(service, service.create(body.model_dump(), actor_for(request, user)))


@router.get("/campaigns/{campaign_id}", response_model=CampaignRead)
def get_campaign(campaign_id: uuid.UUID, _: StaffReader, db: DbSession, settings: AppSettings) -> CampaignRead:
    service = CampaignService(db, settings)
    return _read(service, service.get(campaign_id))


@router.put("/campaigns/{campaign_id}", response_model=CampaignRead)
def update_campaign(campaign_id: uuid.UUID, body: CampaignWrite, request: Request, user: Staff, db: DbSession,
                    settings: AppSettings) -> CampaignRead:
    service = CampaignService(db, settings)
    return _read(service, service.update(service.get(campaign_id), body.model_dump(), actor_for(request, user)))


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a campaign (its past runs are kept)")
def delete_campaign(campaign_id: uuid.UUID, request: Request, user: Admin, db: DbSession,
                    settings: AppSettings) -> None:
    service = CampaignService(db, settings)
    service.delete(service.get(campaign_id), actor_for(request, user))


@router.post("/campaigns/{campaign_id}/run", response_model=DiscoveryRunRead, status_code=status.HTTP_202_ACCEPTED,
             summary="Start a sweep; poll GET /discovery/runs/{id} for progress. One sweep at a time (409).")
def run_campaign(campaign_id: uuid.UUID, request: Request, user: Staff, db: DbSession,
                 settings: AppSettings) -> DiscoveryRun:
    service = CampaignService(db, settings)
    return service.start(service.get(campaign_id), actor_for(request, user))


@router.get("/campaigns/{campaign_id}/runs", response_model=list[DiscoveryRunRead])
def campaign_runs(campaign_id: uuid.UUID, _: StaffReader, db: DbSession, settings: AppSettings) -> list[DiscoveryRun]:
    service = CampaignService(db, settings)
    service.get(campaign_id)
    return list(service.runs(campaign_id))


@router.get("/runs/{run_id}", response_model=DiscoveryRunRead)
def get_run(run_id: uuid.UUID, _: StaffReader, db: DbSession) -> DiscoveryRun:
    return _run_or_404(db, run_id)


@router.post("/runs/{run_id}/cancel", response_model=DiscoveryRunRead,
             summary="Stop after the current query; what was found so far is still imported")
def cancel_run(run_id: uuid.UUID, request: Request, user: Staff, db: DbSession, settings: AppSettings) -> DiscoveryRun:
    return CampaignService(db, settings).cancel(_run_or_404(db, run_id), actor_for(request, user))
