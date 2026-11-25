"""Contact enrichment end to end: API -> job -> worker -> tiers -> provenance -> rescore (port step 4)."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.net import SafeFetchResult
from app.domains.business_discovery.contacts import PolicyDecision, ValueType, VerificationStatus
from app.domains.outreach.suppression import SuppressionKind, SuppressionReason
from app.models import Business, BusinessContact, FactoryJob, ProviderUsage
from app.services import enrichment_service
from app.services.providers import providers
from app.services.support import SYSTEM
from app.services.suppression_service import SuppressionService
from app.workers.factory_worker import FactoryWorker

TIERS = "/api/v1/businesses/enrichment-tiers"


@pytest.fixture
def worker(session_factory, settings):
    return FactoryWorker(session_factory, settings, worker_id="test")


@pytest.fixture
def site(monkeypatch):
    """A fake web: set `pages[url] = html`; every fetched URL is recorded in `fetched`."""

    class Site:
        pages: dict[str, str] = {}
        fetched: list[str] = []

    def fetch(url: str) -> SafeFetchResult:
        Site.fetched.append(url)
        html = Site.pages.get(url.rstrip("/"))
        status = 200 if html is not None else 404
        return SafeFetchResult(ok=status == 200, status=status,
                               headers=httpx.Headers({"content-type": "text/html"}), text=html or "", url=url)

    monkeypatch.setattr(enrichment_service, "website_fetcher", fetch)
    return Site


@pytest.fixture
def api(monkeypatch):
    """Mock for RDAP / Hunter traffic: set `routes[host] = response`."""

    class Api:
        routes: dict[str, httpx.Response] = {}
        requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        Api.requests.append(request)
        return Api.routes.get(request.url.host, httpx.Response(404))

    monkeypatch.setattr(enrichment_service, "http_client_factory",
                        lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return Api


def make_business(client, headers, **fields) -> dict:
    body = {"name": f"Shop {uuid.uuid4().hex[:6]}", "city": "Cebu City", **fields}
    response = client.post("/api/v1/businesses", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def enrich(client, headers, business_id: str, worker, **body) -> dict:
    queued = client.post(f"/api/v1/businesses/{business_id}/enrich", json=body or None, headers=headers)
    assert queued.status_code == 202, queued.text
    worker.drain()
    return queued.json()


def job_result(db, job: dict) -> dict:
    return db.get(FactoryJob, uuid.UUID(job["id"])).result


def contacts(db, business_id: str) -> dict[str, BusinessContact]:
    rows = db.scalars(select(BusinessContact).where(BusinessContact.business_id == uuid.UUID(business_id)))
    return {c.value: c for c in rows}


# --- tiers ----------------------------------------------------------------------------------------


def test_tiers_reflect_flags_and_keys(client, readonly_headers, settings, monkeypatch):
    tiers = {t["id"]: t for t in client.get(TIERS, headers=readonly_headers).json()}
    assert tiers["website_scrape"]["enabled"] and not tiers["rdap"]["enabled"] and not tiers["hunter"]["enabled"]
    assert "needs HUNTER_API_KEY" in tiers["hunter"]["note"] and tiers["hunter"]["billed"]

    monkeypatch.setattr(settings, "hunter_api_key", "k")
    tiers = {t["id"]: t for t in client.get(TIERS, headers=readonly_headers).json()}
    assert not tiers["hunter"]["enabled"] and "ENRICH_ALLOW_HUNTER is not true" in tiers["hunter"]["note"]

    monkeypatch.setattr(settings, "enrich_allow_hunter", True)
    monkeypatch.setattr(settings, "enrich_allow_rdap", True)
    tiers = {t["id"]: t for t in client.get(TIERS, headers=readonly_headers).json()}
    assert tiers["hunter"]["enabled"] and tiers["rdap"]["enabled"]


def test_enqueue_validation(client, admin_headers, readonly_headers):
    business = make_business(client, admin_headers, website="https://shop.ph")
    url = f"/api/v1/businesses/{business['id']}/enrich"
    assert client.post(url, json={"tiers": ["hunter"]}, headers=admin_headers).status_code == 422  # disabled
    assert client.post(url, json={"tiers": ["telepathy"]}, headers=admin_headers).status_code == 422
    assert client.post(url, headers=readonly_headers).status_code == 403
    assert client.post(url, headers=admin_headers).status_code == 202
    assert client.post(url, headers=admin_headers).status_code == 409  # already queued
    missing = "/api/v1/businesses/00000000-0000-4000-8000-000000000000/enrich"
    assert client.post(missing, headers=admin_headers).status_code == 404


# --- website scrape -------------------------------------------------------------------------------


def test_scrape_records_provenance_promotes_and_rescores(client, admin_headers, worker, db, site):
    business = make_business(client, admin_headers, website="https://shop.ph")
    site.pages["https://shop.ph"] = '<link href="/wp-content/x.css"><a href="tel:+63 32 555 0101">call</a>'
    site.pages["https://shop.ph/contact"] = 'Write to <a href="mailto:Orders@Shop.ph">us</a>'
    providers.dns.set("MX", "shop.ph", [(10, "mx.shop.ph")])

    job = enrich(client, admin_headers, business["id"], worker)
    result = job_result(db, job)
    assert result["tiers_run"] == ["website_scrape"]
    assert result["promoted"] == {"email": "orders@shop.ph", "phone": "63325550101"}  # it had neither
    assert result["tech_stack"] == ["wordpress"] and result["undeliverable"] == 0

    email = contacts(db, business["id"])["orders@shop.ph"]
    assert (email.source, email.source_ref, email.value_type, email.verification_status) == (
        "website_scrape", "https://shop.ph/contact", ValueType.OBSERVED, VerificationStatus.UNVERIFIED)
    refreshed = db.get(Business, uuid.UUID(business["id"]))
    db.refresh(refreshed)
    assert refreshed.email == "orders@shop.ph"
    assert "email_available" in refreshed.score_breakdown["breakdown"]
    assert refreshed.score > business["score"]


def test_email_on_a_domain_that_cannot_receive_mail_is_invalid_and_not_promoted(client, admin_headers, worker, db,
                                                                               site):
    business = make_business(client, admin_headers, website="https://shop.ph")
    site.pages["https://shop.ph"] = "hello@dead-domain.ph and team@alive.ph"
    providers.dns.set("A", "alive.ph", ["203.0.113.5"])  # no MX, but an A record still receives mail

    result = job_result(db, enrich(client, admin_headers, business["id"], worker))
    found = contacts(db, business["id"])
    assert found["hello@dead-domain.ph"].verification_status == VerificationStatus.INVALID
    assert found["team@alive.ph"].verification_status == VerificationStatus.UNVERIFIED
    assert result["undeliverable"] == 1 and result["promoted"] == {"email": "team@alive.ph"}


def test_dns_trouble_leaves_contacts_unverified(client, admin_headers, worker, db, site):
    business = make_business(client, admin_headers, website="https://shop.ph")
    site.pages["https://shop.ph"] = "hi@shop.ph"
    providers.dns.fail = True
    result = job_result(db, enrich(client, admin_headers, business["id"], worker))
    assert result["undeliverable"] == 0 and result["promoted"] == {"email": "hi@shop.ph"}


def test_facebook_pages_are_never_scraped(client, admin_headers, worker, db, site, api):
    business = make_business(client, admin_headers, website="https://www.facebook.com/someshop")
    result = job_result(db, enrich(client, admin_headers, business["id"], worker))
    assert site.fetched == [] and api.requests == [] and result["emails_found"] == 0


# --- compliance gates -----------------------------------------------------------------------------


def test_suppressed_domain_is_skipped_before_any_tier_runs(client, admin_headers, worker, db, site, api, settings,
                                                          monkeypatch):
    monkeypatch.setattr(settings, "hunter_api_key", "k")
    monkeypatch.setattr(settings, "enrich_allow_hunter", True)
    monkeypatch.setattr(settings, "enrich_paid_min_score", 0)
    business = make_business(client, admin_headers, website="https://www.blocked.ph")
    SuppressionService(db).add(SuppressionKind.DOMAIN, "blocked.ph", SuppressionReason.LEGAL, SYSTEM)

    result = job_result(db, enrich(client, admin_headers, business["id"], worker))
    assert result["skipped"] == "domain_suppressed"
    assert site.fetched == [] and api.requests == []  # no free fetch, no paid lookup
    assert db.scalars(select(ProviderUsage)).all() == []


def test_suppressed_email_found_on_a_site_is_blocked(client, admin_headers, worker, db, site):
    SuppressionService(db).add(SuppressionKind.EMAIL, "owner@shop.ph", SuppressionReason.REQUESTED, SYSTEM)
    business = make_business(client, admin_headers, website="https://shop.ph")
    site.pages["https://shop.ph"] = "owner@shop.ph"
    result = job_result(db, enrich(client, admin_headers, business["id"], worker))
    contact = contacts(db, business["id"])["owner@shop.ph"]
    assert (contact.policy_decision, contact.reason_code) == (PolicyDecision.BLOCKED, "SUPPRESSED_EMAIL")
    assert result["blocked"] == 1 and result["promoted"] == {}


# --- opt-in tiers ---------------------------------------------------------------------------------


def test_rdap_guesses_are_stored_as_predicted_and_never_promoted(client, admin_headers, worker, db, site, api,
                                                                settings, monkeypatch):
    monkeypatch.setattr(settings, "enrich_allow_rdap", True)
    monkeypatch.setattr(settings, "rdap_base_url", "https://rdap.test/domain")
    api.routes["rdap.test"] = httpx.Response(200, json={"entities": [
        {"vcardArray": ["vcard", [["email", {}, "text", "domains@proxy.example"]]]}]})
    business = make_business(client, admin_headers, website="https://shop.ph")

    result = job_result(db, enrich(client, admin_headers, business["id"], worker))
    guess = contacts(db, business["id"])["domains@proxy.example"]
    assert result["tiers_run"] == ["website_scrape", "rdap"] and result["guesses_found"] == 1
    assert (guess.value_type, guess.confidence) == (ValueType.PREDICTED, 0.2)
    assert result["promoted"] == {} and db.get(Business, uuid.UUID(business["id"])).email is None


@pytest.fixture
def hunter_on(settings, monkeypatch, api):
    monkeypatch.setattr(settings, "hunter_api_key", "hunter-key")
    monkeypatch.setattr(settings, "enrich_allow_hunter", True)
    monkeypatch.setattr(settings, "hunter_cost_micros", 49000)
    api.routes["api.hunter.io"] = httpx.Response(200, json={"data": {"emails": [
        {"value": "owner@nosite-bakery.ph", "confidence": 88}]}})
    return api


def test_hunter_runs_for_high_scorers_and_every_call_is_ledgered(client, admin_headers, worker, db, settings,
                                                                monkeypatch, hunter_on):
    business = make_business(client, admin_headers, name="Nosite Bakery", phone="0917 555 0109",
                             facebook="facebook.com/nosite")
    monkeypatch.setattr(settings, "enrich_paid_min_score", business["score"])

    result = job_result(db, enrich(client, admin_headers, business["id"], worker))
    assert result["tiers_run"] == ["hunter"] and result["billed_calls"] == {"hunter": 1}
    assert hunter_on.requests[0].url.params["company"] == "Nosite Bakery"
    usage = db.scalars(select(ProviderUsage)).one()
    assert (usage.provider, usage.units, usage.cost_micros, str(usage.business_id)) == (
        "hunter", 1, 49000, business["id"])
    contact = contacts(db, business["id"])["owner@nosite-bakery.ph"]
    assert (contact.source, contact.confidence, contact.value_type) == ("hunter", 0.88, ValueType.OBSERVED)


def test_hunter_is_skipped_for_low_scorers_and_businesses_that_have_an_email(client, admin_headers, worker, db,
                                                                            settings, monkeypatch, hunter_on):
    monkeypatch.setattr(settings, "enrich_paid_min_score", 101)
    low = make_business(client, admin_headers, name="Low Score Co")
    assert job_result(db, enrich(client, admin_headers, low["id"], worker))["tiers_run"] == []

    monkeypatch.setattr(settings, "enrich_paid_min_score", 0)
    has_email = make_business(client, admin_headers, name="Has Email Co", email="hi@hasemail.ph")
    assert job_result(db, enrich(client, admin_headers, has_email["id"], worker))["tiers_run"] == []
    assert hunter_on.requests == [] and db.scalars(select(ProviderUsage)).all() == []


# --- discovery hand-off ---------------------------------------------------------------------------


def test_discovery_queues_enrichment_for_businesses_with_a_website(client, admin_headers, worker, db, settings,
                                                                   monkeypatch):
    client.post("/api/v1/businesses/discover", json={"source": "fixture", "category": "salon"}, headers=admin_headers)
    worker.drain()  # discovery job, then the enrichment job it queued
    kinds = sorted(db.scalars(select(FactoryJob.kind)).all())
    assert kinds == ["discover_businesses", "enrich_business"]  # Bloom and Co. has a site

    monkeypatch.setattr(settings, "enrich_after_discovery", False)
    client.post("/api/v1/businesses/discover", json={"source": "fixture", "category": "gym"}, headers=admin_headers)
    worker.drain()
    assert sorted(db.scalars(select(FactoryJob.kind)).all()).count("enrich_business") == 1


def test_discovery_does_not_queue_enrichment_without_a_website(client, admin_headers, worker, db):
    client.post("/api/v1/businesses/discover", json={"source": "fixture", "category": "bakery"}, headers=admin_headers)
    worker.drain()
    assert db.scalars(select(FactoryJob.kind)).all() == ["discover_businesses"]
