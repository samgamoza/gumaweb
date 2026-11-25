"""Live discovery end to end: API -> job queue -> worker -> import pipeline -> provenance (port step 3)."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.domains.business_discovery.contacts import ContactKind, ValueType
from app.domains.business_discovery.enums import DiscoverySource
from app.models import Business, BusinessContact, DiscoveryRun, FactoryJob
from app.services import discovery_service
from app.workers.factory_worker import FactoryWorker

DISCOVER = "/api/v1/businesses/discover"


@pytest.fixture
def worker(session_factory, settings):
    return FactoryWorker(session_factory, settings, worker_id="test")


@pytest.fixture
def overpass(monkeypatch):
    """Route provider HTTP through a mock; set `.response` to control what Overpass answers."""

    class Overpass:
        response = httpx.Response(200, json={"elements": []})
        requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        Overpass.requests.append(request)
        return Overpass.response

    monkeypatch.setattr(discovery_service, "http_client_factory",
                        lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return Overpass


def test_sources_list_shows_what_is_configured(client, admin_headers, readonly_headers, settings, monkeypatch):
    monkeypatch.setattr(settings, "google_maps_api_key", None)
    sources = {s["id"]: s for s in client.get("/api/v1/businesses/discovery-sources", headers=readonly_headers).json()}
    assert sources["osm"]["configured"] is True and sources["osm"]["discovery_source"] == "osm"
    assert sources["google_places"]["configured"] is False and sources["google_places"]["billed"] is True
    assert sources["fixture"]["category"] == "test"  # tests are not production

    monkeypatch.setattr(settings, "google_maps_api_key", "test-key")
    sources = {s["id"]: s for s in client.get("/api/v1/businesses/discovery-sources", headers=admin_headers).json()}
    assert sources["google_places"]["configured"] is True


def test_fixture_discovery_runs_on_the_worker_and_imports_with_provenance(client, admin_headers, worker, db):
    queued = client.post(DISCOVER, json={"source": "fixture", "category": "bakery"}, headers=admin_headers)
    assert queued.status_code == 202, queued.text
    assert queued.json()["kind"] == "discover_businesses" and queued.json()["status"] == "queued"

    duplicate = client.post(DISCOVER, json={"source": "fixture", "category": "Bakery"}, headers=admin_headers)
    assert duplicate.status_code == 409

    assert worker.drain() == 1
    job = db.get(FactoryJob, uuid.UUID(queued.json()["id"]))
    assert job.status == "succeeded" and job.result["status"] == "completed" and job.result["created"] == 2

    businesses = db.scalars(select(Business).where(Business.source == DiscoverySource.FIXTURE)).all()
    assert {b.name for b in businesses} == {"Davao Sunrise Bakery", "Bacolod Sweet Escape"}
    davao = next(b for b in businesses if b.name == "Davao Sunrise Bakery")
    assert davao.source_ref == "fixture:5" and davao.phone == "63825550133" and davao.score is not None

    contacts = client.get(f"/api/v1/businesses/{davao.id}/contacts", headers=admin_headers).json()
    assert [(c["kind"], c["value"], c["source"], c["source_ref"], c["value_type"]) for c in contacts] == [
        ("phone", "63825550133", "fixture", "fixture:5", "observed")]
    assert contacts[0]["discovery_run_id"] == job.result["discovery_run_id"]

    # Running it again is allowed once the first finished, and finds only duplicates.
    client.post(DISCOVER, json={"source": "fixture", "category": "bakery"}, headers=admin_headers)
    worker.drain()
    runs = client.get("/api/v1/businesses/discovery-runs", headers=admin_headers).json()
    second = next(r for r in runs if r["id"] != job.result["discovery_run_id"])  # same-second timestamps tie
    assert (second["source"], second["created_count"], second["duplicate_count"]) == ("fixture", 0, 2)


def test_osm_discovery_imports_real_shaped_results(client, admin_headers, worker, db, overpass):
    overpass.response = httpx.Response(200, json={"elements": [
        {"type": "node", "id": 101, "lat": 15.14, "lon": 120.59,
         "tags": {"name": "Angeles Pipe Masters", "craft": "plumber", "phone": "0917 555 0177"}},
        {"type": "way", "id": 202, "center": {"lat": 15.15, "lon": 120.58},
         "tags": {"name": "Balibago Plumbing", "craft": "plumber", "website": "https://balibago-plumbing.example"}},
        {"type": "node", "id": 303, "tags": {"craft": "plumber"}},  # unnamed: skipped
    ]})
    client.post(DISCOVER, json={"source": "osm", "category": "plumbing", "city": "Angeles City"},
                headers=admin_headers)
    worker.drain()

    sent = overpass.requests[0].content.decode()
    assert "Angeles+City" in sent and "plumber" in sent and overpass.requests[0].headers["user-agent"]
    found = {b.name: b for b in db.scalars(select(Business).where(Business.source == DiscoverySource.OSM))}
    assert set(found) == {"Angeles Pipe Masters", "Balibago Plumbing"}
    pipes = found["Angeles Pipe Masters"]
    assert (pipes.source_ref, pipes.latitude, pipes.longitude, pipes.city) == (
        "osm:node/101", 15.14, 120.59, "Angeles City")
    assert found["Balibago Plumbing"].website == "https://balibago-plumbing.example"
    phone = db.scalar(select(BusinessContact).where(BusinessContact.business_id == pipes.id))
    assert (phone.kind, phone.value_type, phone.confidence) == (ContactKind.PHONE, ValueType.OBSERVED, 0.8)


@pytest.mark.parametrize("status", [429, 504])
def test_source_failure_is_a_failed_run_and_the_job_is_not_retried(client, admin_headers, worker, db, overpass,
                                                                   status):
    overpass.response = httpx.Response(status, text="busy")
    queued = client.post(DISCOVER, json={"source": "osm", "category": "bakery", "city": "Cebu City"},
                         headers=admin_headers).json()
    assert worker.drain() == 1
    job = db.get(FactoryJob, uuid.UUID(queued["id"]))
    assert job.status == "succeeded" and job.attempts == 1 and job.result["status"] == "failed"
    run = db.get(DiscoveryRun, uuid.UUID(job.result["discovery_run_id"]))
    assert run.status == "failed" and run.source == DiscoverySource.OSM
    expected = "DiscoveryQuotaExceeded" if status == 429 else "DiscoveryError"
    assert run.errors[0]["error"].startswith(expected)


def test_invalid_requests_are_rejected_before_queueing(client, admin_headers, operator_headers, readonly_headers,
                                                      settings, monkeypatch, db):
    monkeypatch.setattr(settings, "google_maps_api_key", None)
    cases = [
        ({"source": "google_places", "category": "bakery", "city": "Cebu City"}, 422),  # no key
        ({"source": "yellow_pages", "category": "bakery"}, 422),  # unknown
        ({"source": "osm"}, 422),  # nothing to search for
        ({"source": "osm", "category": "bakery", "limit": 0}, 422),
    ]
    for body, expected in cases:
        assert client.post(DISCOVER, json=body, headers=admin_headers).status_code == expected, body
    body = {"source": "fixture", "city": "Cebu"}
    assert client.post(DISCOVER, json=body, headers=readonly_headers).status_code == 403
    assert client.post(DISCOVER, json=body, headers=operator_headers).status_code == 202
    assert db.scalar(select(FactoryJob).where(FactoryJob.kind == "discover_businesses")) is not None


def test_fixture_source_can_be_disabled(client, admin_headers, settings, monkeypatch):
    monkeypatch.setattr(settings, "discovery_allow_fixture", False)
    assert client.post(DISCOVER, json={"source": "fixture", "city": "Cebu"}, headers=admin_headers).status_code == 422
    ids = {s["id"] for s in client.get("/api/v1/businesses/discovery-sources", headers=admin_headers).json()}
    assert "fixture" not in ids


def test_fixture_is_off_in_production_by_default(settings, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "discovery_allow_fixture", None)
    assert discovery_service.discovery_config(settings).allow_fixture is False


def test_contacts_endpoint_404s_for_unknown_business(client, admin_headers):
    missing = client.get("/api/v1/businesses/00000000-0000-4000-8000-000000000000/contacts", headers=admin_headers)
    assert missing.status_code == 404
