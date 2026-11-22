from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from app.api.deps import AppSettings, DbSession, Pagination, Staff, StaffReader, actor_for
from app.core.exceptions import ValidationFailedError
from app.domains.business_discovery.enums import DiscoverySource
from app.domains.business_discovery.sources import CsvSource, JsonSource
from app.models import Business, BusinessProfile, DiscoveryRun
from app.repositories.repositories import BusinessRepository, DiscoveryRunRepository
from app.schemas.business import (
    BusinessCreate,
    BusinessFilters,
    BusinessProfileRead,
    BusinessProfileUpdate,
    BusinessRead,
    BusinessUpdate,
    DiscoveryRunRead,
)
from app.schemas.common import Page
from app.services.business_service import BusinessService, ProfileService

router = APIRouter(prefix="/businesses", tags=["Businesses"])

MAX_IMPORT_BYTES = 10 * 1024 * 1024


@router.get("", response_model=Page[BusinessRead])
def list_businesses(
    _: StaffReader, db: DbSession, settings: AppSettings, paging: Pagination,
    filters: Annotated[BusinessFilters, Depends()],
) -> Page[BusinessRead]:
    items, total = BusinessService(db, settings).list(filters, paging.page, paging.page_size)
    return Page(items=items, total=total, page=paging.page, page_size=paging.page_size)


@router.post("", response_model=BusinessRead, status_code=status.HTTP_201_CREATED)
def create_business(body: BusinessCreate, request: Request, user: Staff, db: DbSession,
                    settings: AppSettings) -> Business:
    return BusinessService(db, settings).create(body, actor_for(request, user))


@router.post("/import", response_model=DiscoveryRunRead, status_code=status.HTTP_201_CREATED,
             summary="Bulk import from a CSV or JSON file (discovery batch)")
async def import_businesses(request: Request, user: Staff, db: DbSession, settings: AppSettings,
                            file: UploadFile = File(...)) -> DiscoveryRun:
    raw = await file.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValidationFailedError("Import file exceeds 10 MB")
    text = raw.decode("utf-8-sig", errors="replace")
    name = (file.filename or "").lower()
    source = JsonSource(text) if name.endswith(".json") else CsvSource(text)
    return BusinessService(db, settings).import_records(source.fetch(), DiscoverySource.CSV_IMPORT,
                                                        actor_for(request, user))


@router.get("/discovery-runs", response_model=list[DiscoveryRunRead])
def discovery_runs(_: StaffReader, db: DbSession) -> list[DiscoveryRun]:
    return list(DiscoveryRunRepository(db).recent())


@router.get("/{business_id}", response_model=BusinessRead)
def get_business(business_id: uuid.UUID, _: StaffReader, db: DbSession) -> Business:
    return BusinessRepository(db).get_or_404(business_id)


@router.patch("/{business_id}", response_model=BusinessRead)
def update_business(business_id: uuid.UUID, body: BusinessUpdate, request: Request, user: Staff,
                    db: DbSession, settings: AppSettings) -> Business:
    business = BusinessRepository(db).get_or_404(business_id)
    return BusinessService(db, settings).update(business, body, actor_for(request, user))


@router.delete("/{business_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Archive a business")
def archive_business(business_id: uuid.UUID, request: Request, user: Staff, db: DbSession,
                     settings: AppSettings) -> None:
    business = BusinessRepository(db).get_or_404(business_id)
    BusinessService(db, settings).archive(business, actor_for(request, user))


@router.post("/{business_id}/score", response_model=BusinessRead, summary="Recompute opportunity score")
def score_business(business_id: uuid.UUID, _: Staff, db: DbSession, settings: AppSettings) -> Business:
    business = BusinessRepository(db).get_or_404(business_id)
    return BusinessService(db, settings).rescore(business)


@router.post("/{business_id}/profile", response_model=BusinessProfileRead,
             summary="Build (or rebuild) the business intelligence profile")
def build_profile(business_id: uuid.UUID, _: Staff, db: DbSession, settings: AppSettings,
                  force: bool = False) -> BusinessProfile:
    business = BusinessRepository(db).get_or_404(business_id)
    profile = ProfileService(db, settings).ensure(business, force=force)
    db.commit()
    return profile


@router.get("/{business_id}/profile", response_model=BusinessProfileRead)
def get_profile(business_id: uuid.UUID, _: StaffReader, db: DbSession, settings: AppSettings) -> BusinessProfile:
    business = BusinessRepository(db).get_or_404(business_id)
    if business.profile is None:
        profile = ProfileService(db, settings).ensure(business)
        db.commit()
        return profile
    return business.profile


@router.patch("/{business_id}/profile", response_model=BusinessProfileRead)
def update_profile(business_id: uuid.UUID, body: BusinessProfileUpdate, _: Staff, db: DbSession,
                   settings: AppSettings) -> BusinessProfile:
    business = BusinessRepository(db).get_or_404(business_id)
    return ProfileService(db, settings).update(business, body)
