"""Outbound engine A2: enrollment, behaviour-driven follow-ups, guardrails, stopping, and the playbook API."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import OutreachMessage, PlaybookEnrollment, ProspectTask
from app.models.sales import EnrollmentStatus
from app.services.outbound_engine import OutboundEngine, run_outbound_job
from app.services.prospect_service import ProspectService
from app.services.providers import providers
from app.workers.factory_worker import FactoryWorker

PIPELINE = "/api/v1/pipeline"


@pytest.fixture
def worker(session_factory, settings):
    return FactoryWorker(session_factory, settings, worker_id="test")


@pytest.fixture
def engine_settings(settings, monkeypatch):
    monkeypatch.setattr(settings, "outbound_quiet_hours_start", 0)  # no quiet hours unless a test sets them
    monkeypatch.setattr(settings, "outbound_quiet_hours_end", 0)
    return settings


def tick(db, settings, hours: float = 0, base: datetime | None = None) -> dict[str, int]:
    db.expire_all()
    return OutboundEngine(db, settings, now=(base or BASE[0]) + timedelta(hours=hours)).tick()


BASE: list[datetime] = [datetime.now(UTC)]


@pytest.fixture(autouse=True)
def _base_time():
    BASE[0] = datetime.now(UTC)


def enrollment(db) -> PlaybookEnrollment:
    db.expire_all()
    return db.scalar(select(PlaybookEnrollment))


def playbook_emails() -> list[str]:
    return [m.subject for m in providers.email.outbox if "claim" in m.subject.lower() or "website" in m.subject.lower()]


def token_of(db, step: int) -> str:
    return db.scalar(select(OutreachMessage.tracking_token).where(OutreachMessage.step == step))


def test_enrolls_a_ready_prospect_and_sends_the_intro_once(client, published_site, engine_settings, db):
    stats = tick(db, engine_settings)
    assert stats["enrolled"] == 1 and stats["sent"] == 1
    assert providers.email.outbox[-1].subject == "Your website is ready, Santos Plumbing Services"
    assert "/public/outreach/click/" in providers.email.outbox[-1].text  # tracked claim link
    assert "Unsubscribe:" in providers.email.outbox[-1].text
    prospect = ProspectService(db).for_business(uuid.UUID(published_site["business"]["id"]))
    assert prospect.stage.value == "contacted"

    again = tick(db, engine_settings, hours=1)
    assert (again["enrolled"], again["sent"]) == (0, 0)
    assert enrollment(db).steps_done["intro"]["status"] == "sent"


def test_unopened_intro_is_resent_after_48h_but_an_opened_one_is_not(client, published_site, engine_settings, db):
    tick(db, engine_settings)
    assert tick(db, engine_settings, hours=47)["sent"] == 0
    assert tick(db, engine_settings, hours=49)["sent"] == 1
    assert providers.email.outbox[-1].subject == "Santos Plumbing Services: your free website is waiting"


def test_opened_intro_skips_the_resend(client, published_site, engine_settings, db):
    tick(db, engine_settings)
    client.get(f"/api/v1/public/outreach/open/{token_of(db, 0)}.gif")
    tick(db, engine_settings, hours=49)
    assert enrollment(db).steps_done["resend"] == enrollment(db).steps_done["resend"] | {"status": "skipped",
                                                                                         "reason": "opened"}


def test_click_then_abandoned_claim_get_their_own_followups(client, published_site, engine_settings, db):
    tick(db, engine_settings)
    client.get(f"/api/v1/public/outreach/click/{token_of(db, 0)}", follow_redirects=False)
    tick(db, engine_settings, hours=25)
    assert providers.email.outbox[-1].subject == "Your website is still waiting for you"

    client.post("/api/v1/claims", json={"subdomain": published_site["website"]["subdomain"],
                                        "claimant_name": "Jose", "claimant_email": "santos.plumbing@gmail.com"})
    stats = tick(db, engine_settings, hours=50)
    assert stats["sent"] == 1 and providers.email.outbox[-1].subject == "Almost done: finish claiming your website"
    assert enrollment(db).steps_done["resend"]["reason"] == "engaged"  # the click shows they read the intro


def test_claiming_stops_the_enrollment(client, published_site, engine_settings, db):
    tick(db, engine_settings)
    client.post("/api/v1/claims", json={"subdomain": published_site["website"]["subdomain"],
                                        "claimant_name": "Jose", "claimant_email": "santos.plumbing@gmail.com"})
    token = re.search(r"token=([\w-]+)", providers.email.outbox[-1].text).group(1)
    client.post("/api/v1/claims/verify", json={"token": token, "password": "OwnerPass!2026"})
    stats = tick(db, engine_settings, hours=3)
    assert stats["stopped"] == 1 and stats["sent"] == 0
    assert (enrollment(db).status, enrollment(db).stop_reason) == (EnrollmentStatus.STOPPED, "stage:claimed")


def test_do_not_contact_stops_and_a_suppressed_address_is_never_mailed(client, admin_headers, published_site,
                                                                     engine_settings, worker, db):
    tick(db, engine_settings)
    client.post("/api/v1/outreach/suppressions", json={"kind": "domain", "value": "gmail.com", "reason": "requested"},
                headers=admin_headers)
    worker.drain()
    sent_before = len(providers.email.outbox)
    stats = tick(db, engine_settings, hours=49)
    assert stats["stopped"] == 1 and len(providers.email.outbox) == sent_before


def test_quiet_hours_and_weekly_cap_defer_instead_of_skipping(client, published_site, settings, monkeypatch, db):
    monkeypatch.setattr(settings, "outbound_quiet_hours_start", 20)
    monkeypatch.setattr(settings, "outbound_quiet_hours_end", 8)
    night = datetime(2026, 11, 26, 14, tzinfo=UTC)  # 22:00 in Manila
    stats = OutboundEngine(db, settings, now=night).tick()
    assert (stats["enrolled"], stats["sent"], stats["deferred"]) == (1, 0, 1)
    assert "intro" not in enrollment(db).steps_done
    db.expire_all()
    assert OutboundEngine(db, settings, now=night + timedelta(hours=11)).tick()["sent"] == 1  # 09:00

    monkeypatch.setattr(settings, "outbound_max_touches_per_week", 1)
    db.expire_all()
    stats = OutboundEngine(db, settings, now=night + timedelta(hours=11 + 49)).tick()  # resend is due
    assert (stats["sent"], stats["deferred"]) == (0, 1)


def test_unengaged_high_scorer_gets_a_call_task(client, published_site, engine_settings, db):
    tick(db, engine_settings)
    prospect = ProspectService(db).for_business(uuid.UUID(published_site["business"]["id"]))
    tick(db, engine_settings, hours=73)
    expected = "sent" if (prospect.score or 0) >= 70 else "skipped"
    assert enrollment(db).steps_done["call"]["status"] == expected

    task_titles = [t.title for t in db.scalars(select(ProspectTask))]
    assert task_titles == (["Call Santos Plumbing Services about their free website"] if expected == "sent" else [])


def test_enrollment_rules_drafts_daily_cap_and_manual_campaigns(client, admin_headers, published_site, settings,
                                                                engine_settings, monkeypatch, db):
    monkeypatch.setattr(settings, "outbound_daily_enrollment_limit", 0)
    assert tick(db, engine_settings)["enrolled"] == 0

    monkeypatch.setattr(settings, "outbound_daily_enrollment_limit", 100)
    launched = client.post("/api/v1/outreach/campaign", json={"name": "manual"}, headers=admin_headers).json()
    assert launched["scheduled_messages"] == 4  # a manual campaign owns this business for now
    assert tick(db, engine_settings)["enrolled"] == 0


def test_engine_switch_job_and_playbook_api(client, admin_headers, readonly_headers, published_site, settings,
                                            engine_settings, worker, db):
    assert run_outbound_job(db, settings, {}) == {"skipped": "disabled"}

    queued = client.post(f"{PIPELINE}/outbound/run", headers=admin_headers)
    assert queued.status_code == 202 and queued.json()["status"] == "queued"
    worker.drain()
    books = client.get(f"{PIPELINE}/playbooks", headers=readonly_headers).json()
    assert len(books) == 1 and books[0]["name"] == "Claim your website"
    assert books[0]["enrollments"]["active"] == 1
    intro = next(s for s in books[0]["step_stats"] if s["key"] == "intro")
    assert intro["sent"] == 1

    book_id = books[0]["id"]
    assert client.patch(f"{PIPELINE}/playbooks/{book_id}", headers=readonly_headers,
                        json={"active": False}).status_code == 403
    bad = client.patch(f"{PIPELINE}/playbooks/{book_id}", headers=admin_headers,
                       json={"steps": [{"key": "x", "channel": "fax", "when": "enrolled"}]})
    assert bad.status_code == 422
    paused = client.patch(f"{PIPELINE}/playbooks/{book_id}", headers=admin_headers, json={"active": False})
    assert paused.status_code == 200 and paused.json()["active"] is False
