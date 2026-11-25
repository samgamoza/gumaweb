"""Live discovery: run a source (OSM, Google Places, fixture) and import what it finds.

Requests are queued (`JobKind.DISCOVER_BUSINESSES`) and run by the factory worker, so a slow source never
holds an HTTP request open. Every result goes through `BusinessService.import_records`, the same
normalize / dedupe / score pipeline as a CSV import, and each new business gets contact provenance.

A source that fails (HTTP error, quota) is recorded as a failed DiscoveryRun and the job completes: retrying
a quota error immediately only burns more quota, so the operator re-runs it deliberately.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, ValidationFailedError
from app.domains.business_discovery.contacts import ContactKind, ContactObservation, ContactPurpose, ValueType
from app.domains.business_discovery.providers.base import (
    DiscoveredBusiness,
    DiscoveryError,
    DiscoveryQuery,
    DiscoveryQuotaExceeded,
    SourceDescriptor,
)
from app.domains.business_discovery.providers.registry import (
    SOURCE_LABELS,
    DiscoveryConfig,
    SourceUnavailableError,
    UnknownSourceError,
    build_provider,
    describe_sources,
)
from app.domains.business_discovery.sources import RawBusinessRecord
from app.domains.website_factory.jobs import JobKind
from app.models import Business, DiscoveryRun, FactoryJob, User
from app.services.business_service import BusinessService
from app.services.contact_service import ContactService
from app.services.job_queue import JobQueue
from app.services.support import SYSTEM, Actor

logger = logging.getLogger("gumaweb.discovery")

# Tests replace this to route provider traffic through httpx.MockTransport.
http_client_factory: Callable[[], httpx.Client] = lambda: httpx.Client(timeout=40.0)  # noqa: E731

# How sure we are that a phone printed in a directory listing belongs to the business.
DIRECTORY_PHONE_CONFIDENCE = 0.8


def discovery_config(settings: Settings) -> DiscoveryConfig:
    allow_fixture = settings.discovery_allow_fixture
    if allow_fixture is None:
        allow_fixture = settings.environment != "production"
    return DiscoveryConfig(google_maps_api_key=settings.google_maps_api_key,
                           overpass_endpoint=settings.overpass_endpoint, user_agent=settings.discovery_user_agent,
                           allow_fixture=allow_fixture)


def _query_from(payload: dict[str, Any]) -> DiscoveryQuery:
    try:
        return DiscoveryQuery(category=payload.get("category"), city=payload.get("city"),
                              query=payload.get("query"), limit=int(payload.get("limit", 30)))
    except ValueError as exc:
        raise ValidationFailedError(str(exc)) from exc


class DiscoveryService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.config = discovery_config(settings)

    def sources(self) -> list[SourceDescriptor]:
        return describe_sources(self.config)

    def _descriptor(self, source: str) -> SourceDescriptor:
        found = next((s for s in self.sources() if s.id == source), None)
        if found is None:
            raise ValidationFailedError(f"Unknown or disabled discovery source: {source}")
        if not found.configured:
            raise ValidationFailedError(f"{found.name} is not configured")
        return found

    def enqueue(self, source: str, payload: dict[str, Any], actor: Actor) -> FactoryJob:
        """Validate now (so the caller gets a clear error), run later on the worker."""
        self._descriptor(source)
        query = _query_from(payload)
        job_payload = {"source": source, "category": query.category, "city": query.city, "query": query.query,
                       "limit": query.limit, "started_by": str(actor.user_id) if actor.user_id else None}
        key = f"discover:{source}:{(query.category or '').lower()}:{(query.city or '').lower()}:" \
              f"{(query.query or '').lower()}"
        job = JobQueue(self.db).enqueue(JobKind.DISCOVER_BUSINESSES, job_payload, dedupe_key=key[:255],
                                        max_attempts=1)
        if job is None:
            raise ConflictError("The same discovery is already queued or running", code="discovery_in_progress")
        self.db.commit()
        return job

    def run(self, source: str, query: DiscoveryQuery, actor: Actor) -> DiscoveryRun:
        """Fetch from the source and import. Never raises for source failures: they become a failed run."""
        label = SOURCE_LABELS.get(source)
        if label is None:
            raise ValidationFailedError(f"Unknown discovery source: {source}")
        businesses = BusinessService(self.db, self.settings)
        with http_client_factory() as client:
            try:
                provider = build_provider(source, client, self.config)
                found = provider.discover(query)
            except (UnknownSourceError, SourceUnavailableError, DiscoveryError) as exc:
                kind = "quota" if isinstance(exc, DiscoveryQuotaExceeded) else "error"
                logger.warning("discovery %s %s failed (%s): %s", source, query, kind, exc)
                return businesses.record_failed_run(label, actor, f"{type(exc).__name__}: {exc}")

        by_record: dict[int, DiscoveredBusiness] = {}
        records: list[RawBusinessRecord] = []
        for item in found:
            record = item.to_raw_record()
            by_record[id(record)] = item
            records.append(record)

        contacts = ContactService(self.db)

        def record_provenance(business: Business, record: RawBusinessRecord) -> None:
            item = by_record.get(id(record))
            if item is None:
                return
            observations = []
            if item.phone:
                observations.append(ContactObservation(
                    ContactKind.PHONE, item.phone, item.source, source_ref=item.place_id,
                    confidence=DIRECTORY_PHONE_CONFIDENCE, purpose=ContactPurpose.LEAD_QUALIFICATION))
            if item.owner:
                observations.append(ContactObservation(
                    ContactKind.OWNER, item.owner, item.source, source_ref=item.place_id,
                    value_type=ValueType.OBSERVED, purpose=ContactPurpose.LEAD_QUALIFICATION))
            if observations:
                contacts.record(business, observations, discovery_run_id=business.discovery_run_id)

        run = businesses.import_records(records, label, actor, on_created=record_provenance)
        logger.info("discovery %s %s: %d found, %d created, %d duplicates", source, query, len(found),
                    run.created_count, run.duplicate_count)
        return run


def run_discovery_job(db: Session, settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    """Factory worker handler for JobKind.DISCOVER_BUSINESSES."""
    actor = SYSTEM
    if payload.get("started_by"):
        user = db.get(User, uuid.UUID(payload["started_by"]))
        actor = Actor(user=user) if user else SYSTEM
    run = DiscoveryService(db, settings).run(payload["source"], _query_from(payload), actor)
    return {"discovery_run_id": str(run.id), "status": run.status.value, "created": run.created_count,
            "duplicates": run.duplicate_count, "errors": run.error_count}
