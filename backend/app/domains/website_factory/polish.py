"""Outreach readiness (A7b polish pass): a stricter review than the publish gate, run before a draft is emailed.

Publishable means "good enough to go live if the owner asks". Outreach-ready means "good enough to be the first thing
an owner sees of us": every quality check passes, the copy is clean, and the page has what makes it look finished.
Drafts that fall short are held for an operator (fix, re-run, or approve by hand); the engine doesn't email them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domains.website_factory.content_quality import evaluate_section

COPY_SECTIONS = ("hero", "about", "services", "faq", "cta")
MIN_SERVICES = 2


@dataclass
class PolishReview:
    checks: dict[str, bool] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return all(self.checks.values())

    def as_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "checks": self.checks, "issues": self.issues}


def review_draft(quality_report: dict[str, Any] | None, content: dict[str, dict[str, Any]], *,
                 known_facts: str, has_contact: bool, min_readability: float, max_spam: int,
                 generated: frozenset[str] = frozenset()) -> PolishReview:
    """`generated`: sections written by a model. Only those are held to the readability bar: the template copy is
    the baseline that bar is measured against (as in the content agent). Spam and invented claims count everywhere."""
    review = PolishReview()
    report = quality_report or {}

    checks = report.get("checks") or {}
    failed = sorted(name for name, ok in checks.items() if not ok)
    review.checks["quality_complete"] = bool(checks) and not failed
    if failed:
        review.issues.append(f"quality checks failing: {', '.join(failed)}")

    copy_issues = []
    for key in COPY_SECTIONS:
        if key in content:
            quality = evaluate_section(key, content[key], max_spam=max_spam, known_facts=known_facts,
                                       min_readability=min_readability if key in generated else float("-inf"))
            copy_issues += [f"{key}: {issue}" for issue in quality.issues]
    review.checks["copy_clean"] = not copy_issues
    review.issues += copy_issues

    hero = content.get("hero") or {}
    review.checks["hero_image"] = isinstance(hero.get("image"), dict) and bool(
        hero["image"].get("asset_id") or hero["image"].get("path"))
    if not review.checks["hero_image"]:
        review.issues.append("hero has no image")

    services = (content.get("services") or {}).get("items") or []
    review.checks["services"] = len(services) >= MIN_SERVICES
    if not review.checks["services"]:
        review.issues.append(f"fewer than {MIN_SERVICES} services listed")

    review.checks["contact"] = has_contact
    if not has_contact:
        review.issues.append("no phone or email on the site")
    return review
