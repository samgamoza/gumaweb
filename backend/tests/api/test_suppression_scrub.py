"""Retroactive suppression scrub (port step 6). Ports the guma_os suppression-scrub cases."""

from __future__ import annotations

import re
import uuid

import pytest
from sqlalchemy import select

from app.domains.business_discovery.contacts import (
    ContactKind,
    ContactObservation,
    PolicyDecision,
    ValueType,
)
from app.domains.outreach.suppression import SuppressionKind, SuppressionReason
from app.models import AuditLog, Business, BusinessContact, Claim, FactoryJob, OutreachMessage
from app.services.contact_service import ContactService
from app.services.providers import providers
from app.services.support import SYSTEM
from app.services.suppression_scrub import scrub
from app.services.suppression_service import SuppressionService
from app.workers.factory_worker import FactoryWorker

SUPPRESSIONS = "/api/v1/outreach/suppressions"


@pytest.fixture
def worker(session_factory, settings):
    return FactoryWorker(session_factory, settings, worker_id="test")


def business_with(db, name: str, *observations: ContactObservation, email: str | None = None) -> Business:
    business = Business(name=name, slug=f"b-{uuid.uuid4().hex[:8]}", dedupe_key=uuid.uuid4().hex, email=email)
    db.add(business)
    db.commit()
    ContactService(db).record(business, list(observations))
    db.commit()
    return business


def seen(value: str, confidence: float = 0.9) -> ContactObservation:
    return ContactObservation(ContactKind.EMAIL, value, "website_scrape", source_ref="https://shop.ph/contact",
                              confidence=confidence)


def guessed(value: str) -> ContactObservation:
    return ContactObservation(ContactKind.EMAIL, value, "rdap", value_type=ValueType.PREDICTED, confidence=0.2)


def contact(db, business: Business, value: str) -> BusinessContact:
    return db.scalar(select(BusinessContact).where(BusinessContact.business_id == business.id,
                                                   BusinessContact.value == value))


def suppress(client, headers, kind: str, value: str) -> None:
    response = client.post(SUPPRESSIONS, json={"kind": kind, "value": value, "reason": "legal"}, headers=headers)
    assert response.status_code == 201, response.text


def test_adding_a_suppression_queues_a_scrub_job(client, admin_headers, db):
    suppress(client, admin_headers, "domain", "WWW.Acme.ph")
    job = db.scalar(select(FactoryJob).where(FactoryJob.kind == "scrub_suppression"))
    assert job.payload == {"kind": "domain", "value": "acme.ph"} and job.dedupe_key == "scrub:domain:acme.ph"
    # Re-adding the same entry is idempotent and queues nothing new.
    client.post(SUPPRESSIONS, json={"kind": "domain", "value": "acme.ph"}, headers=admin_headers)
    assert len(db.scalars(select(FactoryJob).where(FactoryJob.kind == "scrub_suppression")).all()) == 1


def test_exact_email_is_blocked_with_a_trail_and_the_primary_kept(client, admin_headers, worker, db):
    shop = business_with(db, "Shop", seen("owner@shop.ph", 0.95), seen("sales@shop.ph", 0.6))
    other = business_with(db, "Unrelated", seen("hi@other.ph"))
    assert shop.email == "owner@shop.ph"

    suppress(client, admin_headers, "email", "Owner@Shop.ph")
    worker.drain()
    db.expire_all()

    blocked = contact(db, shop, "owner@shop.ph")
    assert (blocked.policy_decision, blocked.reason_code) == (PolicyDecision.BLOCKED, "SUPPRESSED_EMAIL")
    assert blocked.source_ref == "https://shop.ph/contact"  # kept, not deleted: the trail stays reviewable
    # Business.email is the business's own public address (site, claims, owner notices): kept, never marketed to.
    assert db.get(Business, shop.id).email == "owner@shop.ph"
    assert contact(db, shop, "sales@shop.ph").policy_decision == PolicyDecision.ALLOW
    assert contact(db, other, "hi@other.ph").policy_decision == PolicyDecision.ALLOW

    job = db.scalar(select(FactoryJob).where(FactoryJob.kind == "scrub_suppression"))
    assert job.result | {"contacts_blocked": 1, "businesses_now_skipped_by_outreach": 1} == job.result


def test_whole_domain_including_guesses_but_not_subdomains(client, admin_headers, worker, db):
    shop = business_with(db, "Shop", seen("a@acme.ph"), guessed("domains@acme.ph"))
    sub = business_with(db, "Subdomain", seen("x@mail.acme.ph"))  # subdomains need their own entry
    suppress(client, admin_headers, "domain", "acme.ph")
    worker.drain()
    db.expire_all()

    assert contact(db, shop, "a@acme.ph").reason_code == "SUPPRESSED_DOMAIN"
    assert contact(db, shop, "domains@acme.ph").policy_decision == PolicyDecision.BLOCKED
    assert contact(db, sub, "x@mail.acme.ph").policy_decision == PolicyDecision.ALLOW
    job = db.scalar(select(FactoryJob).where(FactoryJob.kind == "scrub_suppression"))
    assert job.result["contacts_blocked"] == 2


def test_businesses_whose_primary_matches_are_counted_and_kept(db, settings):
    imported = business_with(db, "Imported", email="boss@legacy.ph")  # e.g. from a CSV import: no contact rows
    SuppressionService(db).add(SuppressionKind.DOMAIN, "legacy.ph", SuppressionReason.LEGAL, SYSTEM)
    result = scrub(db, settings, SuppressionKind.DOMAIN, "legacy.ph")
    assert (result.businesses_now_skipped_by_outreach, result.contacts_blocked) == (1, 0)
    assert db.get(Business, imported.id).email == "boss@legacy.ph"


def test_queued_outreach_is_skipped_and_sent_messages_are_left_alone(client, admin_headers, published_site, worker,
                                                                     db):
    launched = client.post("/api/v1/outreach/campaign", json={"name": "c"}, headers=admin_headers).json()
    client.post(f"/api/v1/outreach/campaigns/{launched['campaign_id']}/dispatch", headers=admin_headers)
    suppress(client, admin_headers, "domain", "gmail.com")  # the fixture business is santos.plumbing@gmail.com
    worker.drain()
    statuses = sorted((m.step, m.status.value, m.error) for m in db.scalars(select(OutreachMessage)))
    assert statuses[0][1] == "sent"  # Day 0 went out before the suppression; history stays truthful
    assert all(status == "skipped" and error == "suppressed" for _, status, error in statuses[1:])
    assert len(statuses) == 4


def test_nothing_matching_is_a_no_op(client, admin_headers, worker, db):
    shop = business_with(db, "Shop", seen("owner@shop.ph"))
    suppress(client, admin_headers, "domain", "nobody-here.ph")
    worker.drain()
    job = db.scalar(select(FactoryJob).where(FactoryJob.kind == "scrub_suppression"))
    assert (job.result["contacts_blocked"], job.result["messages_skipped"],
            job.result["businesses_now_skipped_by_outreach"]) == (0, 0, 0)
    assert db.get(Business, shop.id).email == "owner@shop.ph"


def test_lifting_the_suppression_before_the_job_runs_skips_the_scrub(client, admin_headers, worker, db):
    shop = business_with(db, "Shop", seen("owner@shop.ph"))
    suppress(client, admin_headers, "email", "owner@shop.ph")
    client.delete(f"{SUPPRESSIONS}/email/owner@shop.ph", headers=admin_headers)
    worker.drain()
    job = db.scalar(select(FactoryJob).where(FactoryJob.kind == "scrub_suppression"))
    assert job.result["skipped"] == "suppression_removed"
    assert contact(db, shop, "owner@shop.ph").policy_decision == PolicyDecision.ALLOW


def test_scrub_is_idempotent_and_audited(db, settings):
    business_with(db, "Shop", seen("owner@shop.ph"))
    SuppressionService(db).add(SuppressionKind.EMAIL, "owner@shop.ph", SuppressionReason.LEGAL, SYSTEM)
    first = scrub(db, settings, SuppressionKind.EMAIL, "owner@shop.ph")
    second = scrub(db, settings, SuppressionKind.EMAIL, "owner@shop.ph")
    assert first.contacts_blocked == 1
    assert (second.contacts_blocked, second.messages_skipped) == (0, 0)
    actions = db.scalars(select(AuditLog.action).where(AuditLog.action == "outreach.suppression_scrubbed")).all()
    assert len(actions) == 2


def test_unsubscribing_scrubs_without_breaking_the_owners_claim(client, admin_headers, published_site, worker, db):
    business_id = uuid.UUID(published_site["business"]["id"])
    launched = client.post("/api/v1/outreach/campaign", json={"name": "c"}, headers=admin_headers).json()
    client.post(f"/api/v1/outreach/campaigns/{launched['campaign_id']}/dispatch", headers=admin_headers)
    token = re.search(r"/public/outreach/unsubscribe/([\w-]+)", providers.email.outbox[-1].text).group(1)
    client.get(f"/api/v1/public/outreach/unsubscribe/{token}")
    worker.drain()
    db.expire_all()
    assert db.get(Business, business_id).email == "santos.plumbing@gmail.com"  # still their public address
    assert db.scalar(select(FactoryJob.result).where(FactoryJob.kind == "scrub_suppression"))[
        "businesses_now_skipped_by_outreach"] == 1

    # The owner can still claim with the email on file, which keeps the claim risk low.
    claim = client.post("/api/v1/claims", json={"subdomain": published_site["website"]["subdomain"],
                                                "claimant_name": "Jose", "claimant_email": "santos.plumbing@gmail.com"})
    assert claim.status_code in (200, 201), claim.text
    stored = db.scalar(select(Claim).where(Claim.business_id == business_id))
    assert any("matches the business email on record" in f for f in stored.risk_factors)
