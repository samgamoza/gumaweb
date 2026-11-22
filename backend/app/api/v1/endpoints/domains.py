"""Phase 5 custom domains and business email: owner API, plus the TLS edge's certificate check."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.api.deps import AppSettings, CustomerUser, DbSession, actor_for
from app.models import CustomDomain
from app.services.customer_service import CustomerService
from app.services.domain_service import DomainService
from app.services.mail_service import MailService

router = APIRouter(prefix="/customer", tags=["Customer Portal: Domains and email"])
edge = APIRouter(prefix="/public/domains", tags=["Public"])


class DomainCreate(BaseModel):
    domain: str = Field(min_length=3, max_length=300)


class DomainServe(BaseModel):
    serve_website: bool


class DomainRead(BaseModel):
    id: uuid.UUID
    domain: str
    status: str
    serve_website: bool
    verified_at: datetime | None
    last_checked_at: datetime | None
    last_error: str | None
    records: list[dict[str, Any]]
    email: dict[str, Any] | None


class MailboxCreate(BaseModel):
    local_part: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(None, max_length=120)
    kind: str = "mailbox"
    forward_to: list[str] = Field(default_factory=list, max_length=10)


def _business_id(user, db, settings) -> uuid.UUID:
    return CustomerService(db, settings).for_user(user).business_id


def _read(db, settings, row: CustomDomain) -> DomainRead:
    mail = MailService(db, settings)
    return DomainRead(id=row.id, domain=row.domain, status=row.status.value, serve_website=row.serve_website,
                      verified_at=row.verified_at, last_checked_at=row.last_checked_at, last_error=row.last_error,
                      records=DomainService(db, settings).records(row) + mail.records_for(row),
                      email=mail.summary(row))


# --- Domains -------------------------------------------------------------------------------------
@router.get("/domains", response_model=list[DomainRead])
def list_domains(user: CustomerUser, db: DbSession, settings: AppSettings) -> list[DomainRead]:
    business_id = _business_id(user, db, settings)
    return [_read(db, settings, d) for d in DomainService(db, settings).domains(business_id)]


@router.post("/domains", response_model=DomainRead, status_code=status.HTTP_201_CREATED,
             summary="Connect a domain (Professional plan); returns the DNS records to add")
def add_domain(body: DomainCreate, user: CustomerUser, db: DbSession, settings: AppSettings) -> DomainRead:
    row = DomainService(db, settings).add(_business_id(user, db, settings), body.domain)
    return _read(db, settings, row)


@router.post("/domains/{domain_id}/verify", response_model=DomainRead,
             summary="Check the TXT verification record now")
def verify_domain(domain_id: uuid.UUID, user: CustomerUser, db: DbSession, settings: AppSettings) -> DomainRead:
    service = DomainService(db, settings)
    return _read(db, settings, service.verify(service.get(_business_id(user, db, settings), domain_id)))


@router.put("/domains/{domain_id}/website", response_model=DomainRead,
            summary="Serve (or stop serving) the website at this domain")
def serve_domain(domain_id: uuid.UUID, body: DomainServe, request: Request, user: CustomerUser, db: DbSession,
                 settings: AppSettings) -> DomainRead:
    service = DomainService(db, settings)
    row = service.get(_business_id(user, db, settings), domain_id)
    return _read(db, settings, service.set_serving(row, body.serve_website, actor_for(request, user)))


@router.delete("/domains/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_domain(domain_id: uuid.UUID, request: Request, user: CustomerUser, db: DbSession,
                  settings: AppSettings) -> None:
    service = DomainService(db, settings)
    service.remove(service.get(_business_id(user, db, settings), domain_id), actor_for(request, user))


# --- Business email --------------------------------------------------------------------------------
@router.post("/domains/{domain_id}/email", response_model=DomainRead, status_code=status.HTTP_201_CREATED,
             summary="Enable business email on a verified domain (Professional plan)")
def enable_email(domain_id: uuid.UUID, user: CustomerUser, db: DbSession, settings: AppSettings) -> DomainRead:
    row = DomainService(db, settings).get(_business_id(user, db, settings), domain_id)
    MailService(db, settings).enable(row)
    return _read(db, settings, row)


@router.post("/domains/{domain_id}/email/check", response_model=DomainRead,
             summary="Check the MX/SPF/DKIM/DMARC records")
def check_email_dns(domain_id: uuid.UUID, user: CustomerUser, db: DbSession, settings: AppSettings) -> DomainRead:
    row = DomainService(db, settings).get(_business_id(user, db, settings), domain_id)
    MailService(db, settings).check_dns(row)
    return _read(db, settings, row)


@router.post("/domains/{domain_id}/mailboxes", status_code=status.HTTP_201_CREATED,
             summary="Create a mailbox or forwarding address (a mailbox's password is shown once)")
def create_mailbox(domain_id: uuid.UUID, body: MailboxCreate, user: CustomerUser, db: DbSession,
                   settings: AppSettings) -> dict[str, Any]:
    row = DomainService(db, settings).get(_business_id(user, db, settings), domain_id)
    return MailService(db, settings).create_mailbox(row, body.model_dump())


@router.post("/domains/{domain_id}/mailboxes/{mailbox_id}/reset-password",
             summary="Set a new password (shown once)")
def reset_mailbox_password(domain_id: uuid.UUID, mailbox_id: uuid.UUID, user: CustomerUser, db: DbSession,
                           settings: AppSettings) -> dict[str, Any]:
    row = DomainService(db, settings).get(_business_id(user, db, settings), domain_id)
    return MailService(db, settings).reset_password(row, mailbox_id)


@router.delete("/domains/{domain_id}/mailboxes/{mailbox_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mailbox(domain_id: uuid.UUID, mailbox_id: uuid.UUID, user: CustomerUser, db: DbSession,
                   settings: AppSettings) -> None:
    row = DomainService(db, settings).get(_business_id(user, db, settings), domain_id)
    MailService(db, settings).delete_mailbox(row, mailbox_id)


# --- TLS edge ----------------------------------------------------------------------------------------
@edge.get("/tls-check", summary="Caddy on-demand TLS `ask`: 200 only for verified domains we serve",
          response_class=Response)
def tls_check(db: DbSession, settings: AppSettings, domain: str = Query(max_length=260)) -> Response:
    allowed = DomainService(db, settings).allows_certificate(domain)
    return Response(status_code=200 if allowed else 404)
