"""Customer portal API (12-customer-portal)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status

from app.api.deps import AppSettings, CustomerUser, DbSession, actor_for, human_only
from app.core.exceptions import NotFoundError
from app.models import Lead, MediaAsset, Subscription
from app.schemas.customer import (
    ChangePlanRequest,
    CustomerDashboard,
    CustomerProfileUpdate,
    LeadRead,
    MediaRead,
    SubscriptionRead,
)
from app.schemas.website import ContentBlockRead, ContentUpdate
from app.services.asset_service import AssetService
from app.services.customer_service import BillingService, CustomerService
from app.services.providers import providers
from app.services.website_service import WebsiteService

router = APIRouter(prefix="/customer", tags=["Customer Portal"])


@router.get("/dashboard", response_model=CustomerDashboard)
def dashboard(user: CustomerUser, db: DbSession, settings: AppSettings) -> CustomerDashboard:
    service = CustomerService(db, settings)
    return service.dashboard(service.for_user(user))


@router.get("/content", response_model=list[ContentBlockRead])
def get_content(user: CustomerUser, db: DbSession, settings: AppSettings) -> list:
    service = CustomerService(db, settings)
    return service.website(service.for_user(user)).contents


@router.put("/content", response_model=list[ContentBlockRead], summary="Update a content section")
def update_content(body: ContentUpdate, request: Request, user: CustomerUser, db: DbSession,
                   settings: AppSettings) -> list:
    service = CustomerService(db, settings)
    website = service.website(service.for_user(user))
    WebsiteService(db, settings).update_content(website, body.section_key, body.updates,
                                                actor_for(request, user), service.content_source(),
                                                body.republish)
    return website.contents


@router.put("/profile", response_model=CustomerDashboard, summary="Update business profile details")
def update_profile(body: CustomerProfileUpdate, request: Request, user: CustomerUser, db: DbSession,
                   settings: AppSettings) -> CustomerDashboard:
    service = CustomerService(db, settings)
    customer = service.update_profile(service.for_user(user), body, actor_for(request, user))
    return service.dashboard(customer)


@router.get("/leads", response_model=list[LeadRead])
def leads(user: CustomerUser, db: DbSession, settings: AppSettings) -> list[Lead]:
    service = CustomerService(db, settings)
    return service.leads(service.for_user(user))


@router.get("/subscription", response_model=SubscriptionRead)
def subscription(user: CustomerUser, db: DbSession, settings: AppSettings) -> Subscription:
    customer = CustomerService(db, settings).for_user(user)
    return BillingService(db).current(customer)


@router.post("/subscription", response_model=SubscriptionRead, summary="Change plan",
             dependencies=[Depends(human_only)])
def change_plan(body: ChangePlanRequest, request: Request, user: CustomerUser, db: DbSession,
                settings: AppSettings) -> Subscription:
    customer = CustomerService(db, settings).for_user(user)
    return BillingService(db).change_plan(customer, body.plan, actor_for(request, user))


# --- Media library (12-customer-portal) ------------------------------------------------------
@router.get("/media", response_model=list[MediaRead], summary="Uploaded images")
def list_media(user: CustomerUser, db: DbSession, settings: AppSettings) -> list[MediaAsset]:
    customer = CustomerService(db, settings).for_user(user)
    return list(AssetService(db, settings).uploads(customer.business))


@router.post("/media", response_model=MediaRead, status_code=status.HTTP_201_CREATED,
             summary="Upload a JPEG/PNG/WebP image (use it in the gallery or as the hero image)")
async def upload_media(user: CustomerUser, db: DbSession, settings: AppSettings, file: UploadFile = File(...),
                       alt_text: str | None = Form(None, max_length=255)) -> MediaAsset:
    customer = CustomerService(db, settings).for_user(user)
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    return AssetService(db, settings).upload(customer.business, data, alt_text)


@router.get("/media/{asset_id}/file", summary="Image bytes (for previews in the portal)")
def media_file(asset_id: uuid.UUID, user: CustomerUser, db: DbSession, settings: AppSettings) -> Response:
    customer = CustomerService(db, settings).for_user(user)
    asset = db.get(MediaAsset, asset_id)
    if asset is None or asset.business_id not in (None, customer.business_id):
        raise NotFoundError("Image not found")
    return Response(providers.storage.get_object(asset.storage_key), media_type=asset.mime_type,
                    headers={"Cache-Control": "private, max-age=3600", "Content-Security-Policy": "default-src 'none'"})


@router.delete("/media/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_media(asset_id: uuid.UUID, request: Request, user: CustomerUser, db: DbSession,
                 settings: AppSettings) -> None:
    service = CustomerService(db, settings)
    customer = service.for_user(user)
    service.remove_image_references(customer, str(asset_id), actor_for(request, user))
    AssetService(db, settings).delete_upload(customer.business, asset_id)
    db.commit()
