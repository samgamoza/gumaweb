"""Durable factory job queue on PostgreSQL.

Workers claim jobs with `SELECT ... FOR UPDATE SKIP LOCKED`, so any number of
replicas can drain the queue concurrently without double-processing and
without running a separate broker. (SQLite, used by tests, ignores the lock
clause; it is single-writer anyway.)
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.domains.website_factory.jobs import ACTIVE_JOB_STATUSES, STALE_LOCK_AFTER, JobKind, JobStatus, retry_delay
from app.models import FactoryJob


def _now() -> datetime:
    return datetime.now(UTC)


class JobQueue:
    def __init__(self, db: Session) -> None:
        self.db = db

    def enqueue(self, kind: JobKind, payload: dict[str, Any], *, dedupe_key: str | None = None,
                priority: int = 100, max_attempts: int = 3) -> FactoryJob | None:
        """Add a job; returns None when an identical job (same dedupe_key) is already queued or running."""
        if dedupe_key and self.db.scalar(
            select(FactoryJob.id).where(FactoryJob.dedupe_key == dedupe_key,
                                        FactoryJob.status.in_(ACTIVE_JOB_STATUSES))
        ):
            return None
        job = FactoryJob(kind=kind, payload=payload, dedupe_key=dedupe_key, priority=priority,
                         max_attempts=max_attempts, run_after=_now())
        try:
            with self.db.begin_nested():
                self.db.add(job)
        except IntegrityError:  # lost a race with a concurrent enqueue
            return None
        return job

    def claim(self, worker_id: str) -> FactoryJob | None:
        stmt = (
            select(FactoryJob)
            .where(FactoryJob.status == JobStatus.QUEUED, FactoryJob.run_after <= _now())
            .order_by(FactoryJob.priority, FactoryJob.run_after)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = self.db.scalar(stmt)
        if job is None:
            self.db.commit()
            return None
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.locked_at = _now()
        job.locked_by = worker_id
        self.db.commit()
        return job

    def complete(self, job: FactoryJob, result: dict[str, Any] | None = None) -> None:
        job.status = JobStatus.SUCCEEDED
        job.result = result or {}
        job.finished_at = _now()
        job.last_error = None
        self.db.commit()

    def fail(self, job: FactoryJob, error: str) -> None:
        job.last_error = error[:4000]
        job.locked_at = None
        job.locked_by = None
        if job.attempts >= job.max_attempts:
            job.status = JobStatus.FAILED
            job.finished_at = _now()
        else:
            job.status = JobStatus.QUEUED
            job.run_after = _now() + retry_delay(job.attempts)
        self.db.commit()

    def retry(self, job: FactoryJob) -> FactoryJob:
        if job.status != JobStatus.FAILED:
            raise ConflictError("Only failed jobs can be retried")
        job.status = JobStatus.QUEUED
        job.attempts = 0
        job.run_after = _now()
        job.finished_at = None
        self.db.commit()
        return job

    def recover_stale(self) -> int:
        """Requeue jobs whose worker died mid-run (lock older than STALE_LOCK_AFTER)."""
        result = self.db.execute(
            update(FactoryJob)
            .where(FactoryJob.status == JobStatus.RUNNING, FactoryJob.locked_at < _now() - STALE_LOCK_AFTER)
            .values(status=JobStatus.QUEUED, locked_at=None, locked_by=None, run_after=_now())
        )
        self.db.commit()
        return result.rowcount or 0

    def get(self, job_id: uuid.UUID) -> FactoryJob | None:
        return self.db.get(FactoryJob, job_id)

    def counts(self) -> dict[str, int]:
        from sqlalchemy import func

        rows = self.db.execute(select(FactoryJob.status, func.count()).group_by(FactoryJob.status)).all()
        counts = {status.value: 0 for status in JobStatus}
        counts.update({str(status): count for status, count in rows})
        return counts

    def recent(self, status: JobStatus | None, limit: int = 100) -> Sequence[FactoryJob]:
        stmt = select(FactoryJob).order_by(FactoryJob.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(FactoryJob.status == status)
        return self.db.scalars(stmt).all()
