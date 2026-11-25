"""Sales CRM C1: the pipeline fills itself from what already happens, and backfill rebuilds it from history."""

from __future__ import annotations

import re
import uuid

import pytest
from sqlalchemy import delete, select

from app.domains.outreach.suppression import SuppressionKind, SuppressionReason
from app.domains.sales import ActivityType, ProspectStage
from app.models import OutreachMessage, Prospect, ProspectActivity
from app.services.prospect_service import ProspectService
from app.services.providers import providers
from app.services.support import SYSTEM
from app.services.suppression_scrub import scrub
from app.services.suppression_service import SuppressionService
from app.workers.factory_worker import FactoryWorker


@pytest.fixture
def worker(session_factory, settings):
    return FactoryWorker(session_factory, settings, worker_id="test")


def prospect(db, business_id) -> Prospect:
    db.expire_all()
    return db.scalar(select(Prospect).where(Prospect.business_id == uuid.UUID(str(business_id))))


def timeline(db, business_id) -> list[str]:
    p = prospect(db, business_id)
    return [a.type.value for a in db.scalars(select(ProspectActivity).where(ProspectActivity.prospect_id == p.id)
                                             .order_by(ProspectActivity.occurred_at, ProspectActivity.created_at))]


def launch_and_send(client, admin_headers) -> None:
    launched = client.post("/api/v1/outreach/campaign", json={"name": "c"}, headers=admin_headers).json()
    client.post(f"/api/v1/outreach/campaigns/{launched['campaign_id']}/dispatch", headers=admin_headers)


def claim(client, subdomain) -> dict[str, str]:
    client.post("/api/v1/claims", json={"subdomain": subdomain, "claimant_name": "Jose",
                                        "claimant_email": "santos.plumbing@gmail.com"})
    token = re.search(r"token=([\w-]+)", providers.email.outbox[-1].text).group(1)
    tokens = client.post("/api/v1/claims/verify", json={"token": token, "password": "OwnerPass!2026"}).json()
    return {"Authorization": f"Bearer {tokens['tokens']['access_token']}"}


def test_publishing_creates_a_new_prospect_once(client, admin_headers, published_site, db):
    business_id = published_site["business"]["id"]
    assert prospect(db, business_id).stage is ProspectStage.NEW
    client.post(f"/api/v1/websites/{published_site['website']['id']}/publish", headers=admin_headers)
    assert timeline(db, business_id) == ["site_published"]  # republishing is a replay


def test_outreach_moves_the_stage_forward_and_records_first_opens_only(client, admin_headers, published_site, db):
    business_id = published_site["business"]["id"]
    launch_and_send(client, admin_headers)
    assert prospect(db, business_id).stage is ProspectStage.CONTACTED

    token = db.scalar(select(OutreachMessage.tracking_token).where(OutreachMessage.step == 0))
    for _ in range(3):  # image proxies reload the pixel
        client.get(f"/api/v1/public/outreach/open/{token}.gif")
    client.get(f"/api/v1/public/outreach/click/{token}", follow_redirects=False)
    p = prospect(db, business_id)
    assert p.stage is ProspectStage.ENGAGED and p.last_touch_at is not None
    assert timeline(db, business_id) == ["site_published", "email_sent", "email_opened", "link_clicked"]
    opened = db.scalar(select(ProspectActivity).where(ProspectActivity.type == ActivityType.EMAIL_OPENED))
    assert opened.data["stage_to"] == "engaged" and opened.data["step"] == 0


def test_claim_then_paid_plan_reaches_won_and_a_downgrade_is_noted_not_regressed(client, admin_headers,
                                                                                published_site, db):
    business_id = published_site["business"]["id"]
    launch_and_send(client, admin_headers)
    headers = claim(client, published_site["website"]["subdomain"])
    assert prospect(db, business_id).stage is ProspectStage.CLAIMED

    assert client.post("/api/v1/customer/subscription", headers=headers, json={"plan": "professional"}).status_code \
        == 200
    assert prospect(db, business_id).stage is ProspectStage.WON
    client.post("/api/v1/customer/subscription", headers=headers, json={"plan": "free"})
    assert prospect(db, business_id).stage is ProspectStage.WON
    assert timeline(db, business_id)[-4:] == ["claim_started", "claim_approved", "subscribed", "churned"]


def test_blocking_suppression_closes_the_prospect_but_an_unsubscribe_does_not(client, admin_headers, published_site,
                                                                               worker, db):
    business_id = published_site["business"]["id"]
    launch_and_send(client, admin_headers)
    token = db.scalar(select(OutreachMessage.tracking_token).where(OutreachMessage.step == 0))
    client.get(f"/api/v1/public/outreach/unsubscribe/{token}")
    worker.drain()
    assert prospect(db, business_id).stage is ProspectStage.CONTACTED  # email only (decision R4)
    assert {"unsubscribed", "suppressed"} <= set(timeline(db, business_id))  # SQLite: same-second order varies

    client.post("/api/v1/outreach/suppressions", json={"kind": "domain", "value": "gmail.com", "reason": "requested"},
                headers=admin_headers)
    worker.drain()
    p = prospect(db, business_id)
    assert p.stage is ProspectStage.DO_NOT_CONTACT
    closing = [a.data for a in db.scalars(select(ProspectActivity).where(
        ProspectActivity.prospect_id == p.id, ProspectActivity.type == ActivityType.SUPPRESSED))
        if a.data.get("stage_to") == "do_not_contact"]
    assert len(closing) == 1 and closing[0]["reason"] == "requested" and closing[0]["blocks_all"] is True


def test_a_customer_keeps_their_stage_when_suppressed(client, published_site, db, settings):
    business_id = published_site["business"]["id"]
    claim(client, published_site["website"]["subdomain"])
    SuppressionService(db).add(SuppressionKind.EMAIL, "santos.plumbing@gmail.com", SuppressionReason.LEGAL, SYSTEM)
    result = scrub(db, settings, SuppressionKind.EMAIL, "santos.plumbing@gmail.com")
    assert result.prospects_noted == 1
    assert prospect(db, business_id).stage is ProspectStage.CLAIMED


def test_backfill_rebuilds_the_same_pipeline_from_history_and_is_idempotent(client, admin_headers, published_site,
                                                                           db):
    business_id = published_site["business"]["id"]
    launch_and_send(client, admin_headers)
    token = db.scalar(select(OutreachMessage.tracking_token).where(OutreachMessage.step == 0))
    client.get(f"/api/v1/public/outreach/open/{token}.gif")
    headers = claim(client, published_site["website"]["subdomain"])
    client.post("/api/v1/customer/subscription", headers=headers, json={"plan": "professional"})
    live = (prospect(db, business_id).stage, timeline(db, business_id))
    assert live[0] is ProspectStage.WON

    db.execute(delete(ProspectActivity))  # as if the CRM never existed
    db.execute(delete(Prospect))
    db.commit()
    first = ProspectService(db).backfill()
    assert first.prospects == 1 and first.activities == len(live[1])
    assert (prospect(db, business_id).stage, sorted(timeline(db, business_id))) == (live[0], sorted(live[1]))

    again = ProspectService(db).backfill()
    assert (again.prospects, again.activities) == (0, 0)
