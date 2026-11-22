from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import Admin, AppSettings, DbSession, Staff, StaffReader, actor_for
from app.models import Template, TemplateComponent
from app.repositories.repositories import TemplateComponentRepository, TemplateRepository
from app.schemas.template import (
    TemplateComponentRead,
    TemplateCreate,
    TemplateRead,
    TemplateSyncResult,
    TemplateUpdate,
)
from app.services.template_service import TemplateService

router = APIRouter(prefix="/templates", tags=["Templates"])


@router.get("", response_model=list[TemplateRead])
def list_templates(_: StaffReader, db: DbSession, settings: AppSettings,
                   category: str | None = None) -> list[Template]:
    return list(TemplateService(db, settings).list(category))


@router.post("", response_model=TemplateRead, status_code=status.HTTP_201_CREATED)
def create_template(body: TemplateCreate, request: Request, user: Admin, db: DbSession,
                    settings: AppSettings) -> Template:
    return TemplateService(db, settings).create(body, actor_for(request, user))


@router.post("/sync", response_model=TemplateSyncResult,
             summary="Load template manifests and components from the /templates directory")
def sync_templates(request: Request, user: Staff, db: DbSession, settings: AppSettings) -> TemplateSyncResult:
    return TemplateService(db, settings).sync_from_disk(actor_for(request, user))


@router.get("/components", response_model=list[TemplateComponentRead])
def list_components(_: StaffReader, db: DbSession) -> list[TemplateComponent]:
    return list(TemplateComponentRepository(db).all())


@router.get("/{template_id}", response_model=TemplateRead)
def get_template(template_id: uuid.UUID, _: StaffReader, db: DbSession) -> Template:
    return TemplateRepository(db).get_or_404(template_id)


@router.patch("/{template_id}", response_model=TemplateRead)
def update_template(template_id: uuid.UUID, body: TemplateUpdate, request: Request, user: Admin,
                    db: DbSession, settings: AppSettings) -> Template:
    template = TemplateRepository(db).get_or_404(template_id)
    return TemplateService(db, settings).update(template, body, actor_for(request, user))
