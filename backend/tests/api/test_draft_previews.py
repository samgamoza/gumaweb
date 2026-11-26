"""Onboarding funnel A7b: polish review, preview images, and the email that shows them."""

from __future__ import annotations

import re
import uuid

import pytest
from sqlalchemy import select

from app.models import DraftPreview, FactoryJob, Website, WebsiteContent
from app.services import lead_compiler
from app.services.draft_prep import DraftPrep
from app.services.outbound_engine import OutboundEngine
from app.services.preview_capture import Shot
from app.services.providers import providers
from app.workers.factory_worker import FactoryWorker

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")
PIPELINE = "/api/v1/pipeline"


class FakeCapture:
    name = "fake"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def capture(self, files):
        self.calls += 1
        if self.fail:
            raise RuntimeError("chromium not installed")
        assert "index.html" in files
        return [Shot("desktop", PNG, "image/png"), Shot("phone", PNG, "image/png")]


@pytest.fixture
def engine_settings(settings, monkeypatch):
    monkeypatch.setattr(settings, "outbound_quiet_hours_start", 0)
    monkeypatch.setattr(settings, "outbound_quiet_hours_end", 0)
    return settings


@pytest.fixture
def worker(session_factory, settings):
    return FactoryWorker(session_factory, settings, worker_id="test")


@pytest.fixture
def built(client, admin_headers, db):
    """A private draft that just entered the pipeline (draft_ready), not yet prepared."""
    business = client.post("/api/v1/businesses", headers=admin_headers, json={
        "name": "Lim Hardware", "city": "Angeles City", "province": "Pampanga", "industry": "hardware",
        "phone": "0917 555 0177", "email": "lim.hardware@gmail.com"}).json()
    created = client.post("/api/v1/websites/generate", json={"business_id": business["id"], "publish": False},
                          headers=admin_headers)
    website = db.get(Website, uuid.UUID(created.json()["id"]))
    assert lead_compiler.draft_built(db, website)
    db.commit()
    return website


def tick(db, settings):
    db.expire_all()
    return OutboundEngine(db, settings).tick()


def test_a_new_draft_is_prepared_before_it_is_emailed(client, built, engine_settings, worker, db):
    job = db.scalar(select(FactoryJob).where(FactoryJob.kind == "prepare_draft"))
    assert job is not None and job.dedupe_key == f"prepare:{built.id}"
    assert tick(db, engine_settings)["enrolled"] == 0  # not reviewed yet: waits

    worker.drain()
    db.expire_all()
    row = db.scalar(select(DraftPreview))
    assert row.ready and row.review["checks"] == {"quality_complete": True, "copy_clean": True, "hero_image": True,
                                                  "services": True, "contact": True}
    assert row.desktop_key is None  # PREVIEW_CAPTURE_BACKEND=none: no pictures

    assert tick(db, engine_settings)["sent"] == 1
    sent = providers.email.outbox[-1]
    assert "See and claim your website" in sent.html and "/start/" in sent.html
    assert "/public/previews/" not in sent.html  # no image without a capture backend
    assert "/start/" in sent.text  # the text part stands alone


def test_captured_images_lead_the_email_and_are_served_privately(client, built, engine_settings, monkeypatch, db):
    fake = FakeCapture()
    monkeypatch.setattr(providers, "previews", fake)
    row = DraftPrep(db, engine_settings).prepare(built)
    db.commit()
    assert fake.calls == 1 and row.desktop_key and row.phone_key and row.captured_at

    tick(db, engine_settings)
    html = providers.email.outbox[-1].html
    urls = re.findall(r'src="([^"]+/public/previews/[^"]+)"', html)
    assert [u.rsplit("/", 1)[1] for u in urls] == ["desktop", "phone"]
    assert 'alt="Preview of the Lim Hardware website"' in html
    assert row.token in urls[0] and "/start/" not in urls[0]  # unrelated to the claim link

    image = client.get(f"/api/v1/public/previews/{row.token}/desktop")
    assert image.status_code == 200 and image.content == PNG and image.headers["content-type"] == "image/png"
    assert image.headers["x-robots-tag"] == "noindex"
    assert client.get(f"/api/v1/public/previews/{row.token}/thumbnail").status_code == 404
    assert client.get("/api/v1/public/previews/nope/desktop").status_code == 404


def test_a_failed_capture_never_holds_a_draft_back(client, built, engine_settings, monkeypatch, db):
    monkeypatch.setattr(providers, "previews", FakeCapture(fail=True))
    row = DraftPrep(db, engine_settings).prepare(built)
    db.commit()
    assert row.ready and row.desktop_key is None and "chromium" in row.capture_error
    assert tick(db, engine_settings)["sent"] == 1


def test_a_draft_short_of_the_bar_is_held_until_fixed_or_approved(client, built, admin_headers, readonly_headers,
                                                                  engine_settings, db):
    hero = db.scalar(select(WebsiteContent).where(WebsiteContent.website_id == built.id,
                                                  WebsiteContent.section_key == "hero"))
    hero.content = {k: v for k, v in hero.content.items() if k != "image"}
    db.commit()
    row = DraftPrep(db, engine_settings).prepare(built)
    db.commit()
    assert not row.ready and row.review["issues"] == ["hero has no image"]
    assert tick(db, engine_settings)["enrolled"] == 0

    held = client.get(f"{PIPELINE}/drafts?held=true", headers=readonly_headers).json()
    assert [(d["business_name"], d["issues"]) for d in held] == [("Lim Hardware", ["hero has no image"])]
    assert client.get(f"{PIPELINE}/drafts?held=false", headers=readonly_headers).json() == []

    assert client.post(f"{PIPELINE}/drafts/{built.id}/approve", headers=readonly_headers).status_code == 403
    approved = client.post(f"{PIPELINE}/drafts/{built.id}/approve", headers=admin_headers)
    assert approved.status_code == 200 and approved.json()["ready"] and approved.json()["approved"]
    rerun = client.post(f"{PIPELINE}/drafts/{built.id}/prepare", headers=admin_headers).json()
    assert rerun["ready"] and rerun["issues"] == ["hero has no image"]  # approval survives a re-run
    assert tick(db, engine_settings)["enrolled"] == 1


def test_live_sites_keep_the_plain_email(client, published_site, engine_settings, db):
    tick(db, engine_settings)
    sent = providers.email.outbox[-1]
    assert "See and claim your website" not in sent.html and "/public/outreach/click/" in sent.text
