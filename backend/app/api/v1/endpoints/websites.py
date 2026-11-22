from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import AppSettings, DbSession, Pagination, Staff, StaffReader, actor_for
from app.core.exceptions import PermissionDeniedError
from app.domains.customers.enums import UserRole
from app.domains.website_factory.enums import ContentSource, WebsiteStatus
from app.models import Deployment, Website
from app.repositories.repositories import WebsiteRepository
from app.schemas.common import Page
from app.schemas.website import (
    BatchResult,
    BlueprintRead,
    ContentBlockRead,
    ContentUpdate,
    DeploymentRead,
    GenerateBatchRequest,
    GenerateWebsiteRequest,
    PublishRequest,
    RegenerateWebsiteRequest,
    SeoRead,
    WebsiteRead,
    WebsiteSummary,
)
from app.services.website_service import WebsiteService

router = APIRouter(prefix="/websites", tags=["Websites"])


def _summary(website: Website) -> WebsiteSummary:
    return WebsiteSummary.model_validate(
        {**WebsiteRead.model_validate(website).model_dump(), "business_name": website.business.name,
         "template_slug": website.template.slug if website.template else None}
    )


@router.get("", response_model=Page[WebsiteSummary])
def list_websites(_: StaffReader, db: DbSession, settings: AppSettings, paging: Pagination,
                  status_filter: WebsiteStatus | None = None) -> Page[WebsiteSummary]:
    items, total = WebsiteService(db, settings).list(status_filter, paging.page, paging.page_size)
    return Page(items=[_summary(w) for w in items], total=total, page=paging.page, page_size=paging.page_size)


@router.post("/generate", response_model=WebsiteRead, status_code=status.HTTP_201_CREATED,
             summary="Generate a website blueprint, content and SEO for a business")
def generate_website(body: GenerateWebsiteRequest, request: Request, user: Staff, db: DbSession,
                     settings: AppSettings) -> Website:
    return WebsiteService(db, settings).generate(body, actor_for(request, user))


@router.post("/generate-batch", response_model=BatchResult, status_code=status.HTTP_202_ACCEPTED,
             summary="Queue website generation for many businesses (processed by factory workers)")
def generate_batch(body: GenerateBatchRequest, _: Staff, db: DbSession, settings: AppSettings) -> BatchResult:
    return WebsiteService(db, settings).enqueue_batch(body)


@router.get("/{website_id}", response_model=WebsiteRead)
def get_website(website_id: uuid.UUID, _: StaffReader, db: DbSession) -> Website:
    return WebsiteRepository(db).get_or_404(website_id)


@router.get("/{website_id}/blueprint", response_model=BlueprintRead)
def get_blueprint(website_id: uuid.UUID, _: StaffReader, db: DbSession) -> BlueprintRead:
    website = WebsiteRepository(db).get_or_404(website_id)
    return BlueprintRead(website_id=website.id, blueprint=website.blueprint or {})


@router.get("/{website_id}/content", response_model=list[ContentBlockRead])
def get_content(website_id: uuid.UUID, _: StaffReader, db: DbSession) -> list:
    return WebsiteRepository(db).get_or_404(website_id).contents


@router.put("/{website_id}/content", response_model=list[ContentBlockRead])
def update_content(website_id: uuid.UUID, body: ContentUpdate, request: Request, user: Staff,
                   db: DbSession, settings: AppSettings) -> list:
    service = WebsiteService(db, settings)
    website = service.get_or_404(website_id)
    service.update_content(website, body.section_key, body.updates, actor_for(request, user),
                           ContentSource.OPERATOR, body.republish)
    return website.contents


@router.get("/{website_id}/seo", response_model=SeoRead | None)
def get_seo(website_id: uuid.UUID, _: StaffReader, db: DbSession):
    return WebsiteRepository(db).get_or_404(website_id).seo


@router.post("/{website_id}/regenerate", response_model=WebsiteRead)
def regenerate_website(website_id: uuid.UUID, body: RegenerateWebsiteRequest, request: Request, user: Staff,
                       db: DbSession, settings: AppSettings) -> Website:
    service = WebsiteService(db, settings)
    return service.regenerate(service.get_or_404(website_id), body, actor_for(request, user))


@router.post("/{website_id}/publish", response_model=DeploymentRead)
def publish_website(website_id: uuid.UUID, request: Request, user: Staff, db: DbSession,
                    settings: AppSettings, body: PublishRequest | None = None) -> Deployment:
    force = bool(body and body.force)
    if force and user.role != UserRole.ADMIN:
        raise PermissionDeniedError("Only admins can bypass the quality gate")
    service = WebsiteService(db, settings)
    return service.publish(service.get_or_404(website_id), actor_for(request, user), force=force)


@router.post("/{website_id}/unpublish", response_model=WebsiteRead)
def unpublish_website(website_id: uuid.UUID, request: Request, user: Staff, db: DbSession,
                      settings: AppSettings) -> Website:
    service = WebsiteService(db, settings)
    return service.unpublish(service.get_or_404(website_id), actor_for(request, user))


@router.get("/{website_id}/deployments", response_model=list[DeploymentRead])
def list_deployments(website_id: uuid.UUID, _: StaffReader, db: DbSession) -> list[Deployment]:
    repo = WebsiteRepository(db)
    repo.get_or_404(website_id)
    return list(repo.deployments(website_id))
