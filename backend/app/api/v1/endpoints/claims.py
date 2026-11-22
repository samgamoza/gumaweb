from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.api.deps import AppSettings, DbSession, Pagination, Staff, StaffReader, actor_for, client_ip
from app.core.exceptions import ValidationFailedError
from app.core.rate_limit import get_rate_limiter
from app.domains.claims.enums import ClaimStatus
from app.models import Claim
from app.repositories.repositories import ClaimRepository
from app.schemas.claim import ClaimRead, ClaimReview, ClaimStart, ClaimStarted, ClaimVerified, ClaimVerify
from app.schemas.common import Page
from app.services.auth_service import issue_tokens
from app.services.claim_service import ClaimService

router = APIRouter(prefix="/claims", tags=["Claims"])


@router.post("", response_model=ClaimStarted, status_code=status.HTTP_201_CREATED,
             summary="Start a claim (public, rate limited)")
def start_claim(body: ClaimStart, request: Request, db: DbSession, settings: AppSettings) -> ClaimStarted:
    if body.website:  # honeypot field filled => bot
        raise ValidationFailedError("Invalid submission")
    limiter = get_rate_limiter()
    limiter.check("claim-ip", client_ip(request) or "unknown", settings.claim_rate_limit_per_hour)
    limiter.check("claim-email", body.claimant_email.lower(), settings.claim_rate_limit_per_hour)
    claim = ClaimService(db, settings).start(body, actor_for(request))
    message = {
        ClaimStatus.MANUAL_REVIEW: "Your claim is under review. We will email you once it is approved.",
        ClaimStatus.PENDING_VERIFICATION: (
            "We sent a 6-digit code to your phone." if body.method == "sms"
            else "Check your email for a verification link."
        ),
    }.get(claim.status, "Claim received.")
    return ClaimStarted(claim_id=claim.id, status=claim.status, method=claim.method,
                        expires_at=claim.expires_at, message=message)


@router.post("/verify", response_model=ClaimVerified, summary="Verify a claim via email token or SMS OTP")
def verify_claim(body: ClaimVerify, request: Request, db: DbSession, settings: AppSettings) -> ClaimVerified:
    get_rate_limiter().check("claim-verify", client_ip(request) or "unknown", 30)
    claim, user = ClaimService(db, settings).verify(body, actor_for(request))
    if claim.status == ClaimStatus.APPROVED and user is not None:
        return ClaimVerified(claim_id=claim.id, status=claim.status, tokens=issue_tokens(user),
                             message="Verified! You now own this website.")
    return ClaimVerified(claim_id=claim.id, status=claim.status,
                         message="Verified. Your claim needs a quick manual review; we will email you soon.")


@router.get("", response_model=Page[ClaimRead])
def list_claims(_: StaffReader, db: DbSession, paging: Pagination,
                status_filter: ClaimStatus | None = None) -> Page[ClaimRead]:
    stmt = select(Claim).order_by(Claim.created_at.desc())
    if status_filter:
        stmt = stmt.where(Claim.status == status_filter)
    repo = ClaimRepository(db)
    items, total = repo.paginate(stmt, paging.page, paging.page_size)
    return Page(items=items, total=total, page=paging.page, page_size=paging.page_size)


@router.get("/{claim_id}", response_model=ClaimRead)
def get_claim(claim_id: uuid.UUID, _: StaffReader, db: DbSession) -> Claim:
    return ClaimRepository(db).get_or_404(claim_id)


@router.post("/{claim_id}/approve", response_model=ClaimRead)
def approve_claim(claim_id: uuid.UUID, body: ClaimReview, request: Request, user: Staff, db: DbSession,
                  settings: AppSettings) -> Claim:
    claim = ClaimRepository(db).get_or_404(claim_id)
    return ClaimService(db, settings).approve(claim, actor_for(request, user), body.notes)


@router.post("/{claim_id}/reject", response_model=ClaimRead)
def reject_claim(claim_id: uuid.UUID, body: ClaimReview, request: Request, user: Staff, db: DbSession,
                 settings: AppSettings) -> Claim:
    claim = ClaimRepository(db).get_or_404(claim_id)
    return ClaimService(db, settings).reject(claim, actor_for(request, user), body.notes)
