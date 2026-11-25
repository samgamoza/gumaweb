"""Phase 4 (automation and integrations): lead intelligence, automations, webhooks, API keys, AI receptionist."""

import json
import re
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text as text_sql

from app.domains.integrations.webhooks import verify
from app.models import Appointment, AutomationRun, Contact, WebhookDelivery
from app.services.automation_service import AutomationService
from app.services.providers import providers
from app.workers.factory_worker import FactoryWorker


def _owner(client, published_site, plan="business"):
    sub = published_site["website"]["subdomain"]
    client.post("/api/v1/claims", json={"subdomain": sub, "claimant_name": "Jose",
                                        "claimant_email": "santos.plumbing@gmail.com"})
    token = re.search(r"token=([\w-]+)", providers.email.outbox[-1].text).group(1)
    tokens = client.post("/api/v1/claims/verify", json={"token": token, "password": "OwnerPass!2026"}).json()
    headers = {"Authorization": f"Bearer {tokens['tokens']['access_token']}"}
    assert client.post("/api/v1/customer/subscription", headers=headers, json={"plan": plan}).status_code == 200
    return headers


def _lead(client, sub, name="Maria", email="maria@example.ph", message="Hello"):
    return client.post(f"/api/v1/public/sites/{sub}/contact", headers={"Accept": "application/json"},
                       data={"name": name, "email": email, "message": message})


@pytest.fixture
def worker(session_factory, settings):
    return FactoryWorker(session_factory, settings, worker_id="test")


@pytest.fixture
def public_dns(monkeypatch):
    """Webhook hosts resolve to a public address without touching real DNS."""
    import ipaddress

    from app.domains.integrations import webhooks

    monkeypatch.setattr(webhooks, "_addresses", lambda host: [ipaddress.ip_address("93.184.216.34")])


def test_leads_are_scored_with_reasons(client, published_site):
    headers = _owner(client, published_site)
    sub = published_site["website"]["subdomain"]
    _lead(client, sub, message="How much for a leak repair? It's urgent, can you come today?")
    _lead(client, sub, name="Ben", email="ben@example.ph", message="hi")
    contacts = client.get("/api/v1/customer/crm/contacts", headers=headers).json()["items"]
    assert contacts[0]["name"] == "Maria"  # sorted by score
    assert contacts[0]["lead_score"] > contacts[1]["lead_score"]
    assert any("buying intent" in r for r in contacts[0]["score_reasons"])


def test_preset_automation_runs_once_per_lead(client, published_site, worker):
    headers = _owner(client, published_site)
    presets = client.get("/api/v1/customer/automations/presets", headers=headers).json()
    assert {p["key"] for p in presets} >= {"thank_new_leads", "appointment_reminder", "hot_lead_alert"}
    rule = client.post("/api/v1/customer/automations/presets/thank_new_leads", headers=headers)
    assert rule.status_code == 201

    _lead(client, published_site["website"]["subdomain"], name="Ana Cruz", email="ana@example.ph")
    assert worker.drain() >= 1
    thanks = [m for m in providers.email.outbox if m.to == "ana@example.ph"]
    assert len(thanks) == 1 and thanks[0].subject.startswith("Thanks for contacting")
    assert "Hi Ana," in thanks[0].text

    # same person again: not a *new* lead, so no second thank-you; replays are idempotent too
    _lead(client, published_site["website"]["subdomain"], name="Ana Cruz", email="ana@example.ph")
    worker.drain()
    assert len([m for m in providers.email.outbox if m.to == "ana@example.ph"]) == 1
    runs = client.get("/api/v1/customer/automations/runs", headers=headers).json()
    assert runs[0]["status"] == "succeeded" and runs[0]["results"][0]["status"] == "done"


def test_hot_lead_alert_and_custom_rule_actions(client, published_site, worker, db):
    headers = _owner(client, published_site)
    client.post("/api/v1/customer/automations/presets/hot_lead_alert", headers=headers)
    created = client.post("/api/v1/customer/automations", headers=headers, json={
        "name": "Tag chat and form leads", "trigger": "lead_captured",
        "conditions": {"sources": ["contact_form"]},
        "actions": [{"type": "add_tag", "tag": "website-lead"}, {"type": "set_stage", "stage": "contacted"}]})
    assert created.status_code == 201
    bad = client.post("/api/v1/customer/automations", headers=headers, json={
        "name": "x" * 3, "trigger": "lead_captured", "actions": [{"type": "email_contact", "subject": "{{ x"}]})
    assert bad.status_code == 422

    sub = published_site["website"]["subdomain"]
    lito = {"name": "Lito", "email": "lito@example.ph", "phone": "0917 111 2222"}
    client.post(f"/api/v1/public/sites/{sub}/contact", headers={"Accept": "application/json"},
                data={**lito, "message": "Need a quote today, how much? urgent"})
    worker.drain()
    # One urgent form scores "warm" (60); a follow-up message makes the lead hot (70+) and alerts the owner.
    assert not any(m.subject.startswith("Hot lead") for m in providers.email.outbox)
    client.post(f"/api/v1/public/sites/{sub}/contact", headers={"Accept": "application/json"},
                data={**lito, "message": "Following up - can you come today?"})
    worker.drain()
    contact = db.query(Contact).filter_by(email="lito@example.ph").one()
    db.refresh(contact)
    assert "website-lead" in contact.tags and contact.stage.value == "contacted"
    alert = next(m for m in providers.email.outbox if m.subject.startswith("Hot lead: Lito"))
    assert alert.to == "santos.plumbing@gmail.com" and "score" in alert.text


def test_appointment_reminders_are_sent_once(client, published_site, worker, db, settings):
    headers = _owner(client, published_site)
    sub = published_site["website"]["subdomain"]
    client.put("/api/v1/customer/booking/settings", headers=headers, json={
        "enabled": True, "services": [{"name": "Visit", "duration_minutes": 30}]})
    client.post("/api/v1/customer/automations/presets/appointment_reminder", headers=headers)
    day = date.today() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    slot = client.get(f"/api/v1/public/sites/{sub}/booking/slots",
                      params={"date": day.isoformat(), "service": "Visit"}).json()[-1]
    client.post(f"/api/v1/public/sites/{sub}/booking", json={"service": "Visit", "start": slot["start"],
                                                             "name": "Carla", "email": "carla@example.ph"})
    appt = db.query(Appointment).one()
    starts = appt.starts_at.replace(tzinfo=UTC) if appt.starts_at.tzinfo is None else appt.starts_at
    service = AutomationService(db, settings)
    assert service.tick(now=starts - timedelta(hours=30))["reminders"] == 0  # outside the 24 h window
    assert service.tick(now=starts - timedelta(hours=20))["reminders"] == 1
    assert service.tick(now=starts - timedelta(hours=10))["reminders"] == 0  # already sent
    reminders = [m for m in providers.email.outbox if m.subject.startswith("Reminder: Visit")]
    assert len(reminders) == 1 and reminders[0].to == "carla@example.ph"
    assert db.query(AutomationRun).filter_by(subject_type="appointment").count() == 1


def test_idle_follow_up_once_per_quiet_period(client, published_site, db, settings):
    headers = _owner(client, published_site)
    client.post("/api/v1/customer/automations/presets/idle_follow_up", headers=headers)
    _lead(client, published_site["website"]["subdomain"], name="Quiet Quinn", email="quinn@example.ph")
    service = AutomationService(db, settings)
    later = datetime.now(UTC) + timedelta(days=4)
    assert service.tick(now=later)["idle"] == 1
    assert service.tick(now=later + timedelta(days=1))["idle"] == 0
    assert any(m.subject == "Follow up with Quiet Quinn" for m in providers.email.outbox)


def test_signed_webhooks_with_retries(public_dns, client, published_site, worker, monkeypatch, settings):
    headers = _owner(client, published_site)
    monkeypatch.setattr(settings, "webhook_allow_private", True)
    received, responses = [], iter([500, 200, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(next(responses))

    providers.http = httpx.Client(transport=httpx.MockTransport(handler))
    ssrf = client.post("/api/v1/customer/integrations/webhooks", headers=headers,
                       json={"url": "ftp://internal/x", "events": ["lead.captured"]})
    assert ssrf.status_code == 422
    endpoint = client.post("/api/v1/customer/integrations/webhooks", headers=headers,
                           json={"url": "http://hooks.example.com/gumaweb", "events": ["lead.captured"]}).json()
    secret = client.get(f"/api/v1/customer/integrations/webhooks/{endpoint['id']}/secret", headers=headers).json()

    _lead(client, published_site["website"]["subdomain"], name="Rosa", email="rosa@example.ph")
    worker.drain()  # first attempt -> HTTP 500 -> job re-queued with backoff
    deliveries = client.get("/api/v1/customer/integrations/deliveries", headers=headers).json()
    assert deliveries[0]["status"] == "failed" and deliveries[0]["response_status"] == 500

    from app.models import FactoryJob
    with worker.session_factory() as s:
        for job in s.query(FactoryJob).filter_by(status="queued"):
            job.run_after = job.created_at
        s.commit()
    worker.drain()  # retry succeeds
    delivery = client.get("/api/v1/customer/integrations/deliveries", headers=headers).json()[0]
    assert delivery["status"] == "delivered" and delivery["attempts"] == 2

    last = received[-1]
    assert last.headers["GumaWeb-Event"] == "lead.captured"
    assert verify(secret["secret"], last.content, last.headers["GumaWeb-Signature"])
    payload = json.loads(last.content)
    assert payload["type"] == "lead.captured" and payload["data"]["contact"]["email"] == "rosa@example.ph"

    rotated = client.post(f"/api/v1/customer/integrations/webhooks/{endpoint['id']}/rotate-secret", headers=headers)
    assert rotated.json()["secret"] != secret["secret"]
    ping = client.post(f"/api/v1/customer/integrations/webhooks/{endpoint['id']}/test", headers=headers)
    assert ping.json()["event_type"] == "ping"
    worker.drain()
    assert json.loads(received[-1].content)["type"] == "ping"


def test_api_keys_scopes_and_lifecycle(client, published_site):
    headers = _owner(client, published_site)
    created = client.post("/api/v1/customer/integrations/api-keys", headers=headers,
                          json={"name": "Guma One sync", "read_only": True}).json()
    key = created["key"]
    assert key.startswith("gw_live_") and created["prefix"] == key[:12]
    listed = client.get("/api/v1/customer/integrations/api-keys", headers=headers).json()
    assert "key" not in listed[0]  # never shown again

    api = {"Authorization": f"Bearer {key}"}
    assert client.get("/api/v1/customer/crm/contacts", headers=api).status_code == 200
    write = client.post("/api/v1/customer/crm/contacts", headers=api, json={"name": "X", "phone": "0917"})
    assert write.status_code == 403
    assert client.get("/api/v1/businesses", headers=api).status_code == 403  # staff API stays closed
    assert client.get("/api/v1/customer/integrations/api-keys", headers=api).status_code == 403  # no self-minting

    writer = client.post("/api/v1/customer/integrations/api-keys", headers=headers,
                         json={"name": "Writer", "read_only": False}).json()["key"]
    assert client.post("/api/v1/customer/subscription", headers={"Authorization": f"Bearer {writer}"},
                       json={"plan": "voice_ai"}).status_code == 403  # billing needs a human session

    client.delete(f"/api/v1/customer/integrations/api-keys/{created['id']}", headers=headers)
    assert client.get("/api/v1/customer/crm/contacts", headers=api).status_code == 401
    client.post("/api/v1/customer/subscription", headers=headers, json={"plan": "free"})
    assert client.get("/api/v1/customer/features", headers={"Authorization": f"Bearer {writer}"}).status_code == 403


def test_receptionist_books_by_phone(client, published_site, db):
    headers = _owner(client, published_site, plan="voice_ai")
    client.put("/api/v1/customer/booking/settings", headers=headers, json={
        "enabled": True, "services": [{"name": "Leak Repair", "duration_minutes": 60}]})
    client.put("/api/v1/customer/voice/settings", headers=headers,
               json={"enabled": True, "phone_number": "0917 555 9000", "forward_number": "0917 555 9001"})

    start = client.post("/api/v1/customer/voice/test-call", headers=headers, json={"caller": "0917 777 1234"}).json()
    assert "book an appointment" in start["say"]
    cid = start["call_id"]

    def say(text):
        return client.post(f"/api/v1/customer/voice/test-call/{cid}/turn", headers=headers, json={"text": text}).json()

    assert "Which day" in say("I need to book a plumber")["say"]
    offer = say(_next_weekday_name())
    assert "Which time" in offer["say"]
    assert "name" in say("the first one")["say"]
    assert "Shall I book it" in say("It's Gloria Santos")["say"]
    assert "You're all set" in say("yes")["say"]
    bye = say("that's all, goodbye")
    assert bye["action"] == "hangup"

    call = client.get("/api/v1/customer/voice/calls", headers=headers).json()[0]
    assert call["outcome"] == "booked" and call["appointment_id"]
    assert "Gloria Santos booked a Leak Repair" in call["summary"]
    appt = client.get("/api/v1/customer/booking/appointments", headers=headers).json()[0]
    assert appt["customer_name"] == "Gloria Santos" and appt["customer_phone"] == "639177771234"
    contact = client.get("/api/v1/customer/crm/contacts?source=phone", headers=headers).json()["items"][0]
    assert contact["phone"] == "639177771234"


def _next_weekday_name() -> str:
    day = date.today() + timedelta(days=2)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.strftime("%A")


def test_gateway_messages_transfers_and_auth(client, published_site, monkeypatch, settings, worker):
    headers = _owner(client, published_site, plan="voice_ai")
    client.put("/api/v1/customer/voice/settings", headers=headers,
               json={"enabled": True, "phone_number": "0917 555 9000", "forward_number": "0917 555 9001"})
    inbound = {"to": "+63 917 555 9000", "from": "+63 918 222 3333"}
    assert client.post("/api/v1/voice/inbound", json=inbound).status_code == 503  # gateway not configured
    monkeypatch.setattr(settings, "voice_gateway_token", "gw-secret")
    wrong = client.post("/api/v1/voice/inbound", json=inbound, headers={"X-Voice-Gateway-Token": "nope"})
    assert wrong.status_code == 401
    gw = {"X-Voice-Gateway-Token": "gw-secret"}
    started = client.post("/api/v1/voice/inbound", json=inbound, headers=gw)
    assert started.status_code == 201
    cid = started.json()["call_id"]
    client.post(f"/api/v1/voice/calls/{cid}/turn", headers=gw, json={"text": "can I leave a message"})
    client.post(f"/api/v1/voice/calls/{cid}/turn", headers=gw, json={"text": "My sink is leaking please call back"})
    done = client.post(f"/api/v1/voice/calls/{cid}/turn", headers=gw, json={"text": "Ramon"}).json()
    assert done["action"] == "hangup"
    message = next(m for m in providers.email.outbox if m.subject == "New phone message from Ramon")
    assert "My sink is leaking" in message.text and "+639182223333" in message.text

    second = client.post("/api/v1/voice/inbound", json=inbound, headers=gw).json()
    transfer = client.post(f"/api/v1/voice/calls/{second['call_id']}/turn", headers=gw,
                           json={"text": "I want to speak to the owner"}).json()
    assert transfer["action"] == "transfer" and transfer["transfer_to"] == "639175559001"

    unknown = client.post("/api/v1/voice/inbound", json={"to": "0999 000 0000", "from": "x"}, headers=gw)
    assert unknown.status_code == 404
    calls = client.get("/api/v1/customer/voice/calls", headers=headers).json()
    assert {c["outcome"] for c in calls} == {"message", "transferred"}
    assert client.post(f"/api/v1/voice/calls/{cid}/turn", headers=gw, json={"text": "hello?"}).status_code == 409


def test_phase4_modules_are_plan_gated(client, published_site):
    headers = _owner(client, published_site, plan="professional")
    for path in ("/api/v1/customer/automations", "/api/v1/customer/voice/settings",
                 "/api/v1/customer/integrations/webhooks"):
        assert client.get(path, headers=headers).status_code == 403
    client.post("/api/v1/customer/subscription", headers=headers, json={"plan": "business"})
    assert client.get("/api/v1/customer/automations", headers=headers).status_code == 200
    assert client.get("/api/v1/customer/voice/settings", headers=headers).status_code == 403  # Voice AI tier


def test_call_completed_webhook(public_dns, client, published_site, monkeypatch, settings, worker, db):
    headers = _owner(client, published_site, plan="voice_ai")
    monkeypatch.setattr(settings, "webhook_allow_private", True)
    monkeypatch.setattr(settings, "voice_gateway_token", "gw-secret")
    received = []
    providers.http = httpx.Client(transport=httpx.MockTransport(lambda r: received.append(r) or httpx.Response(204)))
    client.post("/api/v1/customer/integrations/webhooks", headers=headers,
                json={"url": "http://hooks.example.com/calls", "events": ["call.completed"]})
    client.put("/api/v1/customer/voice/settings", headers=headers,
               json={"enabled": True, "phone_number": "09175559000"})
    gw = {"X-Voice-Gateway-Token": "gw-secret"}
    call = client.post("/api/v1/voice/inbound", json={"to": "09175559000", "from": "09183334444"}, headers=gw).json()
    client.post(f"/api/v1/voice/calls/{call['call_id']}/end", headers=gw)
    worker.drain()
    assert db.query(WebhookDelivery).one().status == "delivered"
    body = json.loads(received[0].content)
    assert body["type"] == "call.completed" and body["data"]["call"]["outcome"] == "abandoned"


def test_call_summary_is_polished_in_the_background(client, published_site, monkeypatch, settings, worker):
    """Regression: the LLM summary ran inline and delayed the caller's "Goodbye" by ~19 s on CPU."""
    from app.agents import registry
    from tests.fakes import FakeLLM

    headers = _owner(client, published_site, plan="voice_ai")
    grounded = FakeLLM(raw="Ramon called about a leaking sink and asked to be called back.")
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(registry, "build_llm_client", lambda _s, **_kw: grounded)
    start = client.post("/api/v1/customer/voice/test-call", headers=headers, json={"caller": "09181112222"}).json()
    for text in ("please take a message", "My sink is leaking please call back", "Ramon"):
        done = client.post(f"/api/v1/customer/voice/test-call/{start['call_id']}/turn", headers=headers,
                           json={"text": text}).json()
    assert done["action"] == "hangup" and grounded.calls == []  # nothing ran while the caller waited
    assert client.get("/api/v1/customer/voice/calls", headers=headers).json()[0]["summary"].startswith(
        "Ramon left a message")
    worker.drain()
    assert client.get("/api/v1/customer/voice/calls", headers=headers).json()[0]["summary"] == (
        "Ramon called about a leaking sink and asked to be called back.")


def test_backfill_scores_silently_and_close_stale_calls(client, published_site, db, settings):
    """Upgrading leaves pre-Phase-4 contacts unscored; the backfill must not email "hot lead" alerts.
    Calls whose hang-up never arrived are closed by maintenance."""
    from app.services.crm_service import CrmService
    from app.services.voice_service import VoiceService

    headers = _owner(client, published_site, plan="voice_ai")
    client.post("/api/v1/customer/automations/presets/hot_lead_alert", headers=headers)
    sub = published_site["website"]["subdomain"]
    for msg in ("How much? urgent, today please", "Following up, can you come today?"):
        client.post(f"/api/v1/public/sites/{sub}/contact", headers={"Accept": "application/json"},
                    data={"name": "Old Lead", "email": "old@example.ph", "phone": "09171234000", "message": msg})
    contact = db.query(Contact).filter_by(email="old@example.ph").one()
    contact.lead_score = contact.lead_temperature = None  # as if created before the upgrade
    db.commit()
    jobs_before = db.execute(text_sql("SELECT count(*) FROM factory_jobs")).scalar()
    assert CrmService(db, settings).rescore_all() >= 1
    db.refresh(contact)
    assert contact.lead_temperature == "hot"
    assert db.execute(text_sql("SELECT count(*) FROM factory_jobs")).scalar() == jobs_before  # no alerts queued

    call = client.post("/api/v1/customer/voice/test-call", headers=headers, json={}).json()
    service = VoiceService(db, settings)
    assert service.close_stale() == 0
    assert service.close_stale(max_age=timedelta(seconds=-1)) == 1
    log = client.get("/api/v1/customer/voice/calls", headers=headers).json()
    assert next(c for c in log if c["id"] == call["call_id"])["outcome"] == "abandoned"
