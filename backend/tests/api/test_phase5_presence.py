"""Phase 5 (Digital Presence Factory): presence kit API, plan tiers, lazy image rendering, downloads."""

import io
import re
import zipfile

from PIL import Image

from app.models import FactoryJob, PresenceKit
from app.services.providers import providers
from app.workers.factory_worker import FactoryWorker


def _owner(client, published_site, plan=None):
    sub = published_site["website"]["subdomain"]
    client.post("/api/v1/claims", json={"subdomain": sub, "claimant_name": "Jose",
                                        "claimant_email": "santos.plumbing@gmail.com"})
    token = re.search(r"token=([\w-]+)", providers.email.outbox[-1].text).group(1)
    tokens = client.post("/api/v1/claims/verify", json={"token": token, "password": "OwnerPass!2026"}).json()
    headers = {"Authorization": f"Bearer {tokens['tokens']['access_token']}"}
    if plan:
        assert client.post("/api/v1/customer/subscription", headers=headers, json={"plan": plan}).status_code == 200
    return headers


def test_publishing_queues_the_presence_kit(published_site, db, session_factory, settings):
    jobs = db.query(FactoryJob).filter_by(kind="generate_presence").all()
    assert len(jobs) == 1 and jobs[0].payload["business_id"]
    FactoryWorker(session_factory, settings, worker_id="t").drain()
    kit = db.query(PresenceKit).one()
    assert kit.version == 1 and kit.social["bios"] and kit.google["description"]
    assert kit.rendered == {}  # images are rendered lazily, not for every unclaimed site


def test_free_plan_gets_the_basic_kit(client, published_site):
    headers = _owner(client, published_site)
    kit = client.get("/api/v1/customer/presence", headers=headers).json()
    assert kit["tiers"] == {"basic": True, "full": False}
    assert kit["google"] is None and kit["seo"] is None and kit["social"]["posts"] == []  # withheld, not hidden
    locked = {a["name"]: a["locked"] for a in kit["assets"]}
    assert locked["profile"] is False and locked["facebook-cover"] is False and locked["story"] is True

    profile = client.get("/api/v1/customer/presence/assets/profile.png", headers=headers)
    assert profile.status_code == 200 and profile.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(profile.content)).size == (1080, 1080)
    story = client.get("/api/v1/customer/presence/assets/story.png", headers=headers)
    assert story.status_code == 403 and story.json()["error"] == "plan_upgrade_required"
    assert client.get("/api/v1/customer/presence/download.zip", headers=headers).status_code == 403
    assert client.get("/api/v1/customer/presence/assets/../../etc.png", headers=headers).status_code == 404
    assert client.get("/api/v1/customer/presence/assets/nonsense.png", headers=headers).status_code == 404


def test_professional_kit_zip_and_checklist(client, published_site, db):
    headers = _owner(client, published_site, plan="professional")
    kit = client.get("/api/v1/customer/presence", headers=headers).json()
    assert kit["google"]["primary_category"] == "Plumber" and kit["seo"]["nap"]["name"]
    post = kit["social"]["posts"][0]
    image = client.get(f"/api/v1/customer/presence/assets/post-{post['key']}.png", headers=headers)
    assert image.status_code == 200

    stored = db.query(PresenceKit).one()
    db.refresh(stored)
    assert f"post-{post['key']}" in stored.rendered  # cached for this kit version

    archive = zipfile.ZipFile(io.BytesIO(client.get("/api/v1/customer/presence/download.zip", headers=headers).content))
    names = set(archive.namelist())
    assert {"images/logo.png", "images/facebook-cover.png", "social/bios.txt", "social/posts.txt",
            "google-business/listing.txt", "seo/profile.json", "README.txt"} <= names
    assert "Primary category: Plumber" in archive.read("google-business/listing.txt").decode()

    done = client.put("/api/v1/customer/presence/checklist", headers=headers, json={"step": "verify", "done": True})
    assert "verify" in done.json()["checklist"]
    bad = client.put("/api/v1/customer/presence/checklist", headers=headers, json={"step": "hack", "done": True})
    assert bad.status_code == 422


def test_kit_follows_website_changes(client, published_site, db):
    headers = _owner(client, published_site, plan="professional")
    first = client.get("/api/v1/customer/presence", headers=headers).json()
    client.get("/api/v1/customer/presence/assets/facebook-cover.png", headers=headers)
    client.put("/api/v1/customer/presence/checklist", headers=headers, json={"step": "claim", "done": True})
    client.put("/api/v1/customer/content", headers=headers, json={
        "section_key": "services", "updates": {"items": [
            {"name": "Septic Tank Cleaning", "description": "Safe septic cleaning."},
            {"name": "Leak Repairs", "description": "Fast leak repairs."}]}})
    client.post("/api/v1/customer/presence/regenerate", headers=headers)
    second = client.get("/api/v1/customer/presence", headers=headers).json()
    assert second["version"] > first["version"]
    assert any("Septic Tank Cleaning" in p["caption"] for p in second["social"]["posts"])
    assert "claim" in second["checklist"]  # progress survives regeneration
    kit = db.query(PresenceKit).one()
    db.refresh(kit)
    assert kit.rendered == {}  # stale images were dropped with the old version
