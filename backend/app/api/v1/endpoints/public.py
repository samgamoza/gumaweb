"""Unauthenticated endpoints called from generated sites, the claim page and outreach emails."""

from __future__ import annotations

import json
from datetime import date as date_type
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Form, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import ValidationError

from app.api.deps import AppSettings, DbSession, actor_for, client_ip
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.core.rate_limit import get_rate_limiter
from app.domains.business_discovery.normalization import normalize_email
from app.domains.claims.enums import ClaimStatus
from app.domains.website_factory.enums import WebsiteStatus
from app.repositories.repositories import WebsiteRepository
from app.schemas.analytics import PublicSiteInfo, SiteEventIn
from app.schemas.claim import ClaimStarted
from app.schemas.engagement import BookingRequest, BookingResult, ChatIn, ChatOut, Slot
from app.schemas.start import StartClaim, StartDetailsUpdate, StartInfo
from app.services.analytics_service import AnalyticsService
from app.services.booking_service import BookingService
from app.services.chatbot_service import ChatbotService
from app.services.claim_link_service import ClaimLinkService
from app.services.outreach_service import OutreachService

router = APIRouter(prefix="/public", tags=["Public"])

# 1x1 transparent GIF
PIXEL = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")


def _mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    return f"{local[0]}{'*' * max(1, len(local) - 1)}@{domain}"


def _mask_phone(phone: str | None) -> str | None:
    return f"{'*' * max(0, len(phone) - 4)}{phone[-4:]}" if phone else None


@router.get("/sites/{subdomain}", response_model=PublicSiteInfo, summary="Site info for the claim page")
def site_info(subdomain: str, db: DbSession) -> PublicSiteInfo:
    website = WebsiteRepository(db).by_subdomain(subdomain)
    if website is None or website.status != WebsiteStatus.PUBLISHED:
        raise NotFoundError("Site not found")
    b = website.business
    return PublicSiteInfo(
        subdomain=website.subdomain, business_name=b.name, industry=b.industry, city=b.city,
        province=b.province, url=website.url, is_claimed=website.is_claimed,
        masked_email=_mask_email(b.email), masked_phone=_mask_phone(b.phone),
    )


@router.post("/sites/{subdomain}/events", status_code=status.HTTP_204_NO_CONTENT,
             summary="Analytics beacon (accepts text/plain JSON from navigator.sendBeacon)")
async def site_event(subdomain: str, request: Request, db: DbSession, settings: AppSettings) -> Response:
    ip = client_ip(request)
    get_rate_limiter().check("site-event", f"{ip}:{subdomain}", 300)
    try:
        event = SiteEventIn.model_validate(json.loads((await request.body())[:4096] or b"{}"))
    except (ValueError, ValidationError) as exc:
        raise ValidationFailedError("Invalid event payload") from exc
    AnalyticsService(db, settings).record_site_event(subdomain, event, ip, request.headers.get("user-agent"))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sites/{subdomain}/contact", summary="Contact form submission from a generated site")
def contact(
    subdomain: str,
    request: Request,
    db: DbSession,
    settings: AppSettings,
    name: Annotated[str, Form(min_length=1, max_length=200)],
    message: Annotated[str, Form(min_length=1, max_length=2000)],
    email: Annotated[str | None, Form(max_length=320)] = None,
    phone: Annotated[str | None, Form(max_length=32)] = None,
    website: Annotated[str | None, Form()] = None,  # honeypot
) -> Response:
    ip = client_ip(request)
    get_rate_limiter().check("contact", ip or "unknown", 10)
    wants_json = "application/json" in request.headers.get("accept", "")
    if website:  # bot filled the hidden field: pretend success, store nothing
        return JSONResponse({"ok": True}) if wants_json else HTMLResponse("Thank you!")
    site = AnalyticsService(db, settings).record_lead(subdomain, name, normalize_email(email), phone,
                                                      message, ip)
    if wants_json:
        return JSONResponse({"ok": True})
    return RedirectResponse(f"{(site.url or '').rstrip('/')}/contact/?sent=1", status_code=303)


@router.get("/outreach/open/{token}.gif", include_in_schema=False)
def outreach_open(token: str, db: DbSession, settings: AppSettings) -> Response:
    OutreachService(db, settings).track_open(token)
    return Response(content=PIXEL, media_type="image/gif", headers={"Cache-Control": "no-store"})


@router.get("/outreach/click/{token}", include_in_schema=False)
def outreach_click(token: str, db: DbSession, settings: AppSettings) -> Response:
    url = OutreachService(db, settings).track_click(token)
    return RedirectResponse(url or settings.frontend_url, status_code=302)


# --- A7: private claim links (owner-triggered publishing) -----------------------------------------
# The token is the only credential: keep it out of referrers, caches and search engines.
PRIVATE_HEADERS = {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer",
                   "Cache-Control": "private, no-store"}


@router.get("/start/{token}", response_model=StartInfo, summary="Open a private claim link (records the click)")
def start_open(token: str, request: Request, response: Response, db: DbSession, settings: AppSettings) -> StartInfo:
    get_rate_limiter().check("start", client_ip(request) or "unknown", 120)
    response.headers.update(PRIVATE_HEADERS)
    return ClaimLinkService(db, settings).open(token)


@router.get("/start/{token}/site/{path:path}", include_in_schema=False)
def start_preview(token: str, path: str, request: Request, db: DbSession, settings: AppSettings) -> Response:
    get_rate_limiter().check("start-preview", client_ip(request) or "unknown", 600)
    data, media_type = ClaimLinkService(db, settings).preview_file(token, path)
    # Shown in a frame on the claim page (frontend origin) only.
    frontend = urlsplit(settings.frontend_url)
    framer = f"{frontend.scheme}://{frontend.netloc}"
    return Response(content=data, media_type=media_type,
                    headers={**PRIVATE_HEADERS, "Content-Security-Policy": f"frame-ancestors {framer}"})


@router.patch("/start/{token}/details", response_model=StartInfo, summary="Save the owner's answers to the draft")
def start_details(token: str, body: StartDetailsUpdate, request: Request, response: Response, db: DbSession,
                  settings: AppSettings) -> StartInfo:
    get_rate_limiter().check("start-details", client_ip(request) or "unknown", 60)
    response.headers.update(PRIVATE_HEADERS)
    return ClaimLinkService(db, settings).save_details(token, body, actor_for(request))


@router.post("/start/{token}/claim", response_model=ClaimStarted, status_code=status.HTTP_201_CREATED,
             summary="Claim the draft from its private link (publishes at claim once verified)")
def start_claim(token: str, body: StartClaim, request: Request, db: DbSession, settings: AppSettings) -> ClaimStarted:
    if body.website:  # honeypot
        raise ValidationFailedError("Invalid submission")
    limiter = get_rate_limiter()
    limiter.check("claim-ip", client_ip(request) or "unknown", settings.claim_rate_limit_per_hour)
    limiter.check("claim-email", body.claimant_email.lower(), settings.claim_rate_limit_per_hour)
    claim = ClaimLinkService(db, settings).claim(token, body, actor_for(request))
    message = {
        ClaimStatus.MANUAL_REVIEW: "Your claim is under review. We will email you once it is approved.",
        ClaimStatus.PENDING_VERIFICATION: (
            "We sent a 6-digit code to your phone." if body.method == "sms"
            else "Check your email for a verification link."
        ),
    }.get(claim.status, "Claim received.")
    return ClaimStarted(claim_id=claim.id, status=claim.status, method=claim.method,
                        expires_at=claim.expires_at, message=message)


@router.get("/outreach/unsubscribe/{token}", response_class=HTMLResponse, include_in_schema=False)
def outreach_unsubscribe(token: str, db: DbSession, settings: AppSettings) -> HTMLResponse:
    ok = OutreachService(db, settings).unsubscribe(token)
    text = "You have been unsubscribed and will not receive further emails." if ok else "Link not recognized."
    return HTMLResponse(f"<!doctype html><title>GumaWeb</title><p style='font-family:sans-serif'>{text}</p>")


# --- Phase 3: booking + chat (called by the widgets on generated sites) -----------------------
@router.get("/sites/{subdomain}/booking", summary="Bookable services for the booking widget")
def booking_info(subdomain: str, db: DbSession, settings: AppSettings) -> dict:
    return BookingService(db, settings).public_info(subdomain)


@router.get("/sites/{subdomain}/booking/slots", response_model=list[Slot])
def booking_slots(subdomain: str, db: DbSession, settings: AppSettings, date: date_type,
                  service: str = Query(max_length=120)) -> list[Slot]:
    service_obj = BookingService(db, settings)
    slots = service_obj.slots(subdomain, date, service)
    return [Slot(start=s, label=s.strftime("%I:%M %p").lstrip("0")) for s in slots]


@router.post("/sites/{subdomain}/booking", response_model=BookingResult, status_code=status.HTTP_201_CREATED)
def book(subdomain: str, body: BookingRequest, request: Request, db: DbSession, settings: AppSettings) -> BookingResult:
    if body.website:  # honeypot
        raise ValidationFailedError("Invalid submission")
    if not (body.email or body.phone):
        raise ValidationFailedError("Please provide an email address or phone number")
    get_rate_limiter().check("booking", client_ip(request) or "unknown", 10)
    appt, _token = BookingService(db, settings).book(subdomain, body.model_dump())
    message = ("You're booked! A confirmation has been sent." if appt.status == "confirmed"
               else "Request received. The business will confirm your booking shortly.")
    return BookingResult(appointment_id=appt.id, status=appt.status, starts_at=appt.starts_at, message=message)


@router.get("/booking/{token}", summary="Booking details for the manage link")
def booking_details(token: str, db: DbSession, settings: AppSettings) -> dict:
    service = BookingService(db, settings)
    return service.summary(service.by_token(token))


@router.post("/booking/{token}/cancel", summary="Cancel a booking via its manage link")
def booking_cancel(token: str, request: Request, db: DbSession, settings: AppSettings) -> dict:
    get_rate_limiter().check("booking-cancel", client_ip(request) or "unknown", 20)
    service = BookingService(db, settings)
    return service.summary(service.cancel_by_token(token))


@router.post("/sites/{subdomain}/chat", response_model=ChatOut, summary="Website assistant (AI tier)")
def chat(subdomain: str, body: ChatIn, request: Request, db: DbSession, settings: AppSettings) -> ChatOut:
    get_rate_limiter().check("chat", f"{client_ip(request)}:{subdomain}", 60)
    reply = ChatbotService(db, settings).chat(subdomain, body.session_token, body.message, client_ip(request))
    return ChatOut(session_token=reply.session_token, reply=reply.reply)
