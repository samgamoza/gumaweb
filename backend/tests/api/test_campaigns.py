"""Discovery campaigns end to end (port step 5). Ports guma_os crawl-runner / crawl-campaigns cases."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.domains.business_discovery.enums import DiscoverySource
from app.models import AuditLog, Business, DiscoveryRun, FactoryJob
from app.services import campaign_service, discovery_service
from app.workers.factory_worker import FactoryWorker

CAMPAIGNS = "/api/v1/discovery/campaigns"


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    """Record pauses instead of sleeping."""
    slept: list[float] = []
    monkeypatch.setattr(campaign_service, "sleep", slept.append)
    return slept


@pytest.fixture
def worker(session_factory, settings):
    return FactoryWorker(session_factory, settings, worker_id="test")


@pytest.fixture
def overpass(monkeypatch):
    """Mock Overpass: `responses` is consumed in order; the default is an empty result."""

    class Overpass:
        responses: list[httpx.Response] = []
        calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        Overpass.calls += 1
        return Overpass.responses.pop(0) if Overpass.responses else httpx.Response(200, json={"elements": []})

    monkeypatch.setattr(discovery_service, "http_client_factory",
                        lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return Overpass


def osm_elements(*names: str) -> httpx.Response:
    return httpx.Response(200, json={"elements": [
        {"type": "node", "id": 1000 + i, "lat": 10.3, "lon": 123.9, "tags": {"name": n}} for i, n in enumerate(names)]})


def create(client, headers, **overrides) -> dict:
    body = {"name": "Bakeries VisMin", "cities": ["Davao City", "Bacolod"], "categories": ["bakery"],
            "sources": ["fixture"], "target": 100, **overrides}
    response = client.post(CAMPAIGNS, json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def start(client, headers, campaign_id: str) -> dict:
    response = client.post(f"{CAMPAIGNS}/{campaign_id}/run", headers=headers)
    assert response.status_code == 202, response.text
    return response.json()


def get_run(client, headers, run_id: str) -> dict:
    return client.get(f"/api/v1/discovery/runs/{run_id}", headers=headers).json()


# --- CRUD and validation --------------------------------------------------------------------------


def test_create_list_get_update_delete(client, admin_headers, db):
    campaign = create(client, admin_headers, cities=[" Davao City ", "davao city", "Bacolod"], categories=["bakery"])
    assert campaign["cities"] == ["Davao City", "Bacolod"]  # trimmed and deduped
    assert campaign["last_run"] is None and campaign["enrichment_tiers"] is None

    assert [c["id"] for c in client.get(CAMPAIGNS, headers=admin_headers).json()] == [campaign["id"]]
    updated = client.put(f"{CAMPAIGNS}/{campaign['id']}", headers=admin_headers,
                         json={**campaign, "name": "Bakeries v2", "target": 5, "enrichment_tiers": []}).json()
    assert (updated["name"], updated["target"], updated["enrichment_tiers"]) == ("Bakeries v2", 5, [])

    assert client.delete(f"{CAMPAIGNS}/{campaign['id']}", headers=admin_headers).status_code == 204
    assert client.get(f"{CAMPAIGNS}/{campaign['id']}", headers=admin_headers).status_code == 404
    actions = sorted(db.scalars(select(AuditLog.action).where(AuditLog.entity_type == "discovery_campaign")))
    assert actions == ["discovery.campaign_created", "discovery.campaign_deleted", "discovery.campaign_updated"]


@pytest.mark.parametrize(("override", "reason"), [
    ({"name": "  "}, "blank name"),
    ({"cities": []}, "no cities"),
    ({"cities": ["  "]}, "blank cities only"),
    ({"categories": []}, "no categories"),
    ({"target": 0}, "target below 1"),
    ({"sources": ["yellow_pages"]}, "unknown source"),
    ({"sources": ["google_places"]}, "unconfigured source"),
    ({"enrichment_tiers": ["hunter"]}, "disabled tier"),
])
def test_invalid_campaigns_are_rejected(client, admin_headers, settings, monkeypatch, override, reason):
    monkeypatch.setattr(settings, "google_maps_api_key", None)
    body = {"name": "x", "cities": ["Cebu City"], "categories": ["bakery"], "sources": ["osm"], **override}
    assert client.post(CAMPAIGNS, json=body, headers=admin_headers).status_code == 422, reason


def test_roles(client, admin_headers, operator_headers, readonly_headers):
    body = {"name": "x", "cities": ["Cebu City"], "categories": ["bakery"], "sources": ["fixture"]}
    assert client.post(CAMPAIGNS, json=body, headers=readonly_headers).status_code == 403
    campaign = client.post(CAMPAIGNS, json=body, headers=operator_headers).json()
    assert client.get(CAMPAIGNS, headers=readonly_headers).status_code == 200
    assert client.delete(f"{CAMPAIGNS}/{campaign['id']}", headers=operator_headers).status_code == 403
    assert client.post(f"{CAMPAIGNS}/{campaign['id']}/run", headers=readonly_headers).status_code == 403


# --- running --------------------------------------------------------------------------------------


def test_sweep_imports_tracks_progress_and_keeps_history(client, admin_headers, worker, db, no_delay, settings):
    campaign = create(client, admin_headers)
    run = start(client, admin_headers, campaign["id"])
    assert run["status"] == "queued" and run["campaign_id"] == campaign["id"]
    assert run["progress"]["queries_planned"] == 2 and run["progress"]["queries_done"] == 0

    worker.drain()
    run = get_run(client, admin_headers, run["id"])
    assert run["status"] == "completed" and run["finished_at"]
    assert (run["progress"]["queries_done"], run["progress"]["found"], run["progress"]["prospects"]) == (2, 2, 2)
    assert "current" not in run["progress"] and run["created_count"] == 2
    names = set(db.scalars(select(Business.name).where(Business.discovery_run_id == uuid.UUID(run["id"]))))
    assert names == {"Davao Sunrise Bakery", "Bacolod Sweet Escape"}
    assert no_delay == [settings.discovery_query_delay_seconds]  # between the two queries, not after the last

    listed = client.get(CAMPAIGNS, headers=admin_headers).json()[0]
    assert listed["last_run"]["id"] == run["id"]
    history = client.get(f"{CAMPAIGNS}/{campaign['id']}/runs", headers=admin_headers).json()
    assert [r["id"] for r in history] == [run["id"]]


def test_only_one_sweep_at_a_time(client, admin_headers, worker):
    first = create(client, admin_headers, name="first")
    second = create(client, admin_headers, name="second")
    start(client, admin_headers, first["id"])
    blocked = client.post(f"{CAMPAIGNS}/{second['id']}/run", headers=admin_headers)
    assert blocked.status_code == 409 and blocked.json()["error"] == "campaign_in_progress"
    worker.drain()
    start(client, admin_headers, second["id"])  # free again once the first finished


def test_stops_at_the_target(client, admin_headers, worker):
    campaign = create(client, admin_headers, cities=["Quezon City"], categories=["a", "e"], target=1)
    run = start(client, admin_headers, campaign["id"])
    worker.drain()
    run = get_run(client, admin_headers, run["id"])
    assert run["progress"]["queries_done"] == 1 and run["progress"]["queries_planned"] == 2
    assert run["created_count"] == 1


def test_a_failing_query_is_a_warning_not_the_end(client, admin_headers, worker, overpass):
    overpass.responses = [httpx.Response(429), osm_elements("Cebu Bread House")]
    campaign = create(client, admin_headers, cities=["Cebu City"], categories=["bakery", "cafe"], sources=["osm"])
    run = start(client, admin_headers, campaign["id"])
    worker.drain()
    run = get_run(client, admin_headers, run["id"])
    assert run["status"] == "completed" and run["created_count"] == 1
    assert len(run["progress"]["warnings"]) == 1 and "Cebu City / bakery / osm" in run["progress"]["warnings"][0]


def test_every_query_failing_is_a_failed_run(client, admin_headers, worker, overpass):
    overpass.responses = [httpx.Response(504), httpx.Response(504)]
    campaign = create(client, admin_headers, cities=["Cebu City"], categories=["bakery", "cafe"], sources=["osm"])
    run = start(client, admin_headers, campaign["id"])
    worker.drain()
    run = get_run(client, admin_headers, run["id"])
    assert run["status"] == "failed" and len(run["progress"]["warnings"]) == 2


def test_multi_source_sweeps_dedupe_and_keep_each_source_label(client, admin_headers, worker, db, overpass):
    overpass.responses = [osm_elements("Davao Sunrise Bakery", "Osm Only Bakery")]
    campaign = create(client, admin_headers, cities=["Davao City"], categories=["bakery"], sources=["fixture", "osm"])
    run = start(client, admin_headers, campaign["id"])
    worker.drain()
    run = get_run(client, admin_headers, run["id"])
    assert run["progress"]["sources"] == ["fixture", "osm"] and run["source"] == "fixture"
    rows = set(db.execute(select(Business.name, Business.source)
                          .where(Business.discovery_run_id == uuid.UUID(run["id"]))).all())
    # Each business keeps the label of the source that found it. Known gap (pre-existing import rule): the
    # dedupe key is name+city+phone, so the OSM copy of the fixture bakery (no phone) is a second record.
    assert rows == {("Davao Sunrise Bakery", DiscoverySource.FIXTURE), ("Davao Sunrise Bakery", DiscoverySource.OSM),
                    ("Osm Only Bakery", DiscoverySource.OSM)}


def test_cancel_a_queued_run(client, admin_headers, worker, db):
    campaign = create(client, admin_headers)
    run = start(client, admin_headers, campaign["id"])
    cancelled = client.post(f"/api/v1/discovery/runs/{run['id']}/cancel", headers=admin_headers).json()
    assert cancelled["cancel_requested"] is True
    worker.drain()
    run = get_run(client, admin_headers, run["id"])
    assert run["status"] == "cancelled" and run["progress"]["queries_done"] == 0 and run["created_count"] == 0
    assert client.post(f"/api/v1/discovery/runs/{run['id']}/cancel", headers=admin_headers).status_code == 409


def test_cancel_mid_sweep_keeps_what_was_found(client, admin_headers, worker, session_factory, monkeypatch):
    campaign = create(client, admin_headers, cities=["Davao City", "Bacolod", "Baguio"])
    run = start(client, admin_headers, campaign["id"])

    def operator_cancels(_seconds: float) -> None:  # runs between the first and second query
        with session_factory() as other:
            other.get(DiscoveryRun, uuid.UUID(run["id"])).cancel_requested = True
            other.commit()

    monkeypatch.setattr(campaign_service, "sleep", operator_cancels)
    worker.drain()
    run = get_run(client, admin_headers, run["id"])
    assert run["status"] == "cancelled" and run["progress"]["queries_done"] == 1
    assert run["created_count"] == 1  # Davao's bakery, found before the cancel, is still imported


def test_deleting_a_campaign_is_blocked_while_it_runs_and_keeps_history(client, admin_headers, worker, db):
    campaign = create(client, admin_headers)
    run = start(client, admin_headers, campaign["id"])
    assert client.delete(f"{CAMPAIGNS}/{campaign['id']}", headers=admin_headers).status_code == 409
    worker.drain()
    assert client.delete(f"{CAMPAIGNS}/{campaign['id']}", headers=admin_headers).status_code == 204
    kept = get_run(client, admin_headers, run["id"])
    assert kept["status"] == "completed" and kept["campaign_id"] is None


def test_enrichment_follows_the_campaign_setting(client, admin_headers, worker, db):
    with_enrichment = create(client, admin_headers, name="salons", cities=["Taguig"], categories=["salon"])
    start(client, admin_headers, with_enrichment["id"])
    worker.drain()
    assert db.scalars(select(FactoryJob.kind).where(FactoryJob.kind == "enrich_business")).all() == ["enrich_business"]

    no_enrichment = create(client, admin_headers, name="gyms", cities=["Iloilo City"], categories=["gym"],
                           enrichment_tiers=[])
    start(client, admin_headers, no_enrichment["id"])
    worker.drain()
    assert len(db.scalars(select(FactoryJob).where(FactoryJob.kind == "enrich_business")).all()) == 1


def test_run_endpoints_404(client, admin_headers):
    missing = "00000000-0000-4000-8000-000000000000"
    assert client.get(f"/api/v1/discovery/runs/{missing}", headers=admin_headers).status_code == 404
    assert client.post(f"/api/v1/discovery/runs/{missing}/cancel", headers=admin_headers).status_code == 404
    assert client.post(f"{CAMPAIGNS}/{missing}/run", headers=admin_headers).status_code == 404
