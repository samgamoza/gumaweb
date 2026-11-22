"""Template Selection Engine: industry -> template, without requiring AI redesign."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class TemplateCandidate:
    slug: str
    category: str
    version: int
    is_default: bool
    industries: tuple[str, ...] = ()


def select_template(
    candidates: Sequence[TemplateCandidate],
    industry: str,
    category: str,
    requested_slug: str | None = None,
    variety_seed: int | None = None,
) -> TemplateCandidate | None:
    """Priority: explicit request > industry-specific > category default > newest in category > general.

    With `variety_seed` (e.g. a hash of the business id), businesses in the same industry are spread
    deterministically across all industry-specific templates, so neighbouring sites don't look identical."""
    if requested_slug:
        return next((c for c in candidates if c.slug == requested_slug), None)

    def best(pool: list[TemplateCandidate]) -> TemplateCandidate | None:
        if not pool:
            return None
        return sorted(pool, key=lambda c: (c.is_default, c.version), reverse=True)[0]

    industry_pool = sorted((c for c in candidates if industry in c.industries), key=lambda c: c.slug)
    if variety_seed is not None and len(industry_pool) > 1:
        return industry_pool[variety_seed % len(industry_pool)]

    return (
        best(industry_pool)
        or best([c for c in candidates if c.category == category])
        or best([c for c in candidates if c.category == "general"])
        or best(list(candidates))
    )
