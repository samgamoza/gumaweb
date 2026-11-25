"""Outbound engine A1: automatic site compilation, outbound priority score, readiness, and the pipeline API."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.domains.business_discovery.contacts import ContactKind, ContactObservation, ValueType
from app.domains.website_factory.enums import WebsiteStatus
from app.models import Business, FactoryJob, OutreachMessage, Prospect, ProspectActivity, Website
from app.services import lead_compiler
from app.services.contact_service import ContactService
from app.services.prospect_service import ProspectService
from app.workers.factory_worker import FactoryWorker

PIPELINE = "/api/v1/pipeline"


@pytest.fixture
def worker(session_factory, settings):
    return FactoryWorker(session_factory, settings, worker_id="test")


@pytest.fixture
def auto_compile(settings, monkeypatch):
    monkeypatch.setattr(settings, "auto_compile_enabled", True)
    monkeypatch.setattr(settings, "auto_compile_daily_limit", 50)
    return settings


def candidate(client, admin_headers, db, name="Reyes Bakery") -> Business:
    created = client.post("/api/v1/businesses", headers=admin_headers, json={
        "name": name, "city": "Angeles City", "industry": "bakery", "phone": "0917 555 0199",
        "email": f"{uuid.uuid4().hex[:6]}@gmail.com", "facebook": "facebook.com/reyes"}).json()
    business = db.get(Business, uuid.UUID(created["id"]))
    assert business.generate_candidate, business.score_breakdown
    return business


def auto_jobs(db) -> list[FactoryJob]:
    return [j for j in db.scalars(select(FactoryJob).where(FactoryJob.kind == "generate_website"))
            if j.payload.get("source") == "auto_compile"]


def test_compiler_decisions(client, admin_headers, auto_compile, published_site, db, monkeypatch):
    business = candidate(client, admin_headers, db)
    assert lead_compiler.consider(db, auto_compile, business) == "queued"
    assert lead_compiler.consider(db, auto_compile, business) == "already_queued"
    job = auto_jobs(db)[0]
    assert job.payload["publish"] is False and job.dedupe_key == f"generate:{business.id}"  # private draft only

    published = db.get(Business, uuid.UUID(published_site["business"]["id"]))
    assert lead_compiler.consider(db, auto_compile, published) == "has_site"

    monkeypatch.setattr(auto_compile, "auto_compile_daily_limit", 1)
    assert lead_compiler.consider(db, auto_compile, candidate(client, admin_headers, db, "Cruz Bakery")) == "daily_cap"
    monkeypatch.setattr(auto_compile, "auto_compile_enabled", False)
    assert lead_compiler.consider(db, auto_compile, business) == "disabled"


def test_discovery_builds_private_drafts_unattended_up_to_the_daily_cap(client, admin_headers, auto_compile, worker,
                                                                       db, monkeypatch):
    monkeypatch.setattr(auto_compile, "enrich_after_discovery", False)
    monkeypatch.setattr(auto_compile, "auto_compile_daily_limit", 2)
    client.post("/api/v1/businesses/discover", json={"source": "fixture", "category": "bakery"}, headers=admin_headers)
    worker.drain()
    candidates = db.scalars(select(Business).where(Business.generate_candidate.is_(True))).all()
    assert candidates, "the fixture source should yield at least one site candidate"
    expected = min(2, len(candidates))
    jobs = auto_jobs(db)
    assert len(jobs) == expected and all(j.status.value == "succeeded" for j in jobs)

    websites = db.scalars(select(Website)).all()
    assert len(websites) == expected
    assert all(w.status is not WebsiteStatus.PUBLISHED and w.published_at is None for w in websites)  # nothing live
    entered = [j for j in jobs if j.result.get("in_pipeline")]  # drafts that passed the quality gate
    prospects = db.scalars(select(Prospect)).all()
    assert len(prospects) == len(entered) and all(p.score is not None for p in prospects)
    for p in prospects:
        assert [a.type.value for a in db.scalars(select(ProspectActivity).where(
            ProspectActivity.prospect_id == p.id))] == ["draft_ready"]


def test_a_draft_that_fails_the_quality_gate_stays_out_of_the_pipeline(client, admin_headers, auto_compile, db):
    business = candidate(client, admin_headers, db)
    draft = Website(business_id=business.id, subdomain=f"d-{uuid.uuid4().hex[:8]}",
                    quality_report={"publishable": False, "issues": ["missing hero image"]})
    db.add(draft)
    db.flush()
    assert lead_compiler.draft_built(db, draft) is False
    assert ProspectService(db).for_business(business.id) is None
    draft.quality_report = {"publishable": True}
    assert lead_compiler.draft_built(db, draft) is True
    assert ProspectService(db).for_business(business.id).stage.value == "new"


def test_disabled_by_default_discovery_queues_no_sites(client, admin_headers, worker, db, settings, monkeypatch):
    monkeypatch.setattr(settings, "enrich_after_discovery", False)
    client.post("/api/v1/businesses/discover", json={"source": "fixture", "category": "bakery"}, headers=admin_headers)
    worker.drain()
    assert auto_jobs(db) == []


def test_priority_reflects_contact_quality_engagement_and_suppression(client, admin_headers, published_site, worker,
                                                                      db):
    business_id = uuid.UUID(published_site["business"]["id"])
    business = db.get(Business, business_id)
    prospect = ProspectService(db).for_business(business_id)
    fit = round(0.4 * business.score)
    assert prospect.score == fit + 12 + 8 and prospect.channels == ["email", "phone"]  # listed email + phone

    # An observed email on their own website is stronger than a bare listing.
    ContactService(db).record(business, [ContactObservation(ContactKind.EMAIL, "hello@santos.ph", "website_scrape",
                                                            value_type=ValueType.OBSERVED)])
    db.commit()
    assert ProspectService(db).rescore(business_id).score == fit + 16 + 8
    db.commit()  # release the row lock before the API (another connection) updates this prospect

    launched = client.post("/api/v1/outreach/campaign", json={"name": "c"}, headers=admin_headers).json()
    client.post(f"/api/v1/outreach/campaigns/{launched['campaign_id']}/dispatch", headers=admin_headers)
    token = db.scalar(select(OutreachMessage.tracking_token).where(OutreachMessage.step == 0))
    client.get(f"/api/v1/public/outreach/click/{token}", follow_redirects=False)
    db.expire_all()
    assert ProspectService(db).for_business(business_id).score == fit + 16 + 8 + 20

    client.post("/api/v1/outreach/suppressions", json={"kind": "domain", "value": "gmail.com", "reason": "requested"},
                headers=admin_headers)
    worker.drain()
    db.expire_all()
    rows = client.get(f"{PIPELINE}/prospects?ready=true", headers=admin_headers).json()
    assert rows == []  # closed (do not contact): the engine leaves it alone


def test_pipeline_api(client, admin_headers, readonly_headers, published_site):
    business_id = published_site["business"]["id"]
    summary = client.get(f"{PIPELINE}/summary", headers=readonly_headers).json()
    assert summary["stages"]["new"] == 1 and summary["stages"]["won"] == 0 and summary["ready"] == 1
    assert summary["auto_compile_enabled"] is False and summary["auto_compiled_today"] == 0

    rows = client.get(f"{PIPELINE}/prospects?ready=true", headers=readonly_headers).json()
    assert [r["business_name"] for r in rows] == ["Santos Plumbing Services"]
    assert rows[0]["channels"] == ["email", "phone"] and rows[0]["score_reasons"]

    detail = client.get(f"{PIPELINE}/prospects/{business_id}", headers=readonly_headers).json()
    assert [a["type"] for a in detail["timeline"]] == ["site_published"]
    assert client.get(f"{PIPELINE}/prospects/{uuid.uuid4()}", headers=readonly_headers).status_code == 404
    assert client.get(f"{PIPELINE}/summary").status_code == 401
