import re
from datetime import UTC, datetime, timedelta

from app.services.outreach_service import OutreachService
from app.services.providers import providers


def test_campaign_launch_dispatch_and_tracking(client, admin_headers, published_site, db, settings):
    launched = client.post("/api/v1/outreach/campaign", json={"name": "Pampanga plumbers"}, headers=admin_headers)
    assert launched.status_code == 201, launched.text
    result = launched.json()
    assert result == {**result, "enrolled_businesses": 1, "scheduled_messages": 4}

    sent = client.post(f"/api/v1/outreach/campaigns/{result['campaign_id']}/dispatch", headers=admin_headers).json()
    assert sent == {"sent": 1, "skipped": 0, "failed": 0}  # only the Day 0 step is due
    email = providers.email.outbox[-1]  # type: ignore[attr-defined]
    assert email.subject == "We Built a Website for Your Business" and "Unsubscribe:" in email.text

    token = re.search(r"/public/outreach/click/([\w-]+)", email.text).group(1)
    click = client.get(f"/api/v1/public/outreach/click/{token}", follow_redirects=False)
    assert click.status_code == 302 and click.headers["location"] == published_site["website"]["url"]
    assert client.get(f"/api/v1/public/outreach/open/{token}.gif").headers["content-type"] == "image/gif"

    stats = client.get(f"/api/v1/outreach/campaigns/{result['campaign_id']}/stats", headers=admin_headers).json()
    assert (stats["outreach_sent"], stats["opens"], stats["clicks"]) == (1, 1, 1)

    # Relaunch does not double-enroll
    relaunch = client.post(f"/api/v1/outreach/campaigns/{result['campaign_id']}/launch", headers=admin_headers)
    assert relaunch.json()["enrolled_businesses"] == 0

    # Unsubscribe suppresses remaining steps (Day 3 / 7 / 14)
    assert "unsubscribed" in client.get(f"/api/v1/public/outreach/unsubscribe/{token}").text
    later = OutreachService(db, settings).dispatch_due(now=datetime.now(UTC) + timedelta(days=30))
    assert later.sent == 0


def test_claim_is_attributed_to_campaign(client, admin_headers, published_site):
    result = client.post("/api/v1/outreach/campaign", json={"name": "c"}, headers=admin_headers).json()
    client.post(f"/api/v1/outreach/campaigns/{result['campaign_id']}/dispatch", headers=admin_headers)
    claim_url = re.search(r"(http://portal\.test/claim/\S+)", providers.email.outbox[-1].text).group(1)
    ref = claim_url.split("ref=")[1]
    client.post("/api/v1/claims", json={"subdomain": published_site["website"]["subdomain"], "ref": ref,
                                        "claimant_name": "Jose", "claimant_email": "santos.plumbing@gmail.com"})
    stats = client.get(f"/api/v1/outreach/campaigns/{result['campaign_id']}/stats", headers=admin_headers).json()
    assert stats["claims"] == 1


def test_site_events_contact_form_and_overview(client, admin_headers, published_site):
    subdomain = published_site["website"]["subdomain"]
    beacon = client.post(f"/api/v1/public/sites/{subdomain}/events",
                         content='{"event_type":"page_view","path":"/"}', headers={"Content-Type": "text/plain"})
    assert beacon.status_code == 204
    assert client.post(f"/api/v1/public/sites/{subdomain}/events", content="not json").status_code == 422

    lead = client.post(f"/api/v1/public/sites/{subdomain}/contact", headers={"Accept": "application/json"},
                       data={"name": "Maria", "email": "maria@gmail.com", "message": "Leaking sink"})
    assert lead.status_code == 200 and lead.json() == {"ok": True}
    no_js = client.post(f"/api/v1/public/sites/{subdomain}/contact", follow_redirects=False,
                        data={"name": "Pedro", "phone": "0917", "message": "Hi"})
    assert no_js.status_code == 303 and no_js.headers["location"].endswith("/contact/?sent=1")
    honeypot = client.post(f"/api/v1/public/sites/{subdomain}/contact", headers={"Accept": "application/json"},
                           data={"name": "Bot", "email": "b@b.co", "message": "spam", "website": "x"})
    assert honeypot.status_code == 200

    stats = client.get(f"/api/v1/analytics/websites/{published_site['website']['id']}",
                       headers=admin_headers).json()
    assert stats["leads"] == 2 and stats["totals"]["page_view"] == 1

    overview = client.get("/api/v1/analytics/overview", headers=admin_headers).json()
    assert overview["kpis"]["published_sites"] == 1 and overview["kpis"]["generated_sites"] == 1
    assert overview["page_views_30d"] == 1


def test_plans_public_and_health(client):
    plans = client.get("/api/v1/billing/plans").json()
    assert [p["code"] for p in plans] == ["free", "professional", "business", "ai", "voice_ai"]
    assert client.get("/api/v1/health/ready").json()["database"] == "ok"
    assert client.get("/metrics").status_code == 200
