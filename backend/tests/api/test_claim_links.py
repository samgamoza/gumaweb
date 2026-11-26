"""Onboarding funnel A7: private claim links, the draft preview, the details form, and publish at claim."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.domains.website_factory.enums import WebsiteStatus
from app.models import Business, ClaimLink, OutreachEvent, ProspectActivity, Website
from app.services import lead_compiler
from app.services.draft_prep import DraftPrep
from app.services.outbound_engine import OutboundEngine
from app.services.prospect_service import ProspectService
from app.services.providers import providers

START = "/api/v1/public/start"
OWNER_EMAIL = "reyes.bakery@gmail.com"


@pytest.fixture
def engine_settings(settings, monkeypatch):
    monkeypatch.setattr(settings, "outbound_quiet_hours_start", 0)
    monkeypatch.setattr(settings, "outbound_quiet_hours_end", 0)
    return settings


@pytest.fixture
def draft(client, admin_headers, db, settings) -> dict:
    """A private draft that passed the quality gate, in the pipeline (as the lead compiler leaves it)."""
    business = client.post("/api/v1/businesses", headers=admin_headers, json={
        "name": "Reyes Bakery", "city": "Angeles City", "province": "Pampanga", "industry": "bakery",
        "phone": "0917 555 0199", "email": OWNER_EMAIL, "facebook": "facebook.com/reyesbakery"}).json()
    created = client.post("/api/v1/websites/generate", json={"business_id": business["id"], "publish": False},
                          headers=admin_headers)
    assert created.status_code == 201, created.text
    website = db.get(Website, uuid.UUID(created.json()["id"]))
    assert website.status is WebsiteStatus.BLUEPRINT_READY
    assert lead_compiler.draft_built(db, website)
    assert DraftPrep(db, settings).prepare(website).ready  # polish review (A7b): outreach-ready
    db.commit()
    return {"business_id": uuid.UUID(business["id"]), "website_id": website.id, "subdomain": website.subdomain}


def emailed_token(db, settings) -> str:
    db.expire_all()
    OutboundEngine(db, settings).tick()
    match = re.search(r"/start/([\w-]+)", providers.email.outbox[-1].text)
    assert match, providers.email.outbox[-1].text
    return match.group(1)


def activity_types(db, business_id) -> list[str]:
    prospect = ProspectService(db).for_business(business_id)
    rows = db.scalars(select(ProspectActivity).where(ProspectActivity.prospect_id == prospect.id))
    return [a.type.value for a in rows]


def test_the_engine_emails_a_draft_its_private_link_and_opening_it_is_the_click(client, draft, engine_settings, db):
    token = emailed_token(db, engine_settings)
    assert providers.email.outbox[-1].subject == "Your website is ready, Reyes Bakery"
    assert "/public/outreach/click/" not in providers.email.outbox[-1].text  # the draft has no public URL
    link = db.scalar(select(ClaimLink))
    assert link.message_id is not None and link.token_hash != token  # only the hash is stored

    opened = client.get(f"{START}/{token}")
    assert opened.status_code == 200
    assert opened.headers["x-robots-tag"].startswith("noindex") and opened.headers["referrer-policy"] == "no-referrer"
    body = opened.json()
    assert body["status"] == "ready" and body["business_name"] == "Reyes Bakery"
    assert re.fullmatch(r"r\*+@gmail\.com",body["masked_email"]) and body["details"]["email"] is None
    client.get(f"{START}/{token}")  # a second open isn't a second click

    db.expire_all()
    assert ProspectService(db).for_business(draft["business_id"]).stage.value == "engaged"
    clicks = db.scalars(select(OutreachEvent).where(OutreachEvent.event_type == "link_clicked")).all()
    assert len(clicks) == 1 and clicks[0].message_id == link.message_id
    assert db.get(ClaimLink, link.id).open_count == 2


def test_preview_serves_the_draft_privately_without_publishing_it(client, draft, engine_settings, db):
    token = emailed_token(db, engine_settings)
    home = client.get(f"{START}/{token}/site/")
    assert home.status_code == 200 and home.headers["content-type"].startswith("text/html")
    assert "Reyes Bakery" in home.text and home.headers["cache-control"] == "private, no-store"
    assert home.headers["content-security-policy"] == "frame-ancestors http://portal.test"  # FRONTEND_URL
    assert "x-frame-options" not in home.headers
    assert client.get(f"{START}/{token}").headers["x-frame-options"] == "DENY"  # everything else stays unframed
    assert client.get(f"{START}/{token}/site/assets/site.css").headers["content-type"].startswith("text/css")
    for missing in ("nope.html", "robots.txt", "../../etc/passwd"):
        assert client.get(f"{START}/{token}/site/{missing}").status_code == 404
    assert client.get(f"{START}/not-a-token/site/").status_code == 404
    assert client.get(f"/api/v1/public/sites/{draft['subdomain']}").status_code == 404  # still not public
    db.expire_all()
    assert db.get(Website, draft["website_id"]).status is WebsiteStatus.BLUEPRINT_READY


def test_details_update_the_draft_but_contacts_wait_for_verification(client, draft, engine_settings, db):
    token = emailed_token(db, engine_settings)
    saved = client.patch(f"{START}/{token}/details", json={
        "name": "Reyes Family Bakery", "services": ["Ensaymada", "Custom cakes"],
        "phone": "0918 000 1111", "email": "new.owner@example.com"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["details"]["phone"] == "639180001111" and saved.json()["details"]["services"] == [
        "Ensaymada", "Custom cakes"]

    page = client.get(f"{START}/{token}/site/").text
    assert "Reyes Family Bakery" in page
    assert "Reyes Bakery" not in page.replace("Reyes Family Bakery", "")  # copy written with the old name too
    assert "Custom cakes" in client.get(f"{START}/{token}/site/services/").text  # template copy rewritten

    db.expire_all()
    business = db.get(Business, draft["business_id"])
    assert business.name == "Reyes Family Bakery"
    assert (business.email, business.phone) == (OWNER_EMAIL, "639175550199")  # what verification relies on
    assert "claim_started" in activity_types(db, draft["business_id"])
    client.patch(f"{START}/{token}/details", json={"description": "Since 1987."})
    assert activity_types(db, draft["business_id"]).count("claim_started") == 1


def test_claiming_with_the_email_on_record_publishes_at_claim(client, draft, engine_settings, db):
    token = emailed_token(db, engine_settings)
    client.patch(f"{START}/{token}/details", json={"phone": "0918 000 1111"})
    started = client.post(f"{START}/{token}/claim", json={"claimant_name": "Ana Reyes", "claimant_email": OWNER_EMAIL})
    assert started.status_code == 201, started.text
    assert started.json()["status"] == "pending_verification"
    verify = re.search(r"token=([\w-]+)", providers.email.outbox[-1].text).group(1)
    verified = client.post("/api/v1/claims/verify", json={"token": verify, "password": "OwnerPass!2026"})
    assert verified.status_code == 200 and verified.json()["tokens"], verified.text

    db.expire_all()
    website = db.get(Website, draft["website_id"])
    assert website.status is WebsiteStatus.PUBLISHED and website.is_claimed  # claimed and live in one step
    assert db.get(Business, draft["business_id"]).phone == "639180001111"  # owner's answer applied at transfer
    assert ProspectService(db).for_business(draft["business_id"]).stage.value == "claimed"
    assert client.get(f"{START}/{token}").json()["status"] == "claimed"


def test_a_forwarded_link_cannot_publish_someone_elses_business(client, draft, engine_settings, db):
    token = emailed_token(db, engine_settings)
    started = client.post(f"{START}/{token}/claim", json={"claimant_name": "Someone Else",
                                                           "claimant_email": "someone.else@example.com"})
    verify = re.search(r"token=([\w-]+)", providers.email.outbox[-1].text).group(1)
    verified = client.post("/api/v1/claims/verify", json={"token": verify, "password": "OwnerPass!2026"})
    assert started.status_code == 201 and verified.json()["status"] == "manual_review"
    db.expire_all()
    assert db.get(Website, draft["website_id"]).status is WebsiteStatus.BLUEPRINT_READY  # nothing published


def test_drafts_are_claimable_only_through_their_link_and_links_expire(client, draft, engine_settings, db):
    claim = {"subdomain": draft["subdomain"], "claimant_name": "Ana Reyes", "claimant_email": OWNER_EMAIL}
    assert client.post("/api/v1/claims", json=claim).status_code == 404

    token = emailed_token(db, engine_settings)
    link = db.scalar(select(ClaimLink))
    link.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    expired = client.get(f"{START}/{token}")
    assert expired.status_code == 410 and expired.json()["error"] == "link_expired"
    assert client.post(f"{START}/{token}/claim", json={"claimant_name": "Ana Reyes",
                                                        "claimant_email": OWNER_EMAIL}).status_code == 410


def test_each_email_carries_a_fresh_link(client, draft, engine_settings, db):
    first = emailed_token(db, engine_settings)
    db.expire_all()
    OutboundEngine(db, engine_settings, now=datetime.now(UTC) + timedelta(hours=49)).tick()  # unopened: resend
    second = re.search(r"/start/([\w-]+)", providers.email.outbox[-1].text).group(1)
    assert first != second and len(db.scalars(select(ClaimLink)).all()) == 2
    assert client.get(f"{START}/{first}").status_code == 200 and client.get(f"{START}/{second}").status_code == 200
