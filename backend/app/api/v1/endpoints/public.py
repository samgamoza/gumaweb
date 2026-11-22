"""Unauthenticated endpoints called from generated sites, the claim page and outreach emails."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Form, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import ValidationError

from app.api.deps import AppSettings, DbSession, client_ip
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.core.rate_limit import get_rate_limiter
from app.domains.business_discovery.normalization import normalize_email
from app.domains.website_factory.enums import WebsiteStatus
from app.repositories.repositories import WebsiteRepository
from app.schemas.analytics import PublicSiteInfo, SiteEventIn
from app.services.analytics_service import AnalyticsService
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


@router.get("/outreach/unsubscribe/{token}", response_class=HTMLResponse, include_in_schema=False)
def outreach_unsubscribe(token: str, db: DbSession, settings: AppSettings) -> HTMLResponse:
    ok = OutreachService(db, settings).unsubscribe(token)
    text = "You have been unsubscribed and will not receive further emails." if ok else "Link not recognized."
    return HTMLResponse(f"<!doctype html><title>GumaWeb</title><p style='font-family:sans-serif'>{text}</p>")
