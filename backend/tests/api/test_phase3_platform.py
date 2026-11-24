"""Phase 3: CRM + lead management, online booking, AI chatbot - plan-gated, wired into published sites."""

import json
import re
from datetime import date, timedelta

import pytest

from app.agents import registry
from app.services.providers import providers
from tests.fakes import FakeLLM


def _owner(client, published_site, email="santos.plumbing@gmail.com") -> dict[str, str]:
    subdomain = published_site["website"]["subdomain"]
    client.post("/api/v1/claims", json={"subdomain": subdomain, "claimant_name": "Jose", "claimant_email": email})
    token = re.search(r"token=([\w-]+)", providers.email.outbox[-1].text).group(1)
    tokens = client.post("/api/v1/claims/verify", json={"token": token, "password": "OwnerPass!2026"}).json()
    return {"Authorization": f"Bearer {tokens['tokens']['access_token']}"}


def _plan(client, headers, plan):
    assert client.post("/api/v1/customer/subscription", headers=headers, json={"plan": plan}).status_code == 200


def _next_weekday(min_days=2) -> date:
    day = date.today() + timedelta(days=min_days)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


@pytest.fixture
def owner(client, published_site):
    return _owner(client, published_site)


def test_contact_form_leads_become_crm_contacts_but_crm_is_plan_gated(client, published_site, owner):
    sub = published_site["website"]["subdomain"]
    for msg in ("Leaking sink", "Also the shower"):
        client.post(f"/api/v1/public/sites/{sub}/contact", headers={"Accept": "application/json"},
                    data={"name": "Maria", "email": "Maria@Example.ph", "message": msg})

    gated = client.get("/api/v1/customer/crm/contacts", headers=owner)
    assert gated.status_code == 403 and gated.json()["error"] == "plan_upgrade_required"
    features = client.get("/api/v1/customer/features", headers=owner).json()
    assert features["plan"] == "Free" and features["features"]["crm"] is False

    _plan(client, owner, "business")  # upgrade reveals contacts captured while on Free
    contacts = client.get("/api/v1/customer/crm/contacts", headers=owner).json()
    assert contacts["total"] == 1  # deduplicated by normalized email
    contact = client.get(f"/api/v1/customer/crm/contacts/{contacts['items'][0]['id']}", headers=owner).json()
    assert contact["email"] == "maria@example.ph" and contact["source"] == "contact_form"
    assert [a["type"] for a in contact["activities"]].count("form_submission") == 2


def test_crm_contact_lifecycle(client, owner, published_site):
    _plan(client, owner, "business")
    created = client.post("/api/v1/customer/crm/contacts", headers=owner,
                          json={"name": "=cmd|' /C calc'!A0", "phone": "0917 555 0001", "value_cents": 150000})
    assert created.status_code == 201
    cid = created.json()["id"]
    dup = client.post("/api/v1/customer/crm/contacts", headers=owner, json={"name": "Dup", "phone": "+63 917 555 0001"})
    assert dup.status_code == 409 and dup.json()["error"] == "duplicate_contact"

    moved = client.patch(f"/api/v1/customer/crm/contacts/{cid}", headers=owner, json={"stage": "qualified"})
    assert moved.json()["stage"] == "qualified"
    client.post(f"/api/v1/customer/crm/contacts/{cid}/activities", headers=owner,
                json={"type": "call", "body": "Called"})
    detail = client.get(f"/api/v1/customer/crm/contacts/{cid}", headers=owner).json()
    assert [a["type"] for a in detail["activities"]][:2] == ["call", "stage_change"]

    pipeline = {s["stage"]: s for s in client.get("/api/v1/customer/crm/pipeline", headers=owner).json()}
    assert pipeline["qualified"] == {"stage": "qualified", "count": 1, "value_cents": 150000}
    csv_text = client.get("/api/v1/customer/crm/export.csv", headers=owner).text
    assert "'=cmd" in csv_text  # formula injection neutralized

    assert client.delete(f"/api/v1/customer/crm/contacts/{cid}", headers=owner).status_code == 204


def test_booking_end_to_end(client, published_site, owner, sites_dir):
    sub = published_site["website"]["subdomain"]
    assert client.get("/api/v1/customer/booking/settings", headers=owner).status_code == 403
    _plan(client, owner, "business")
    assert client.get(f"/api/v1/public/sites/{sub}/booking").status_code == 404  # not enabled yet

    no_services = client.put("/api/v1/customer/booking/settings", headers=owner, json={"enabled": True})
    assert no_services.status_code == 422
    saved = client.put("/api/v1/customer/booking/settings", headers=owner, json={
        "enabled": True, "auto_confirm": True,
        "services": [{"name": "Leak Repair Visit", "duration_minutes": 60}]})
    assert saved.status_code == 200, saved.text
    contact_page = (sites_dir / sub / "contact" / "index.html").read_text(encoding="utf-8")
    assert 'class="card booking-form"' in contact_page and "Book an Appointment" in contact_page
    home_page = (sites_dir / sub / "index.html").read_text(encoding="utf-8")
    assert "form[data-booking]" not in home_page  # widget JS ships only where a widget exists

    info = client.get(f"/api/v1/public/sites/{sub}/booking").json()
    assert info["services"][0]["name"] == "Leak Repair Visit" and info["timezone"] == "Asia/Manila"
    day = _next_weekday()
    slots = client.get(f"/api/v1/public/sites/{sub}/booking/slots",
                       params={"date": day.isoformat(), "service": "Leak Repair Visit"}).json()
    assert slots and slots[0]["label"] == "9:00 AM" and slots[-1]["label"] == "4:00 PM"

    booking = {"service": "Leak Repair Visit", "start": slots[0]["start"], "name": "Ana Reyes",
               "email": "ana@example.ph", "notes": "Kitchen sink"}
    made = client.post(f"/api/v1/public/sites/{sub}/booking", json=booking)
    assert made.status_code == 201 and made.json()["status"] == "confirmed"
    taken = client.post(f"/api/v1/public/sites/{sub}/booking", json={**booking, "email": "other@example.ph"})
    assert taken.status_code == 409 and taken.json()["error"] == "slot_taken"
    later = client.get(f"/api/v1/public/sites/{sub}/booking/slots",
                       params={"date": day.isoformat(), "service": "Leak Repair Visit"}).json()
    assert slots[0]["start"] not in {s["start"] for s in later}

    mail = next(m for m in providers.email.outbox if m.to == "ana@example.ph")
    token = re.search(r"/booking/([\w-]+)", mail.text).group(1)
    assert client.get(f"/api/v1/public/booking/{token}").json()["cancellable"] is True

    appts = client.get("/api/v1/customer/booking/appointments", headers=owner).json()
    assert len(appts) == 1 and appts[0]["customer_name"] == "Ana Reyes"
    contacts = client.get("/api/v1/customer/crm/contacts?source=booking", headers=owner).json()
    assert contacts["total"] == 1

    cancelled = client.post(f"/api/v1/public/booking/{token}/cancel").json()
    assert cancelled["status"] == "cancelled"
    rebook = client.post(f"/api/v1/public/sites/{sub}/booking", json={**booking, "email": "carl@example.ph"})
    assert rebook.status_code == 201  # the freed slot can be booked again

    _plan(client, owner, "free")  # downgrade removes the module from the site and API
    assert client.get(f"/api/v1/public/sites/{sub}/booking").status_code == 404
    assert "booking-form" not in (sites_dir / sub / "contact" / "index.html").read_text(encoding="utf-8")


def test_owner_confirms_pending_bookings(client, published_site, owner):
    sub = published_site["website"]["subdomain"]
    _plan(client, owner, "business")
    client.put("/api/v1/customer/booking/settings", headers=owner, json={
        "enabled": True, "auto_confirm": False, "services": [{"name": "Inspection", "duration_minutes": 30}]})
    slots = client.get(f"/api/v1/public/sites/{sub}/booking/slots",
                       params={"date": _next_weekday().isoformat(), "service": "Inspection"}).json()
    made = client.post(f"/api/v1/public/sites/{sub}/booking", json={
        "service": "Inspection", "start": slots[2]["start"], "name": "Ben", "phone": "0917 555 0909"}).json()
    assert made["status"] == "pending"
    confirmed = client.post(f"/api/v1/customer/booking/appointments/{made['appointment_id']}/confirm", headers=owner)
    assert confirmed.json()["status"] == "confirmed"
    again = client.post(f"/api/v1/customer/booking/appointments/{made['appointment_id']}/confirm", headers=owner)
    assert again.status_code == 409


def test_chatbot_retrieval_lead_capture_and_widget(client, published_site, owner, sites_dir):
    sub = published_site["website"]["subdomain"]
    _plan(client, owner, "business")
    assert client.get("/api/v1/customer/chatbot/settings", headers=owner).status_code == 403  # AI tier only
    _plan(client, owner, "ai")
    enabled = client.put("/api/v1/customer/chatbot/settings", headers=owner,
                         json={"enabled": True, "greeting": "Hi! Ask us about plumbing."})
    assert enabled.status_code == 200
    home = (sites_dir / sub / "index.html").read_text(encoding="utf-8")
    assert 'class="chat__toggle' in home and "Ask us about plumbing." in home

    kb = client.get("/api/v1/customer/chatbot/knowledge", headers=owner).json()
    assert any(e["section"] == "faq" for e in kb) and all(e["source"] == "website" for e in kb)
    client.post("/api/v1/customer/chatbot/knowledge", headers=owner,
                json={"title": "Do you work on Sundays?", "content": "We do emergency visits on Sundays."})

    first = client.post(f"/api/v1/public/sites/{sub}/chat", json={"message": "Hello"}).json()
    assert first["reply"] == "Hi! Ask us about plumbing."
    session = first["session_token"]
    sunday = client.post(f"/api/v1/public/sites/{sub}/chat",
                         json={"message": "Do you work on Sundays?", "session_token": session}).json()
    assert "emergency visits on Sundays" in sunday["reply"]
    unknown = client.post(f"/api/v1/public/sites/{sub}/chat",
                          json={"message": "Can you fix my spaceship hyperdrive?", "session_token": session}).json()
    assert "Leave your name" in unknown["reply"]
    lead = client.post(f"/api/v1/public/sites/{sub}/chat", json={
        "message": "My name is Lito Cruz, call me at 0917 222 3333", "session_token": session}).json()
    assert "passed your details" in lead["reply"]

    convs = client.get("/api/v1/customer/chatbot/conversations", headers=owner).json()
    assert len(convs) == 1 and convs[0]["lead_captured"] is True and convs[0]["message_count"] == 8
    detail = client.get(f"/api/v1/customer/chatbot/conversations/{convs[0]['id']}", headers=owner).json()
    assert [m["role"] for m in detail["messages"]][:2] == ["user", "assistant"]
    contact = client.get("/api/v1/customer/crm/contacts?source=chatbot", headers=owner).json()["items"][0]
    assert contact["name"] == "Lito Cruz" and contact["phone"] == "639172223333"


def test_chatbot_uses_local_llm_when_enabled(client, published_site, owner, monkeypatch, settings):
    sub = published_site["website"]["subdomain"]
    _plan(client, owner, "ai")
    client.put("/api/v1/customer/chatbot/settings", headers=owner, json={"enabled": True})
    llm = FakeLLM(raw=json.dumps({"answer": "Yes - call us for emergencies and we'll advise on timing.",
                                  "used": [1], "unknown": False}))
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(registry, "build_llm_client", lambda _s, **_kw: llm)
    reply = client.post(f"/api/v1/public/sites/{sub}/chat", json={"message": "Do you handle emergency repairs?"})
    assert reply.json()["reply"].startswith("Yes - call us for emergencies")
    too_long = client.post(f"/api/v1/public/sites/{sub}/chat", json={"message": "x" * 1001})
    assert llm.calls and too_long.status_code == 422


def test_chat_unavailable_without_plan_or_switch(client, published_site, owner):
    sub = published_site["website"]["subdomain"]
    assert client.post(f"/api/v1/public/sites/{sub}/chat", json={"message": "hi"}).status_code == 404
    _plan(client, owner, "ai")
    assert client.post(f"/api/v1/public/sites/{sub}/chat", json={"message": "hi"}).status_code == 404  # not enabled
