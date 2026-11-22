"""Phase 5 (Digital Presence Factory) customer API: presence kit, images and downloads."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.api.deps import AppSettings, CustomerUser, DbSession
from app.models import Business
from app.services.customer_service import CustomerService
from app.services.presence_service import PresenceService

router = APIRouter(prefix="/customer/presence", tags=["Customer Portal: Digital presence"])


class ChecklistUpdate(BaseModel):
    step: str
    done: bool


def _business(user, db, settings) -> Business:
    customer = CustomerService(db, settings).for_user(user)
    return db.get(Business, customer.business_id)


@router.get("", summary="Presence kit (locked parts withheld by plan)")
def presence(user: CustomerUser, db: DbSession, settings: AppSettings) -> dict[str, Any]:
    return PresenceService(db, settings).view(_business(user, db, settings))


@router.post("/regenerate", summary="Rebuild the kit from the current website")
def regenerate(user: CustomerUser, db: DbSession, settings: AppSettings) -> dict[str, Any]:
    service = PresenceService(db, settings)
    business = _business(user, db, settings)
    service.generate(business)
    db.commit()
    return service.view(business)


@router.get("/assets/{name}.png", summary="One kit image (rendered on first request, then cached)",
            response_class=Response, responses={200: {"content": {"image/png": {}}}})
def asset(name: str, user: CustomerUser, db: DbSession, settings: AppSettings) -> Response:
    data = PresenceService(db, settings).asset(_business(user, db, settings), name)
    return Response(data, media_type="image/png", headers={
        "Cache-Control": "private, max-age=300",
        "Content-Disposition": f'inline; filename="{name}.png"'})


@router.get("/download.zip", summary="Everything in one ZIP (presence kit plans)", response_class=Response,
            responses={200: {"content": {"application/zip": {}}}})
def download(user: CustomerUser, db: DbSession, settings: AppSettings) -> Response:
    business = _business(user, db, settings)
    data = PresenceService(db, settings).zip_kit(business)
    return Response(data, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{business.slug}-presence-kit.zip"'})


@router.put("/checklist", summary="Mark a Google Business Profile step done or not done")
def checklist(body: ChecklistUpdate, user: CustomerUser, db: DbSession, settings: AppSettings) -> dict[str, Any]:
    service = PresenceService(db, settings)
    business = _business(user, db, settings)
    service.set_step(business, body.step, body.done)
    return service.view(business)
