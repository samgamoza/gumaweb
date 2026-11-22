"""Business lifecycle transitions: statuses only move forward through the pipeline."""

from __future__ import annotations

from app.domains.business_discovery.enums import BusinessStatus

PIPELINE_ORDER = [
    BusinessStatus.DISCOVERED,
    BusinessStatus.SCORED,
    BusinessStatus.PROFILED,
    BusinessStatus.GENERATED,
    BusinessStatus.PUBLISHED,
    BusinessStatus.CLAIMED,
]


def advance(current: BusinessStatus, target: BusinessStatus) -> BusinessStatus:
    """Return the new status: `target` if it is further along than `current`, else `current`.
    Archived businesses never advance."""
    if current == BusinessStatus.ARCHIVED:
        return current
    if PIPELINE_ORDER.index(target) > PIPELINE_ORDER.index(current):
        return target
    return current
