"""Domain-level suppression end to end, and contact provenance (port plan step 2)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.domains.business_discovery.contacts import (
    ContactKind,
    ContactObservation,
    PolicyDecision,
    ValueType,
    VerificationStatus,
)
from app.domains.outreach.suppression import SuppressionKind, SuppressionReason
from app.models import AuditLog, Business, BusinessContact, OutreachMessage, OutreachSuppression
from app.services.contact_service import ContactService
from app.services.outreach_service import OutreachService
from app.services.providers import providers
from app.services.support import SYSTEM
from app.services.suppression_service import SuppressionService

SUPPRESSIONS = "/api/v1/outreach/suppressions"


# --- API ------------------------------------------------------------------------------------------


def test_add_list_check_and_remove_suppressions(client, admin_headers):
    created = client.post(SUPPRESSIONS, json={"kind": "domain", "value": "WWW.Spam.PH", "reason": "legal",
                                              "note": "regulator request #42"}, headers=admin_headers)
    assert created.status_code == 201, created.text
    assert created.json() | {"kind": "domain", "value": "spam.ph", "reason": "legal"} == created.json()

    again = client.post(SUPPRESSIONS, json={"kind": "domain", "value": "spam.ph"}, headers=admin_headers)
    assert again.status_code == 200 and again.json()["id"] == created.json()["id"]  # idempotent

    client.post(SUPPRESSIONS, json={"value": "Owner@Shop.ph"}, headers=admin_headers)
    listed = client.get(SUPPRESSIONS, headers=admin_headers).json()
    assert {(s["kind"], s["value"]) for s in listed} == {("domain", "spam.ph"), ("email", "owner@shop.ph")}
    only_domains = client.get(SUPPRESSIONS, params={"kind": "domain"}, headers=admin_headers).json()
    assert [s["value"] for s in only_domains] == ["spam.ph"]

    check = client.get(f"{SUPPRESSIONS}/check", params={"email": "anyone@spam.ph"}, headers=admin_headers).json()
    assert check == {"email": "anyone@spam.ph", "suppressed": True, "matched_kind": "domain",
                     "matched_value": "spam.ph"}
    clear = client.get(f"{SUPPRESSIONS}/check", params={"email": "x@sub.spam.ph"}, headers=admin_headers).json()
    assert clear["suppressed"] is False  # subdomains need their own entry

    assert client.delete(f"{SUPPRESSIONS}/domain/spam.ph", headers=admin_headers).status_code == 204
    assert client.delete(f"{SUPPRESSIONS}/domain/spam.ph", headers=admin_headers).status_code == 404


def test_invalid_values_are_rejected(client, admin_headers):
    bad_email = client.post(SUPPRESSIONS, json={"kind": "email", "value": "not-an-email"}, headers=admin_headers)
    bad_domain = client.post(SUPPRESSIONS, json={"kind": "domain", "value": "a@b.ph"}, headers=admin_headers)
    assert bad_email.status_code == 422 and bad_domain.status_code == 422


def test_staff_may_add_but_only_admin_may_remove(client, admin_headers, operator_headers, readonly_headers):
    assert client.post(SUPPRESSIONS, json={"value": "a@b.ph"}, headers=readonly_headers).status_code == 403
    assert client.post(SUPPRESSIONS, json={"value": "a@b.ph"}, headers=operator_headers).status_code == 201
    assert client.get(SUPPRESSIONS, headers=readonly_headers).status_code == 200
    assert client.delete(f"{SUPPRESSIONS}/email/a@b.ph", headers=operator_headers).status_code == 403
    assert client.delete(f"{SUPPRESSIONS}/email/a@b.ph", headers=admin_headers).status_code == 204


def test_add_and_remove_are_audited(client, admin_headers, db):
    client.post(SUPPRESSIONS, json={"kind": "domain", "value": "acme.ph"}, headers=admin_headers)
    client.delete(f"{SUPPRESSIONS}/domain/acme.ph", headers=admin_headers)
    actions = db.scalars(select(AuditLog.action).where(AuditLog.entity_type == "outreach_suppression")).all()
    assert sorted(actions) == ["outreach.suppression_added", "outreach.suppression_removed"]


# --- outreach honours domain suppression ----------------------------------------------------------


def test_launch_skips_businesses_at_a_suppressed_domain(client, admin_headers, published_site):
    client.post(SUPPRESSIONS, json={"kind": "domain", "value": "gmail.com"}, headers=admin_headers)
    launched = client.post("/api/v1/outreach/campaign", json={"name": "c"}, headers=admin_headers).json()
    assert launched["enrolled_businesses"] == 0


def test_launch_matches_suppressed_email_case_insensitively(client, admin_headers, published_site, db):
    db.get(Business, uuid.UUID(published_site["business"]["id"])).email = "Santos.Plumbing@Gmail.com"
    db.commit()
    client.post(SUPPRESSIONS, json={"value": "santos.plumbing@gmail.com"}, headers=admin_headers)
    launched = client.post("/api/v1/outreach/campaign", json={"name": "c"}, headers=admin_headers).json()
    assert launched["enrolled_businesses"] == 0


def test_dispatch_skips_messages_once_their_domain_is_suppressed(client, admin_headers, published_site):
    launched = client.post("/api/v1/outreach/campaign", json={"name": "c"}, headers=admin_headers).json()
    assert launched["enrolled_businesses"] == 1
    client.post(SUPPRESSIONS, json={"kind": "domain", "value": "gmail.com"}, headers=admin_headers)
    result = client.post(f"/api/v1/outreach/campaigns/{launched['campaign_id']}/dispatch", headers=admin_headers)
    assert result.json() == {"sent": 0, "skipped": 1, "failed": 0}


def test_unsubscribe_records_the_address_even_when_its_domain_is_suppressed(client, admin_headers, published_site,
                                                                           db, settings):
    launched = client.post("/api/v1/outreach/campaign", json={"name": "c"}, headers=admin_headers).json()
    client.post(f"/api/v1/outreach/campaigns/{launched['campaign_id']}/dispatch", headers=admin_headers)
    token = re.search(r"/public/outreach/unsubscribe/([\w-]+)", providers.email.outbox[-1].text).group(1)
    client.post(SUPPRESSIONS, json={"kind": "domain", "value": "gmail.com"}, headers=admin_headers)

    assert "unsubscribed" in client.get(f"/api/v1/public/outreach/unsubscribe/{token}").text
    rows = {(s.kind, s.value, s.reason) for s in db.scalars(select(OutreachSuppression))}
    assert (SuppressionKind.EMAIL, "santos.plumbing@gmail.com", "unsubscribed") in rows

    # Lifting the domain suppression must not re-subscribe the person who opted out.
    client.delete(f"{SUPPRESSIONS}/domain/gmail.com", headers=admin_headers)
    later = OutreachService(db, settings).dispatch_due(now=datetime.now(UTC) + timedelta(days=30))
    assert later.sent == 0
    statuses = set(db.scalars(select(OutreachMessage.status)))
    assert "scheduled" not in statuses

    # Unsubscribing twice is harmless.
    assert "unsubscribed" in client.get(f"/api/v1/public/outreach/unsubscribe/{token}").text


# --- contact provenance ---------------------------------------------------------------------------


def _business(db, email: str | None = None, phone: str | None = None) -> Business:
    business = Business(name="Acme Bakery", slug=f"acme-{uuid.uuid4().hex[:8]}", dedupe_key=uuid.uuid4().hex,
                        email=email, phone=phone)
    db.add(business)
    db.commit()
    return business


def test_records_provenance_and_promotes_an_observed_email(db):
    business = _business(db)
    result = ContactService(db).record(business, [
        ContactObservation(ContactKind.EMAIL, " Hello@AcmeBakery.ph ", "website_scrape",
                           source_ref="https://acmebakery.ph/contact", confidence=0.9),
        ContactObservation(ContactKind.PHONE, "0917 123 4567", "osm", source_ref="node/123"),
    ])
    db.commit()
    assert (result.created, result.blocked, result.invalid) == (2, 0, 0)
    assert business.email == "hello@acmebakery.ph" and business.phone == "639171234567"
    assert result.promoted == {"email": "hello@acmebakery.ph", "phone": "639171234567"}
    stored = {c.kind: c for c in ContactService(db).contacts_for(business.id)}
    email = stored[ContactKind.EMAIL]
    assert (email.source, email.source_ref, email.value_type, email.policy_decision) == (
        "website_scrape", "https://acmebakery.ph/contact", ValueType.OBSERVED, PolicyDecision.ALLOW)
    assert email.acquired_at is not None


def test_predicted_email_is_stored_but_never_promoted_or_contacted(db):
    business = _business(db)
    result = ContactService(db).record(business, [
        ContactObservation(ContactKind.EMAIL, "owner@acmebakery.ph", "rdap", value_type=ValueType.PREDICTED,
                           confidence=0.95),
    ])
    db.commit()
    assert result.created == 1 and result.promoted == {}
    assert business.email is None  # so outreach (which reads Business.email) can never reach it


def test_suppressed_contacts_are_blocked_with_a_reason(db):
    SuppressionService(db).add(SuppressionKind.DOMAIN, "blocked.ph", SuppressionReason.LEGAL, SYSTEM)
    SuppressionService(db).add(SuppressionKind.EMAIL, "me@open.ph", SuppressionReason.REQUESTED, SYSTEM)
    business = _business(db)
    result = ContactService(db).record(business, [
        ContactObservation(ContactKind.EMAIL, "info@blocked.ph", "website_scrape"),
        ContactObservation(ContactKind.EMAIL, "me@open.ph", "website_scrape"),
        ContactObservation(ContactKind.EMAIL, "ok@open.ph", "website_scrape", confidence=0.5),
    ])
    db.commit()
    assert result.blocked == 2
    codes = {c.value: (c.policy_decision, c.reason_code) for c in ContactService(db).contacts_for(business.id)}
    assert codes["info@blocked.ph"] == (PolicyDecision.BLOCKED, "SUPPRESSED_DOMAIN")
    assert codes["me@open.ph"] == (PolicyDecision.BLOCKED, "SUPPRESSED_EMAIL")
    assert business.email == "ok@open.ph"  # the only allowed one, despite the lowest confidence


def test_existing_primary_is_kept_unless_it_is_suppressed(db):
    keeper = _business(db, email="owner@kept.ph")
    ContactService(db).record(keeper, [ContactObservation(ContactKind.EMAIL, "other@kept.ph", "website_scrape")])
    assert keeper.email == "owner@kept.ph"

    SuppressionService(db).add(SuppressionKind.DOMAIN, "gone.ph", SuppressionReason.LEGAL, SYSTEM)
    stale = _business(db, email="owner@gone.ph")
    result = ContactService(db).record(stale, [ContactObservation(ContactKind.EMAIL, "hi@fresh.ph", "osm")])
    db.commit()
    assert result.cleared == ["email"]
    assert stale.email == "hi@fresh.ph"


def test_repeat_sightings_only_strengthen_a_contact(db):
    business = _business(db)
    service = ContactService(db)
    service.record(business, [ContactObservation(ContactKind.EMAIL, "a@shop.ph", "rdap",
                                                 value_type=ValueType.PREDICTED, confidence=0.4)])
    assert business.email is None
    result = service.record(business, [
        ContactObservation(ContactKind.EMAIL, "A@Shop.ph", "website_scrape", source_ref="https://shop.ph",
                           confidence=0.9, verification_status=VerificationStatus.VERIFIED),
    ])
    db.commit()
    assert (result.created, result.updated) == (0, 1)
    contact = service.contacts_for(business.id)[0]
    assert (contact.value_type, contact.source, contact.confidence, contact.verification_status) == (
        ValueType.OBSERVED, "website_scrape", 0.9, VerificationStatus.VERIFIED)
    assert business.email == "a@shop.ph"  # promoted once a real sighting confirmed the guess

    service.record(business, [ContactObservation(ContactKind.EMAIL, "a@shop.ph", "rdap",
                                                 value_type=ValueType.PREDICTED, confidence=0.1)])
    contact = service.contacts_for(business.id)[0]
    assert (contact.value_type, contact.confidence) == (ValueType.OBSERVED, 0.9)  # a weaker sighting changes nothing


def test_invalid_values_are_counted_not_stored(db):
    business = _business(db)
    result = ContactService(db).record(business, [ContactObservation(ContactKind.EMAIL, "nope", "x"),
                                                  ContactObservation(ContactKind.PHONE, "12", "x")])
    assert result.invalid == 2 and ContactService(db).contacts_for(business.id) == []


def test_contacts_are_deleted_with_their_business(db):
    business = _business(db)
    ContactService(db).record(business, [ContactObservation(ContactKind.EMAIL, "a@b.ph", "x")])
    db.commit()
    db.delete(business)
    db.commit()
    assert db.scalars(select(BusinessContact)).all() == []
