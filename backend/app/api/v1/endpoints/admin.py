from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import select

from app.api.deps import Admin, DbSession, Pagination, Staff, StaffReader, actor_for
from app.core.exceptions import NotFoundError
from app.domains.customers.enums import UserRole
from app.domains.website_factory.jobs import JobStatus
from app.models import AuditLog, DomainEvent, FactoryJob, User
from app.repositories.repositories import AuditRepository, DomainEventRepository, UserRepository
from app.schemas.analytics import AuditLogRead, DomainEventRead
from app.schemas.auth import UserCreate, UserRead, UserUpdate
from app.schemas.common import Page
from app.schemas.website import JobRead
from app.services.auth_service import AuthService
from app.services.job_queue import JobQueue

router = APIRouter(prefix="/admin", tags=["Administration"])


@router.get("/users", response_model=Page[UserRead])
def list_users(_: Admin, db: DbSession, paging: Pagination, role: UserRole | None = None) -> Page[UserRead]:
    stmt = select(User).order_by(User.created_at.desc())
    if role:
        stmt = stmt.where(User.role == role)
    items, total = UserRepository(db).paginate(stmt, paging.page, paging.page_size)
    return Page(items=items, total=total, page=paging.page, page_size=paging.page_size)


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, request: Request, admin: Admin, db: DbSession) -> User:
    return AuthService(db).create_user(body, actor_for(request, admin))


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(user_id: uuid.UUID, body: UserUpdate, request: Request, admin: Admin, db: DbSession) -> User:
    user = UserRepository(db).get_or_404(user_id)
    return AuthService(db).update_user(user, body, actor_for(request, admin))


@router.get("/jobs", response_model=list[JobRead], summary="Factory job queue")
def list_jobs(_: StaffReader, db: DbSession, status_filter: JobStatus | None = None,
              limit: int = Query(100, ge=1, le=500)) -> list[FactoryJob]:
    return list(JobQueue(db).recent(status_filter, limit))


@router.get("/jobs/stats", response_model=dict[str, int])
def job_stats(_: StaffReader, db: DbSession) -> dict[str, int]:
    return JobQueue(db).counts()


@router.post("/jobs/{job_id}/retry", response_model=JobRead)
def retry_job(job_id: uuid.UUID, _: Staff, db: DbSession) -> FactoryJob:
    queue = JobQueue(db)
    job = queue.get(job_id)
    if job is None:
        raise NotFoundError("Job not found")
    return queue.retry(job)


@router.get("/audit-logs", response_model=Page[AuditLogRead])
def audit_logs(_: StaffReader, db: DbSession, paging: Pagination, action: str | None = None,
               entity_type: str | None = None, entity_id: str | None = None) -> Page[AuditLogRead]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    items, total = AuditRepository(db).paginate(stmt, paging.page, paging.page_size)
    return Page(items=items, total=total, page=paging.page, page_size=paging.page_size)


@router.get("/events", response_model=Page[DomainEventRead], summary="Domain event outbox")
def domain_events(_: StaffReader, db: DbSession, paging: Pagination,
                  event_type: str | None = None) -> Page[DomainEventRead]:
    stmt = select(DomainEvent).order_by(DomainEvent.occurred_at.desc())
    if event_type:
        stmt = stmt.where(DomainEvent.event_type == event_type)
    items, total = DomainEventRepository(db).paginate(stmt, paging.page, paging.page_size)
    return Page(items=items, total=total, page=paging.page, page_size=paging.page_size)
