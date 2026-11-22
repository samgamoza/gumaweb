"""Factory worker: drains the job queue and relays the event outbox.

    python -m app.cli worker            # long-running (Kubernetes Deployment "builder", autoscaled)
    python -m app.cli worker --once     # process what is due and exit (tests, cron)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.exceptions import GumaWebError
from app.domains.website_factory.jobs import JobKind
from app.models import Business, DomainEvent, FactoryJob, Website
from app.schemas.website import RegenerateWebsiteRequest
from app.services.job_queue import JobQueue
from app.services.publishing_service import PublishingService
from app.services.support import SYSTEM
from app.services.website_service import WebsiteService
from app.workflows.website_generation import WebsiteGenerationWorkflow

logger = logging.getLogger("gumaweb.worker")

Handler = Callable[[Session, Settings, dict[str, Any]], dict[str, Any]]


def _generate(db: Session, settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    business = db.get(Business, uuid.UUID(payload["business_id"]))
    if business is None:
        return {"skipped": "business deleted"}
    website = WebsiteGenerationWorkflow(db, settings).run(business, template_slug=payload.get("template_slug"))
    published = False
    if payload.get("publish") and (website.quality_report or {}).get("publishable"):
        PublishingService(db, settings).publish(website, SYSTEM)
        published = True
    db.commit()
    return {"website_id": str(website.id), "quality": website.quality_score, "published": published}


def _regenerate(db: Session, settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    website = db.get(Website, uuid.UUID(payload["website_id"]))
    if website is None:
        return {"skipped": "website deleted"}
    req = RegenerateWebsiteRequest(reset_content=payload.get("reset_content", False),
                                   publish=payload.get("publish", False))
    WebsiteService(db, settings).regenerate(website, req, SYSTEM)
    return {"website_id": str(website.id), "version": website.version}


def _publish(db: Session, settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    website = db.get(Website, uuid.UUID(payload["website_id"]))
    if website is None:
        return {"skipped": "website deleted"}
    deployment = PublishingService(db, settings).publish(website, SYSTEM, force=payload.get("force", False))
    db.commit()
    return {"website_id": str(website.id), "version": deployment.version}


HANDLERS: dict[JobKind, Handler] = {
    JobKind.GENERATE_WEBSITE: _generate,
    JobKind.REGENERATE_WEBSITE: _regenerate,
    JobKind.PUBLISH_WEBSITE: _publish,
}


class FactoryWorker:
    def __init__(self, session_factory: sessionmaker, settings: Settings, worker_id: str | None = None) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"
        self._stopping = False

    def stop(self, *_: object) -> None:
        logger.info("worker %s stopping after current job", self.worker_id)
        self._stopping = True

    def process_one(self) -> bool:
        """Claim and run one job. Returns False when nothing was due."""
        with self.session_factory() as db:
            queue = JobQueue(db)
            job = queue.claim(self.worker_id)
            if job is None:
                return False
            job_id = job.id
            started = time.perf_counter()
            try:
                result = HANDLERS[job.kind](db, self.settings, dict(job.payload))
            except Exception as exc:  # noqa: BLE001 - every failure is recorded on the job
                db.rollback()
                job = db.get(FactoryJob, job_id)
                level = logging.WARNING if isinstance(exc, GumaWebError) else logging.ERROR
                logger.log(level, "job %s (%s) failed: %s", job_id, job.kind, exc, exc_info=level == logging.ERROR)
                queue.fail(job, f"{type(exc).__name__}: {exc}")
                return True
            job = db.get(FactoryJob, job_id)
            result["duration_ms"] = int((time.perf_counter() - started) * 1000)
            queue.complete(job, result)
            return True

    def drain(self, max_jobs: int | None = None) -> int:
        processed = 0
        while (max_jobs is None or processed < max_jobs) and not self._stopping and self.process_one():
            processed += 1
        return processed

    def relay_events(self, batch_size: int = 500) -> int:
        """Outbox relay: publish unprocessed domain events to the Redis stream `gumaweb:events`."""
        if not self.settings.redis_url:
            return 0
        import redis

        client = redis.Redis.from_url(self.settings.redis_url)
        with self.session_factory() as db:
            events = db.scalars(
                select(DomainEvent).where(DomainEvent.processed_at.is_(None))
                .order_by(DomainEvent.occurred_at).limit(batch_size).with_for_update(skip_locked=True)
            ).all()
            for event in events:
                client.xadd(
                    "gumaweb:events",
                    {"id": str(event.id), "type": event.event_type, "aggregate": event.aggregate_type,
                     "aggregate_id": event.aggregate_id, "payload": json.dumps(event.payload, default=str),
                     "occurred_at": event.occurred_at.isoformat()},
                    maxlen=1_000_000, approximate=True,
                )
                event.processed_at = datetime.now(UTC)
            db.commit()
            return len(events)

    def run_forever(self, poll_seconds: float = 2.0) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        logger.info("worker %s started", self.worker_id)
        last_maintenance = 0.0
        while not self._stopping:
            if time.monotonic() - last_maintenance > 60:
                with self.session_factory() as db:
                    recovered = JobQueue(db).recover_stale()
                if recovered:
                    logger.warning("requeued %d stale jobs", recovered)
                last_maintenance = time.monotonic()
            try:
                relayed = self.relay_events()
            except Exception:  # Redis outage must not stop site generation
                logger.exception("event relay failed")
                relayed = 0
            if not self.drain(max_jobs=50) and not relayed:
                time.sleep(poll_seconds)
