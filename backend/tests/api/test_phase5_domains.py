"""Phase 5 custom domains: verification, serving the website at the owner's domain, revocation."""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.exceptions import ConflictError, ValidationFailedError
from app.domains.presence.domains import is_verified, normalize_domain
from app.models import Business, CustomDomain, Mailbox, MailDomain, Website
from app.services import domain_service
from app.services.domain_service import DomainService
from app.services.providers import providers
from app.services.support import SYSTEM
from tests.fakes import FakeMailProvider


def _owner(client, published_site, plan="professional"):
    sub = published_site["website"]["subdomain"]
    client.post("/api/v1/claims", json={"subdomain": sub, "claimant_name": "Jose",
                                        "claimant_email": "santos.plumbing@gmail.com"})
    token = re.search(r"token=([\w-]+)", providers.email.outbox[-1].text).group(1)
    tokens = client.post("/api/v1/claims/verify", json={"token": token, "password": "OwnerPass!2026"}).json()
    headers = {"Authorization": f"Bearer {tokens['tokens']['access_token']}"}
    if plan:
        assert client.post("/api/v1/customer/subscription", headers=headers, json={"plan": plan}).status_code == 200
    return headers


def _txt(domain: dict) -> dict:
    return next(r for r in domain["records"] if r["type"] == "TXT" and r["name"].startswith("_gumaweb."))


@pytest.mark.parametrize("raw,expected", [
    ("SantosPlumbing.PH", "santosplumbing.ph"),
    ("https://www.santosplumbing.ph/about?x=1", "santosplumbing.ph"),
    ("santosplumbing.ph.", "santosplumbing.ph"),
    ("tubero-ñino.ph", "xn--tubero-ino-z9a.ph"),
])
def test_domains_are_normalized(raw, expected):
    assert normalize_domain(raw, platform_domain="gumaweb.io") == expected


@pytest.mark.parametrize("raw", ["localhost", "10.0.0.1", "shop.local", "x.gumaweb.io", "gumaweb.io",
                                 "user@host.ph", "host.ph:8080", "-bad.ph", "nodot", "a..b.ph", "x" * 64 + ".ph"])
def test_unservable_domains_are_rejected(raw):
    with pytest.raises(ValidationFailedError):
        normalize_domain(raw, platform_domain="gumaweb.io")


def test_verification_record_matching():
    assert is_verified(['"gumaweb-verify=abc"', "other"], "abc")
    assert not is_verified(["gumaweb-verify=abcd"], "abc")


def test_connect_verify_and_serve_website(client, published_site, settings, db):
    headers = _owner(client, published_site)
    created = client.post("/api/v1/customer/domains", headers=headers, json={"domain": "www.SantosPlumbing.ph"})
    assert created.status_code == 201
    domain = created.json()
    assert domain["domain"] == "santosplumbing.ph" and domain["status"] == "pending"
    assert {r["type"] for r in domain["records"]} >= {"TXT", "CNAME"}

    base = f"/api/v1/customer/domains/{domain['id']}"
    early = client.put(f"{base}/website", headers=headers, json={"serve_website": True})
    assert early.status_code == 422  # must verify first
    pending = client.post(f"/api/v1/customer/domains/{domain['id']}/verify", headers=headers).json()
    assert pending["status"] == "pending" and "No TXT record" in pending["last_error"]

    record = _txt(domain)
    providers.dns.set("TXT", record["name"], [record["value"]])
    assert client.post(f"{base}/verify", headers=headers).json()["status"] == "verified"
    assert client.get("/api/v1/public/domains/tls-check", params={"domain": "santosplumbing.ph"}).status_code == 404

    served = client.put(f"{base}/website", headers=headers, json={"serve_website": True})
    assert served.status_code == 200 and served.json()["serve_website"] is True
    website = db.query(Website).one()
    db.refresh(website)
    assert website.url == "https://santosplumbing.ph/"
    live = settings.generated_sites_dir / "_d" / "santosplumbing.ph" / "index.html"
    assert live.exists() and 'href="https://santosplumbing.ph/"' in live.read_text(encoding="utf-8")  # canonical
    for host in ("santosplumbing.ph", "www.santosplumbing.ph", "SantosPlumbing.PH."):
        assert client.get("/api/v1/public/domains/tls-check", params={"domain": host}).status_code == 200
    assert client.get("/api/v1/public/domains/tls-check", params={"domain": "evil.ph"}).status_code == 404

    off = client.put(f"/api/v1/customer/domains/{domain['id']}/website", headers=headers, json={"serve_website": False})
    assert off.json()["serve_website"] is False and not live.exists()
    db.refresh(website)
    assert website.url == settings.site_url(website.subdomain)


def test_domains_need_professional_and_cannot_be_squatted(client, published_site, db, monkeypatch, settings):
    headers = _owner(client, published_site, plan=None)
    blocked = client.post("/api/v1/customer/domains", headers=headers, json={"domain": "santosplumbing.ph"})
    assert blocked.status_code == 403 and blocked.json()["error"] == "plan_upgrade_required"

    client.post("/api/v1/customer/subscription", headers=headers, json={"plan": "professional"})
    first = client.post("/api/v1/customer/domains", headers=headers, json={"domain": "santosplumbing.ph"}).json()

    rival = Business(name="Rival Plumbing", slug="rival-plumbing", dedupe_key="rival-plumbing")
    db.add(rival)
    db.commit()
    monkeypatch.setattr(domain_service, "require_feature", lambda *a, **k: None)  # rival's plan isn't under test
    service = DomainService(db, settings)
    with pytest.raises(ConflictError):
        service.add(rival.id, "santosplumbing.ph")
    # an abandoned, never-verified claim is released after the grace period
    row = db.get(CustomDomain, uuid.UUID(first["id"]))
    row.created_at = datetime.now(UTC) - timedelta(days=30)
    db.commit()
    assert service.add(rival.id, "santosplumbing.ph").business_id == rival.id


def test_revoked_or_downgraded_domains_stop_serving(client, published_site, settings, db):
    headers = _owner(client, published_site)
    domain = client.post("/api/v1/customer/domains", headers=headers, json={"domain": "santosplumbing.ph"}).json()
    record = _txt(domain)
    providers.dns.set("TXT", record["name"], [record["value"]])
    client.post(f"/api/v1/customer/domains/{domain['id']}/verify", headers=headers)
    client.put(f"/api/v1/customer/domains/{domain['id']}/website", headers=headers, json={"serve_website": True})
    live = settings.generated_sites_dir / "_d" / "santosplumbing.ph"
    assert live.exists()

    service = DomainService(db, settings)
    later = datetime.now(UTC) + timedelta(days=2)
    providers.dns.fail = True  # resolver trouble is not revocation
    assert service.recheck(SYSTEM, now=later)["failed"] == 0 and live.exists()
    providers.dns.fail = False
    providers.dns.set("TXT", record["name"], [])  # the owner (or a new domain holder) removed the record
    assert service.recheck(SYSTEM, now=later)["failed"] == 1
    assert not live.exists()
    assert any("no longer connected" in m.subject for m in providers.email.outbox)

    # re-verify, serve again, then downgrade: serving stops
    providers.dns.set("TXT", record["name"], [record["value"]])
    client.post(f"/api/v1/customer/domains/{domain['id']}/verify", headers=headers)
    client.put(f"/api/v1/customer/domains/{domain['id']}/website", headers=headers, json={"serve_website": True})
    assert live.exists()
    client.post("/api/v1/customer/subscription", headers=headers, json={"plan": "free"})
    assert not live.exists()
    assert client.get("/api/v1/customer/domains", headers=headers).json()[0]["serve_website"] is False


def test_email_is_honestly_unavailable_without_a_mail_server(client, published_site):
    headers = _owner(client, published_site)
    domain = _verified_domain(client, headers)
    response = client.post(f"/api/v1/customer/domains/{domain['id']}/email", headers=headers)
    assert response.status_code == 503 and response.json()["error"] == "business_email_unavailable"


def _verified_domain(client, headers, name="santosplumbing.ph"):
    domain = client.post("/api/v1/customer/domains", headers=headers, json={"domain": name}).json()
    record = _txt(domain)
    providers.dns.set("TXT", record["name"], [record["value"]])
    return client.post(f"/api/v1/customer/domains/{domain['id']}/verify", headers=headers).json()


def test_business_email_lifecycle(client, published_site, db):
    mail = FakeMailProvider()
    providers.mail = mail
    headers = _owner(client, published_site)
    pending = client.post("/api/v1/customer/domains", headers=headers, json={"domain": "santosplumbing.ph"}).json()
    early = client.post(f"/api/v1/customer/domains/{pending['id']}/email", headers=headers)
    assert early.status_code == 422  # domain must be verified first
    domain = _verified_domain(client, headers)
    base = f"/api/v1/customer/domains/{domain['id']}"

    enabled = client.post(f"{base}/email", headers=headers)
    assert enabled.status_code == 201
    body = enabled.json()
    assert body["email"]["status"] == "dns_pending"
    mail_records = {(r["type"], r["name"]): r for r in body["records"] if r.get("purpose") and "required" in r}
    assert ("MX", "santosplumbing.ph") in mail_records
    assert mail_records[("TXT", "_dmarc.santosplumbing.ph")]["required"]

    checked = client.post(f"{base}/email/check", headers=headers).json()["email"]
    assert checked["status"] == "dns_pending" and "MX santosplumbing.ph" in checked["dns_missing"]
    for r in mail_records.values():  # the owner publishes the records
        if r["type"] == "MX":
            providers.dns.set("MX", r["name"], [(r["priority"], r["value"])])
        elif r["type"] == "TXT":
            providers.dns.set("TXT", r["name"], [*providers.dns.txt(r["name"]), r["value"]])
    assert client.post(f"{base}/email/check", headers=headers).json()["email"]["status"] == "active"

    created = client.post(f"{base}/mailboxes", headers=headers,
                          json={"local_part": "Info", "display_name": "Front desk"})
    assert created.status_code == 201
    box = created.json()
    assert box["address"] == "info@santosplumbing.ph" and len(box["password"]) >= 16
    assert mail.accounts[next(iter(mail.accounts))]["password"] == box["password"]
    assert box["password"] not in str([vars(m) for m in db.query(Mailbox).all()])  # never stored by us
    listed = client.get("/api/v1/customer/domains", headers=headers).json()[0]["email"]["addresses"]
    assert "password" not in listed[0]

    dup = client.post(f"{base}/mailboxes", headers=headers, json={"local_part": "info"})
    assert dup.status_code == 422
    reserved = client.post(f"{base}/mailboxes", headers=headers, json={"local_part": "postmaster"})
    assert reserved.status_code == 422
    fwd = client.post(f"{base}/mailboxes", headers=headers,
                      json={"local_part": "orders", "kind": "forward", "forward_to": ["Owner.Personal@Gmail.com"]})
    assert fwd.status_code == 201 and "password" not in fwd.json()
    assert next(iter(mail.forwards.values()))["targets"] == ["owner.personal@gmail.com"]
    loop = client.post(f"{base}/mailboxes", headers=headers,
                       json={"local_part": "loop", "kind": "forward", "forward_to": ["info@santosplumbing.ph"]})
    assert loop.status_code == 422

    reset = client.post(f"{base}/mailboxes/{box['id']}/reset-password", headers=headers).json()
    assert reset["password"] != box["password"]
    assert mail.accounts[next(iter(mail.accounts))]["password"] == reset["password"]

    for i in range(4):  # Professional includes 5 mailboxes; forwards don't count
        assert client.post(f"{base}/mailboxes", headers=headers, json={"local_part": f"staff{i}"}).status_code == 201
    over = client.post(f"{base}/mailboxes", headers=headers, json={"local_part": "staff9"})
    assert over.status_code == 403 and over.json()["error"] == "plan_upgrade_required"

    # downgrade: email is suspended (no new addresses) but nothing is deleted
    client.post("/api/v1/customer/subscription", headers=headers, json={"plan": "free"})
    summary = client.get("/api/v1/customer/domains", headers=headers).json()[0]["email"]
    assert summary["status"] == "suspended" and len(mail.accounts) == 5
    client.post("/api/v1/customer/subscription", headers=headers, json={"plan": "professional"})
    assert client.get("/api/v1/customer/domains", headers=headers).json()[0]["email"]["status"] == "active"

    deleted = client.delete(f"{base}/mailboxes/{box['id']}", headers=headers)
    assert deleted.status_code == 204 and len(mail.accounts) == 4
    client.delete(base, headers=headers)  # removing the domain removes its email from the mail server
    assert mail.accounts == {} and mail.forwards == {} and mail.domains == {}
    assert db.query(Mailbox).count() == 0 and db.query(MailDomain).count() == 0
