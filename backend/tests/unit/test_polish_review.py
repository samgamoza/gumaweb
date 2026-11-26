"""Outreach readiness review (A7b, pure)."""

from __future__ import annotations

from app.domains.website_factory.polish import review_draft

GOOD_REPORT = {"checks": {"pages_exist": True, "layout_valid": True, "content_complete": True, "seo_valid": True,
                          "contact_available": True}}
CONTENT = {
    "hero": {"headline": "Fresh bread daily", "subheadline": "Baked in Angeles City.", "cta_label": "Visit",
             "image": {"asset_id": "a1"}},
    "services": {"heading": "Our Services", "items": [{"name": "Bread"}, {"name": "Cakes"}]},
}


def review(report=GOOD_REPORT, content=CONTENT, **kw):
    args = {"known_facts": "Reyes Bakery Angeles City", "has_contact": True, "min_readability": 50.0,
            "max_spam": 10} | kw
    return review_draft(report, content, **args)


def test_a_complete_draft_is_ready():
    result = review()
    assert result.ready and result.issues == []


def test_each_shortfall_holds_the_draft_with_a_reason():
    assert review(report={"checks": {**GOOD_REPORT["checks"], "seo_valid": False}}).issues == [
        "quality checks failing: seo_valid"]
    assert review(report=None).checks["quality_complete"] is False
    no_image = {**CONTENT, "hero": {k: v for k, v in CONTENT["hero"].items() if k != "image"}}
    assert review(content=no_image).issues == ["hero has no image"]
    one_service = {**CONTENT, "services": {"heading": "Services", "items": [{"name": "Bread"}]}}
    assert review(content=one_service).issues == ["fewer than 2 services listed"]
    assert review(has_contact=False).issues == ["no phone or email on the site"]


def test_invented_claims_count_everywhere_readability_only_for_generated_copy():
    boasting = {**CONTENT, "hero": {**CONTENT["hero"], "subheadline": "Award-winning bakery since 1950."}}
    result = review(content=boasting)
    assert not result.ready and any("unsupported claim" in i for i in result.issues)

    dense = ("Notwithstanding considerable organizational transformations, comprehensive institutional "
             "methodologies necessitate multidimensional operational reconceptualization, particularly regarding "
             "infrastructural sustainability, interdepartmental communication, and administrative accountability "
             "frameworks, notwithstanding unprecedented technological disruption across interconnected international "
             "commercial ecosystems.")
    hard = {**CONTENT, "about": {"heading": "About", "company_story": dense}}
    assert review(content=hard).ready  # template copy is the readability baseline
    assert not review(content=hard, generated=frozenset({"about"})).ready
