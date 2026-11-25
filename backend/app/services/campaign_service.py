"""Discovery campaigns: saved sweeps of cities x categories x sources, run on the worker with live progress.

Ported from guma_os `crawl-runner.ts` and `crawl-campaigns.ts`:

* One campaign run at a time across the whole system (single flight). Overpass is a free community service
  under fair use; two concurrent sweeps, which a double-click would otherwise start, risk getting blocked.
* A failing query (timeout, 429) is a warning, not the end of the sweep.
* The sweep stops once `target` unique businesses are found (deduped by provider id across sources).
* Cancelling stops after the current query; what was found so far is still imported.
* Results go through the same import pipeline as everything else, one batch per source so each business
  keeps its true source label, with provenance and enrichment queued per new business.

Progress is written to `DiscoveryRun.progress` after every query so the admin page can poll it.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.domains.audit.actions import AuditAction
from app.domains.business_discovery.enums import ACTIVE_RUN_STATUSES, DiscoveryRunStatus
from app.domains.business_discovery.providers.base import DiscoveredBusiness, DiscoveryError, DiscoveryQuery
from app.domains.business_discovery.providers.registry import SOURCE_LABELS, build_provider
from app.domains.website_factory.jobs import JobKind
from app.models import DiscoveryCampaign, DiscoveryRun, User
from app.services import discovery_service
from app.services.business_service import BusinessService
from app.services.discovery_service import DiscoveryService
from app.services.enrichment_service import EnrichmentService
from app.services.job_queue import JobQueue
from app.services.support import SYSTEM, Actor, audit

logger = logging.getLogger("gumaweb.campaigns")

SINGLE_FLIGHT_KEY = "discovery-campaign"  # one campaign run at a time, system-wide
MAX_WARNINGS = 50
MAX_LIST_ITEMS = 50
sleep: Callable[[float], None] = time.sleep  # tests replace this


def _clean_list(values: Sequence[str] | None) -> list[str]:
    seen: list[str] = []
    for value in values or []:
        item = " ".join(str(value).split())
        if item and item.lower() not in {s.lower() for s in seen}:
            seen.append(item)
    return seen


def _key(b: DiscoveredBusiness) -> str:
    return b.place_id or f"{b.name.lower()}|{(b.city or '').lower()}"


class CampaignService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # --- validation -----------------------------------------------------------------------------
    def _validated(self, data: dict[str, Any]) -> dict[str, Any]:
        name = " ".join(str(data.get("name") or "").split())
        if not name:
            raise ValidationFailedError("A campaign needs a name")
        cities, categories = _clean_list(data.get("cities")), _clean_list(data.get("categories"))
        if not cities:
            raise ValidationFailedError("Pick at least one city")
        if not categories:
            raise ValidationFailedError("Pick at least one category")
        if len(cities) > MAX_LIST_ITEMS or len(categories) > MAX_LIST_ITEMS:
            raise ValidationFailedError(f"At most {MAX_LIST_ITEMS} cities and {MAX_LIST_ITEMS} categories")
        sources = _clean_list(data.get("sources"))
        if not sources:
            raise ValidationFailedError("Pick at least one discovery source")
        available = {s.id: s for s in DiscoveryService(self.db, self.settings).sources()}
        bad = [s for s in sources if s not in available or not available[s].configured]
        if bad:
            raise ValidationFailedError(f"Unknown, disabled or unconfigured source(s): {', '.join(bad)}")
        tiers = data.get("enrichment_tiers")
        if tiers is not None:
            tiers = _clean_list(tiers)
            enabled = {t.id for t in EnrichmentService(self.db, self.settings).tiers() if t.enabled}
            bad = [t for t in tiers if t not in enabled]
            if bad:
                raise ValidationFailedError(f"Unknown or disabled enrichment tier(s): {', '.join(bad)}")
        target, per_query = int(data.get("target") or 100), int(data.get("per_query") or 50)
        if not 1 <= target <= 5000:
            raise ValidationFailedError("Target must be between 1 and 5000")
        if not 1 <= per_query <= 500:
            raise ValidationFailedError("Results per query must be between 1 and 500")
        return {"name": name[:200], "description": (data.get("description") or None), "cities": cities,
                "categories": categories, "sources": sources, "enrichment_tiers": tiers, "target": target,
                "per_query": per_query}

    # --- CRUD -----------------------------------------------------------------------------------
    def list(self) -> Sequence[DiscoveryCampaign]:
        return self.db.scalars(select(DiscoveryCampaign).order_by(DiscoveryCampaign.created_at.desc())).all()

    def get(self, campaign_id: uuid.UUID) -> DiscoveryCampaign:
        campaign = self.db.get(DiscoveryCampaign, campaign_id)
        if campaign is None:
            raise NotFoundError("Campaign not found")
        return campaign

    def create(self, data: dict[str, Any], actor: Actor) -> DiscoveryCampaign:
        campaign = DiscoveryCampaign(**self._validated(data), created_by=actor.user_id)
        self.db.add(campaign)
        self.db.flush()
        audit(self.db, actor, AuditAction.DISCOVERY_CAMPAIGN_CREATED, "discovery_campaign", campaign.id)
        self.db.commit()
        return campaign

    def update(self, campaign: DiscoveryCampaign, data: dict[str, Any], actor: Actor) -> DiscoveryCampaign:
        for field, value in self._validated(data).items():
            setattr(campaign, field, value)
        audit(self.db, actor, AuditAction.DISCOVERY_CAMPAIGN_UPDATED, "discovery_campaign", campaign.id)
        self.db.commit()
        return campaign

    def delete(self, campaign: DiscoveryCampaign, actor: Actor) -> None:
        if self.active_run(campaign.id) is not None:
            raise ConflictError("Cancel the running sweep before deleting this campaign")
        audit(self.db, actor, AuditAction.DISCOVERY_CAMPAIGN_DELETED, "discovery_campaign", campaign.id,
              {"name": campaign.name})
        self.db.delete(campaign)  # past runs stay, with campaign_id cleared
        self.db.commit()

    def runs(self, campaign_id: uuid.UUID, limit: int = 25) -> Sequence[DiscoveryRun]:
        return self.db.scalars(
            select(DiscoveryRun).where(DiscoveryRun.campaign_id == campaign_id)
            .order_by(DiscoveryRun.started_at.desc()).limit(limit)
        ).all()

    def active_run(self, campaign_id: uuid.UUID | None = None) -> DiscoveryRun | None:
        stmt = select(DiscoveryRun).where(DiscoveryRun.status.in_(ACTIVE_RUN_STATUSES),
                                          DiscoveryRun.campaign_id.is_not(None))
        if campaign_id is not None:
            stmt = stmt.where(DiscoveryRun.campaign_id == campaign_id)
        return self.db.scalars(stmt.limit(1)).first()

    # --- running --------------------------------------------------------------------------------
    def start(self, campaign: DiscoveryCampaign, actor: Actor) -> DiscoveryRun:
        self._validated(self._as_input(campaign))  # sources may have been disabled since it was saved
        run_id = uuid.uuid4()
        job = JobQueue(self.db).enqueue(JobKind.RUN_CAMPAIGN, {"run_id": str(run_id), "campaign_id": str(campaign.id)},
                                        dedupe_key=SINGLE_FLIGHT_KEY, max_attempts=1)
        if job is None:
            raise ConflictError("Another campaign sweep is queued or running. Wait for it or cancel it.",
                                code="campaign_in_progress")
        planned = len(campaign.cities) * len(campaign.categories) * len(campaign.sources)
        run = DiscoveryRun(id=run_id, source=SOURCE_LABELS[campaign.sources[0]], status=DiscoveryRunStatus.QUEUED,
                           campaign_id=campaign.id, started_by=actor.user_id, errors=[],
                           progress=self._progress(planned=planned, target=campaign.target, sources=campaign.sources))
        self.db.add(run)
        audit(self.db, actor, AuditAction.DISCOVERY_CAMPAIGN_STARTED, "discovery_campaign", campaign.id,
              {"run": str(run_id)})
        self.db.commit()
        return run

    def cancel(self, run: DiscoveryRun, actor: Actor) -> DiscoveryRun:
        if run.status not in ACTIVE_RUN_STATUSES:
            raise ConflictError(f"This run is already {run.status.value}")
        run.cancel_requested = True
        audit(self.db, actor, AuditAction.DISCOVERY_CAMPAIGN_CANCELLED, "discovery_run", run.id)
        self.db.commit()
        return run

    def execute(self, run_id: uuid.UUID, actor: Actor = SYSTEM) -> DiscoveryRun:
        """The sweep itself (worker). Never raises for source trouble: failures end up on the run."""
        run = self.db.get(DiscoveryRun, run_id)
        if run is None:
            raise NotFoundError("Discovery run not found")
        campaign = self.db.get(DiscoveryCampaign, run.campaign_id) if run.campaign_id else None
        if campaign is None:
            return self._finish(run, DiscoveryRunStatus.FAILED, actor, "The campaign was deleted before it ran")
        progress = dict(run.progress or {})
        progress.setdefault("warnings", [])
        run.status = DiscoveryRunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        run.progress = progress
        self.db.commit()

        discovery = DiscoveryService(self.db, self.settings)
        found: dict[str, DiscoveredBusiness] = {}
        failures = 0
        try:
            with discovery_service.http_client_factory() as client:
                providers = {s: build_provider(s, client, discovery.config) for s in campaign.sources}
                plan = [(city, category, source) for city in campaign.cities for category in campaign.categories
                        for source in campaign.sources]
                for index, (city, category, source) in enumerate(plan):
                    self.db.refresh(run, ["cancel_requested"])
                    if run.cancel_requested:
                        break
                    progress["current"] = f"{city} · {category} · {source}"
                    try:
                        results = providers[source].discover(
                            DiscoveryQuery(category=category, city=city, limit=campaign.per_query))
                    except DiscoveryError as exc:
                        failures += 1
                        results = []
                        if len(progress["warnings"]) < MAX_WARNINGS:
                            progress["warnings"].append(f"{city} / {category} / {source}: {exc}"[:300])
                    for item in results:
                        found.setdefault(_key(item), item)
                    progress.update(queries_done=index + 1, found=len(found),
                                    prospects=sum(1 for b in found.values() if not b.website))
                    run.progress = dict(progress)
                    self.db.commit()
                    if len(found) >= campaign.target:
                        break
                    if index + 1 < len(plan):
                        sleep(self.settings.discovery_query_delay_seconds)

            items = list(found.values())[: campaign.target]
            businesses = BusinessService(self.db, self.settings)
            for source in campaign.sources:
                batch = [b for b in items if b.source == source]
                if batch:
                    records, hook = discovery.import_hook(batch, actor, enrichment_tiers=campaign.enrichment_tiers)
                    businesses.import_records(records, SOURCE_LABELS[source], actor, on_created=hook, run=run,
                                              finalize=False)
        except Exception as exc:  # noqa: BLE001 - anything unexpected must still close the run
            logger.exception("campaign run %s failed", run.id)
            self.db.rollback()
            run = self.db.get(DiscoveryRun, run_id)
            return self._finish(run, DiscoveryRunStatus.FAILED, actor, f"{type(exc).__name__}: {exc}")

        progress.pop("current", None)
        run.progress = dict(progress)
        if run.cancel_requested:
            status = DiscoveryRunStatus.CANCELLED
        elif failures and failures == progress.get("queries_done") and not found:
            status = DiscoveryRunStatus.FAILED  # every query failed: say so, rather than "completed, found 0"
        else:
            status = DiscoveryRunStatus.COMPLETED
        return self._finish(run, status, actor)

    def _finish(self, run: DiscoveryRun, status: DiscoveryRunStatus, actor: Actor,
                error: str | None = None) -> DiscoveryRun:
        run.status = status
        run.finished_at = datetime.now(UTC)
        if error:
            run.errors = [*(run.errors or []), {"row": None, "error": error[:300]}]
        progress = dict(run.progress or {})
        progress.pop("current", None)
        run.progress = progress
        audit(self.db, actor, AuditAction.BUSINESS_IMPORTED, "discovery_run", run.id,
              {"campaign": str(run.campaign_id), "status": status.value, "created": run.created_count,
               "duplicates": run.duplicate_count})
        self.db.commit()
        return run

    @staticmethod
    def _progress(*, planned: int, target: int, sources: list[str]) -> dict[str, Any]:
        return {"queries_done": 0, "queries_planned": planned, "found": 0, "prospects": 0, "target": target,
                "sources": sources, "warnings": []}

    @staticmethod
    def _as_input(c: DiscoveryCampaign) -> dict[str, Any]:
        return {"name": c.name, "description": c.description, "cities": c.cities, "categories": c.categories,
                "sources": c.sources, "enrichment_tiers": c.enrichment_tiers, "target": c.target,
                "per_query": c.per_query}


def run_campaign_job(db: Session, settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    """Factory worker handler for JobKind.RUN_CAMPAIGN."""
    run = db.get(DiscoveryRun, uuid.UUID(payload["run_id"]))
    actor = SYSTEM
    if run is not None and run.started_by:
        user = db.get(User, run.started_by)
        actor = Actor(user=user) if user else SYSTEM
    run = CampaignService(db, settings).execute(uuid.UUID(payload["run_id"]), actor)
    return {"discovery_run_id": str(run.id), "status": run.status.value, "found": run.progress.get("found", 0),
            "created": run.created_count, "duplicates": run.duplicate_count}
