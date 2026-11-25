"""Claim Ownership Platform (11):

Website Published → Business Visits Site → Claim Request → Verification
→ Ownership Transfer → Customer Activation
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.core.security import generate_otp, generate_url_token, hash_password, hash_token, tokens_match
from app.domains.audit.actions import AuditAction
from app.domains.billing.enums import PlanCode
from app.domains.business_discovery.enums import BusinessStatus
from app.domains.business_discovery.lifecycle import advance
from app.domains.business_discovery.normalization import normalize_phone
from app.domains.claims.enums import ACTIVE_CLAIM_STATUSES, ClaimStatus, VerificationMethod
from app.domains.claims.risk import RiskInput, assess_claim_risk
from app.domains.customers.enums import UserRole
from app.domains.outreach.enums import MessageStatus, OutreachEventType
from app.domains.sales import ActivityType
from app.domains.website_factory.enums import WebsiteStatus
from app.models import Claim, Customer, OutreachEvent, OutreachMessage, Subscription, User, Website
from app.repositories.repositories import (
    ClaimRepository,
    CustomerRepository,
    OutreachRepository,
    UserRepository,
    WebsiteRepository,
)
from app.schemas.claim import ClaimStart, ClaimVerify
from app.services.auth_service import issue_tokens
from app.services.notifications import EmailMessage
from app.services.prospect_service import ProspectService
from app.services.providers import providers
from app.services.publishing_service import PublishingService
from app.services.support import Actor, EventType, audit, record_event

logger = logging.getLogger("gumaweb.claims")


class ClaimService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.claims = ClaimRepository(db)
        self.websites = WebsiteRepository(db)
        self.users = UserRepository(db)
        self.customers = CustomerRepository(db)
        self.outreach = OutreachRepository(db)

    # --- Start ----------------------------------------------------------------------
    def start(self, data: ClaimStart, actor: Actor) -> Claim:
        website = self.websites.by_subdomain(data.subdomain)
        if website is None or website.status != WebsiteStatus.PUBLISHED:
            raise NotFoundError("Website not found")
        if website.is_claimed or self.claims.approved_for_business(website.business_id):
            raise ConflictError("This website has already been claimed", code="already_claimed")

        email = data.claimant_email.lower()
        phone = normalize_phone(data.claimant_phone, self.settings.default_country_code)
        active = self.claims.active_for_business(website.business_id)
        existing = next((c for c in active if c.claimant_email == email), None)
        if existing and existing.status == ClaimStatus.MANUAL_REVIEW:
            return existing  # duplicate claim: already awaiting review

        business = website.business
        since = datetime.now(UTC) - timedelta(hours=24)
        risk = assess_claim_risk(
            RiskInput(
                method=data.method, claimant_email=email, claimant_phone=phone, business_email=business.email,
                business_phone=business.phone, business_website=business.website,
                recent_claims_from_ip=(self.claims.count_from_ip_since(actor.ip, since) + 1) if actor.ip else 1,
                competing_active_claims=len([c for c in active if c.claimant_email != email]),
            )
        )
        claim = existing or Claim(business_id=business.id, website_id=website.id, claimant_email=email)
        claim.claimant_name = data.claimant_name
        claim.claimant_phone = phone
        claim.method = data.method
        claim.status = ClaimStatus.PENDING_VERIFICATION
        claim.evidence = data.evidence
        claim.risk_score = risk.score
        claim.risk_factors = risk.factors
        claim.ip_address = actor.ip
        claim.user_agent = (actor.user_agent or "")[:500] or None
        claim.verification_attempts = 0
        claim.expires_at = datetime.now(UTC) + timedelta(hours=self.settings.claim_token_ttl_hours)
        if existing is None:
            self.db.add(claim)

        if data.method == VerificationMethod.SMS:
            otp = generate_otp()
            claim.otp_hash = hash_token(otp)
            claim.verification_token_hash = None
            self.db.flush()
            providers.sms.send(phone or "", f"Your GumaWeb verification code is {otp}. It expires in "
                                            f"{self.settings.claim_token_ttl_hours} hours.")
        else:  # email link; business_identity also proves email ownership before review
            token = generate_url_token()
            claim.verification_token_hash = hash_token(token)
            claim.otp_hash = None
            self.db.flush()
            link = f"{self.settings.frontend_url.rstrip('/')}/claim/verify?token={token}"
            providers.email.send(
                EmailMessage(
                    to=email,
                    subject=f"Verify your claim for {business.name}",
                    text=(
                        f"Hi {data.claimant_name},\n\nConfirm that you own {business.name} by opening this "
                        f"link:\n{link}\n\nThe link expires in {self.settings.claim_token_ttl_hours} hours. "
                        "If you did not request this, ignore this email.\n\nGumaWeb"
                    ),
                )
            )

        self._attribute(business.id, OutreachEventType.CLAIM_STARTED, data.ref)
        ProspectService(self.db).record(business.id, ActivityType.CLAIM_STARTED,
                                        external_id=f"claim:{claim.id}:started", data={"method": data.method.value})
        record_event(self.db, EventType.CLAIM_STARTED, "claim", claim.id, {"business_id": str(business.id)})
        audit(self.db, actor, AuditAction.CLAIM_STARTED, "claim", claim.id,
              {"business_id": str(business.id), "method": data.method.value, "risk": risk.score})
        self.db.commit()
        return claim

    # --- Verify ---------------------------------------------------------------------
    def verify(self, data: ClaimVerify, actor: Actor) -> tuple[Claim, User | None]:
        claim = self._locate_for_verification(data)
        if claim.status != ClaimStatus.PENDING_VERIFICATION:
            raise ConflictError(f"Claim is {claim.status.value}")
        if claim.expires_at.replace(tzinfo=claim.expires_at.tzinfo or UTC) < datetime.now(UTC):
            claim.status = ClaimStatus.EXPIRED
            self.db.commit()
            raise ValidationFailedError("This verification has expired; please start a new claim")

        user = self.users.by_email(claim.claimant_email)
        if user is None:
            if not data.password:
                raise ValidationFailedError("Choose a password (min. 10 characters) to create your account",
                                            code="password_required")
            user = self.users.add(
                User(email=claim.claimant_email, password_hash=hash_password(data.password),
                     full_name=claim.claimant_name, phone=claim.claimant_phone, role=UserRole.CUSTOMER,
                     is_email_verified=claim.method != VerificationMethod.SMS)
            )
        elif user.role == UserRole.CUSTOMER and self.customers.by_user(user.id):
            raise ConflictError("This account already manages a business", code="already_customer")

        claim.user_id = user.id
        claim.verified_at = datetime.now(UTC)
        claim.verification_token_hash = None
        claim.otp_hash = None
        audit(self.db, Actor(user=user, ip=actor.ip), AuditAction.CLAIM_VERIFIED, "claim", claim.id)

        assessment_requires_review = claim.method == VerificationMethod.BUSINESS_IDENTITY or (
            claim.risk_score >= self.settings.claim_manual_review_threshold
        )
        if assessment_requires_review:
            claim.status = ClaimStatus.MANUAL_REVIEW
            self.db.commit()
            return claim, None
        self._transfer_ownership(claim, user, Actor(user=user, ip=actor.ip))
        return claim, user

    def _locate_for_verification(self, data: ClaimVerify) -> Claim:
        if data.token:
            claim = self.claims.by_token_hash(hash_token(data.token))
            if claim is None:
                raise NotFoundError("Invalid or already used verification link")
            return claim
        claim = self.claims.get(data.claim_id)
        if claim is None or claim.method != VerificationMethod.SMS:
            raise NotFoundError("Claim not found")
        if claim.verification_attempts >= self.settings.claim_max_verification_attempts:
            claim.status = ClaimStatus.EXPIRED
            self.db.commit()
            raise PermissionDeniedError("Too many attempts; please start a new claim")
        if not tokens_match(data.otp or "", claim.otp_hash):
            claim.verification_attempts += 1
            self.db.commit()
            raise ValidationFailedError("Incorrect verification code")
        return claim

    # --- Review (staff) -------------------------------------------------------------
    def approve(self, claim: Claim, actor: Actor, notes: str | None) -> Claim:
        if claim.status != ClaimStatus.MANUAL_REVIEW or claim.user_id is None:
            raise ConflictError("Only verified claims awaiting review can be approved")
        claim.reviewed_by = actor.user_id
        claim.reviewed_at = datetime.now(UTC)
        claim.review_notes = notes
        user = self.users.get_or_404(claim.user_id)
        self._transfer_ownership(claim, user, actor)
        providers.email.send(EmailMessage(
            to=claim.claimant_email, subject="Your website claim was approved",
            text=f"Good news! You now manage your website. Sign in at {self.settings.frontend_url}/login",
        ))
        return claim

    def reject(self, claim: Claim, actor: Actor, notes: str | None) -> Claim:
        if claim.status not in ACTIVE_CLAIM_STATUSES:
            raise ConflictError(f"Claim is already {claim.status.value}")
        claim.status = ClaimStatus.REJECTED
        claim.reviewed_by = actor.user_id
        claim.reviewed_at = datetime.now(UTC)
        claim.review_notes = notes
        claim.verification_token_hash = None
        record_event(self.db, EventType.CLAIM_REJECTED, "claim", claim.id)
        ProspectService(self.db).record(claim.business_id, ActivityType.CLAIM_REJECTED,
                                        external_id=f"claim:{claim.id}:rejected", data={"notes": notes})
        audit(self.db, actor, AuditAction.CLAIM_REJECTED, "claim", claim.id, {"notes": notes})
        self.db.commit()
        return claim

    # --- Ownership transfer ----------------------------------------------------------
    def _transfer_ownership(self, claim: Claim, user: User, actor: Actor) -> None:
        business = claim.business
        website: Website | None = self.websites.by_business(business.id)
        if self.customers.by_business(business.id):
            raise ConflictError("This business already has an owner", code="already_claimed")

        claim.status = ClaimStatus.APPROVED
        self.db.execute(
            update(Claim)
            .where(Claim.business_id == business.id, Claim.id != claim.id,
                   Claim.status.in_(ACTIVE_CLAIM_STATUSES))
            .values(status=ClaimStatus.REJECTED, review_notes="Superseded by an approved claim",
                    verification_token_hash=None)
        )
        customer = self.customers.add(Customer(user_id=user.id, business_id=business.id, plan=PlanCode.FREE))
        self.db.add(Subscription(customer_id=customer.id, plan_code=PlanCode.FREE))
        business.status = advance(business.status, BusinessStatus.CLAIMED)
        # Stop outreach to a business that has converted.
        self.db.execute(
            update(OutreachMessage)
            .where(OutreachMessage.business_id == business.id,
                   OutreachMessage.status == MessageStatus.SCHEDULED)
            .values(status=MessageStatus.SKIPPED, error="claimed")
        )
        self._attribute(business.id, OutreachEventType.CLAIM_COMPLETED, None)
        ProspectService(self.db).record(business.id, ActivityType.CLAIM_APPROVED,
                                        external_id=f"claim:{claim.id}:approved",
                                        data={"claimant_name": claim.claimant_name})
        record_event(self.db, EventType.CLAIM_COMPLETED, "claim", claim.id,
                     {"business_id": str(business.id), "customer_id": str(customer.id)})
        audit(self.db, actor, AuditAction.CLAIM_APPROVED, "claim", claim.id, {"customer_id": str(customer.id)})

        if website is not None:
            website.is_claimed = True
            if website.status == WebsiteStatus.PUBLISHED:
                try:  # republish without the claim banner; a failure must not undo the claim
                    PublishingService(self.db, self.settings).publish(website, actor, force=True)
                except Exception:
                    logger.exception("republish after claim failed for %s", website.subdomain)
        self.db.commit()

    def _attribute(self, business_id: uuid.UUID, event_type: OutreachEventType, ref: str | None) -> None:
        """Attribute claim funnel events to the outreach message that drove them."""
        message = self.outreach.message_by_token(ref) if ref else None
        if message is None or message.business_id != business_id:
            message = self.outreach.latest_message_for_business(business_id)
        if message is not None:
            self.db.add(OutreachEvent(business_id=business_id, campaign_id=message.campaign_id,
                                      message_id=message.id, channel=message.channel, event_type=event_type))

    def tokens_for(self, user: User):
        return issue_tokens(user)


