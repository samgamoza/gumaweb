"""Phase 2: job queue + workers, AI content pipeline, image factory, media library, SEO audit, analytics."""

import re

import pytest

from app.agents import registry
from app.domains.website_factory.jobs import JobKind, JobStatus
from app.models import FactoryJob, WebsiteContent
from app.services.job_queue import JobQueue
from app.services.providers import providers
from app.workers.factory_worker import FactoryWorker
from tests.fakes import FakeLLM, make_png


def _business(client, headers, name="Santos Plumbing Services", **extra):
    payload = {"name": name, "city": "Angeles City", "province": "Pampanga", "phone": "0917 555 0102",
               "email": "santos.plumbing@gmail.com", **extra}
    return client.post("/api/v1/businesses", json=payload, headers=headers).json()


@pytest.fixture
def ai_enabled(monkeypatch, settings):
    llm = FakeLLM()
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(registry, "build_llm_client", lambda _settings: llm)
    return llm


def test_batch_generation_runs_through_queue_and_workers(client, admin_headers, session_factory, settings,
                                                         sites_dir):
    ids = [_business(client, admin_headers, name=f"Glow Beauty Salon {i}", industry="beauty")["id"]
           for i in range(3)]
    queued = client.post("/api/v1/websites/generate-batch", json={"publish": True}, headers=admin_headers)
    assert queued.status_code == 202 and queued.json() == {"enqueued": 3, "skipped": 0}
    # identical batch is deduplicated while jobs are pending
    assert client.post("/api/v1/websites/generate-batch", json={"business_ids": ids},
                       headers=admin_headers).json() == {"enqueued": 0, "skipped": 3}
    assert client.get("/api/v1/admin/jobs/stats", headers=admin_headers).json()["queued"] == 3

    processed = FactoryWorker(session_factory, settings, worker_id="test-worker").drain()
    assert processed == 3
    jobs = client.get("/api/v1/admin/jobs", headers=admin_headers).json()
    assert {j["status"] for j in jobs} == {"succeeded"} and all(j["result"]["published"] for j in jobs)

    websites = client.get("/api/v1/websites", headers=admin_headers).json()["items"]
    assert len(websites) == 3 and {w["status"] for w in websites} == {"published"}
    home = (sites_dir / websites[0]["subdomain"] / "index.html").read_text(encoding="utf-8")
    # beauty templates use the premium hero, which now carries library artwork shipped inside the build
    image = re.search(r"assets/img/([0-9a-f-]+)\.svg", home)
    assert image and (sites_dir / websites[0]["subdomain"] / "assets" / "img" / f"{image.group(1)}.svg").exists()


def test_failed_jobs_retry_with_backoff_then_fail(db, session_factory, settings, client, admin_headers):
    queue = JobQueue(db)
    job = queue.enqueue(JobKind.GENERATE_WEBSITE, {"business_id": "not-a-uuid"}, max_attempts=2)
    db.commit()
    worker = FactoryWorker(session_factory, settings)
    assert worker.process_one()
    db.refresh(job)
    assert job.status == JobStatus.QUEUED and job.attempts == 1 and "ValueError" in job.last_error
    job.run_after = job.created_at  # make it due again
    db.commit()
    assert worker.process_one()
    db.refresh(job)
    assert job.status == JobStatus.FAILED
    retried = client.post(f"/api/v1/admin/jobs/{job.id}/retry", headers=admin_headers)
    assert retried.status_code == 200 and retried.json()["status"] == "queued"


def test_ai_content_is_vetted_cached_and_reported(client, admin_headers, ai_enabled, db):
    business = _business(client, admin_headers)
    website = client.post("/api/v1/websites/generate", json={"business_id": business["id"], "publish": True},
                          headers=admin_headers).json()
    blocks = {b["section_key"]: b for b in client.get(f"/api/v1/websites/{website['id']}/content",
                                                      headers=admin_headers).json()}
    assert blocks["hero"]["source"] == "ai"
    assert blocks["hero"]["content"]["headline"] == "Plumbing Help for Homes and Shops in Angeles City"
    assert blocks["contact"]["source"] == "template"
    assert "Gold Plating" not in str(blocks["services"]["content"])
    assert website["quality_report"]["content_generator"] == "llm"

    calls_before = len(ai_enabled.calls)
    client.post(f"/api/v1/websites/{website['id']}/regenerate", json={}, headers=admin_headers)
    assert len(ai_enabled.calls) == calls_before  # unchanged facts -> served from ai_generations cache

    usage = client.get("/api/v1/analytics/ai", headers=admin_headers).json()
    assert usage["enabled"] is True and usage["tokens_total"] == 12000  # 5 sections x (content + review), once
    assert usage["ai_section_share"] > 0.5


def test_inference_outage_still_produces_a_site(client, admin_headers, ai_enabled):
    ai_enabled.fail = True
    business = _business(client, admin_headers)
    website = client.post("/api/v1/websites/generate", json={"business_id": business["id"], "publish": True},
                          headers=admin_headers)
    assert website.status_code == 201 and website.json()["status"] == "published"
    assert any("model unavailable" in n for n in website.json()["quality_report"]["content_notes"])


def _claim(client, subdomain, email="owner@santos.ph"):
    client.post("/api/v1/claims", json={"subdomain": subdomain, "claimant_name": "Jose", "claimant_email": email})
    token = re.search(r"token=([\w-]+)", providers.email.outbox[-1].text).group(1)
    tokens = client.post("/api/v1/claims/verify", json={"token": token, "password": "OwnerPass!2026"}).json()
    return {"Authorization": f"Bearer {tokens['tokens']['access_token']}"}


def test_media_library_gallery_and_seo_gaps(client, admin_headers, sites_dir):
    business = _business(client, admin_headers, name="Coral Bay Beach Resort", industry="resort")
    website = client.post("/api/v1/websites/generate", json={"business_id": business["id"], "publish": True},
                          headers=admin_headers).json()
    headers = _claim(client, website["subdomain"])

    dashboard = client.get("/api/v1/customer/dashboard", headers=headers).json()
    gaps = {g["key"] for g in dashboard["seo"]["content_gaps"]}
    assert "photos" in gaps and "address" in gaps

    assert client.post("/api/v1/customer/media", headers=headers,
                       files={"file": ("x.svg", b"<svg onload=alert(1)>", "image/svg+xml")}).status_code == 422
    uploaded = [client.post("/api/v1/customer/media", headers=headers, data={"alt_text": f"Pool {i}"},
                            files={"file": (f"p{i}.png", make_png(2 + i, 2), "image/png")}).json()
                for i in range(3)]
    assert uploaded[0]["mime_type"] == "image/png" and uploaded[0]["width"] == 2
    preview = client.get(f"/api/v1/customer/media/{uploaded[0]['id']}/file", headers=headers)
    assert preview.headers["content-type"] == "image/png"

    images = [{"asset_id": u["id"], "alt": f"Pool {i}"} for i, u in enumerate(uploaded)]
    saved = client.put("/api/v1/customer/content", headers=headers,
                       json={"section_key": "gallery", "updates": {"images": images}})
    assert saved.status_code == 200, saved.text
    home = (sites_dir / website["subdomain"] / "index.html").read_text(encoding="utf-8")
    assert f"assets/img/{uploaded[0]['id']}.png" in home and 'alt="Pool 0"' in home
    gaps = {g["key"] for g in client.get("/api/v1/customer/dashboard", headers=headers).json()["seo"]["content_gaps"]}
    assert "photos" not in gaps

    # someone else's (or a made-up) asset id is refused
    bogus = client.put("/api/v1/customer/content", headers=headers, json={
        "section_key": "gallery", "updates": {"images": [{"asset_id": "00000000-0000-0000-0000-000000000000",
                                                          "alt": ""}]}})
    assert bogus.status_code == 422

    assert client.delete(f"/api/v1/customer/media/{uploaded[0]['id']}", headers=headers).status_code == 204
    assert f"assets/img/{uploaded[0]['id']}" not in (sites_dir / website["subdomain"] / "index.html").read_text(
        encoding="utf-8")
    assert len(client.get("/api/v1/customer/media", headers=headers).json()) == 2


def test_faq_page_has_faq_schema_and_unique_titles(client, admin_headers, published_site, sites_dir):
    faq_html = (sites_dir / published_site["website"]["subdomain"] / "faq" / "index.html").read_text(encoding="utf-8")
    assert '"@type": "FAQPage"' in faq_html
    assert "<title>FAQ | Santos Plumbing Services</title>" in faq_html
    seo = client.get(f"/api/v1/websites/{published_site['website']['id']}/seo", headers=admin_headers).json()
    assert {"home", "about", "faq"} <= seo["pages"].keys() and seo["audit"]["score"] > 0


def test_analytics_breakdowns(client, admin_headers, published_site):
    series = client.get("/api/v1/analytics/timeseries?days=7", headers=admin_headers).json()
    assert len(series) == 7 and sum(d["generated"] for d in series) == 1 and sum(d["published"] for d in series) == 1
    templates = {t["slug"]: t for t in client.get("/api/v1/analytics/templates", headers=admin_headers).json()}
    assert sum(t["sites"] for t in templates.values()) == 1 and len(templates) == 14
    industries = client.get("/api/v1/analytics/industries", headers=admin_headers).json()
    assert industries[0]["industry"] == "plumbing" and industries[0]["sites"] == 1


def test_customer_cannot_attach_library_free_hero_from_other_business(client, admin_headers, db):
    """Library images (business_id NULL) are usable by anyone; uploads only by their owner."""
    owner_a = _business(client, admin_headers, name="Alpha Dental Clinic", industry="dental",
                        email="a@gmail.com", phone="0917 555 1001")
    owner_b = _business(client, admin_headers, name="Beta Dental Clinic", industry="dental",
                        email="b@gmail.com", phone="0917 555 1002")
    site_a = client.post("/api/v1/websites/generate", json={"business_id": owner_a["id"], "publish": True},
                         headers=admin_headers).json()
    site_b = client.post("/api/v1/websites/generate", json={"business_id": owner_b["id"], "publish": True},
                         headers=admin_headers).json()
    headers_a = _claim(client, site_a["subdomain"], "a@gmail.com")
    headers_b = _claim(client, site_b["subdomain"], "b@gmail.com")
    upload_a = client.post("/api/v1/customer/media", headers=headers_a,
                           files={"file": ("a.png", make_png(), "image/png")}).json()
    stolen = client.put("/api/v1/customer/content", headers=headers_b, json={
        "section_key": "hero", "updates": {"image": {"asset_id": upload_a["id"], "alt": "x"}}})
    assert stolen.status_code == 422
    library = db.query(WebsiteContent).filter_by(section_key="hero").first().content["image"]["asset_id"]
    own = client.put("/api/v1/customer/content", headers=headers_b, json={
        "section_key": "hero", "updates": {"image": {"asset_id": library, "alt": ""}}})
    assert own.status_code == 200
    assert db.query(FactoryJob).count() == 0  # synchronous path does not touch the queue
