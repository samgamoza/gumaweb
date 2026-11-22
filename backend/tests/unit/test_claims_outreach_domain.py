import pytest
from jinja2.exceptions import SecurityError

from app.domains.business_discovery.enums import BusinessStatus
from app.domains.business_discovery.lifecycle import advance
from app.domains.claims.enums import VerificationMethod
from app.domains.claims.risk import RiskInput, assess_claim_risk, requires_manual_review
from app.domains.outreach.sequence import DEFAULT_SEQUENCE, render_message, validate_sequence


def _risk(**overrides):
    base = dict(method=VerificationMethod.EMAIL, claimant_email="owner@gmail.com", claimant_phone=None,
                business_email=None, business_phone=None, business_website=None,
                recent_claims_from_ip=1, competing_active_claims=0)
    return assess_claim_risk(RiskInput(**{**base, **overrides}))


def test_matching_business_email_is_low_risk():
    assert _risk(business_email="owner@gmail.com").score == 0


def test_unknown_claimant_is_moderate_and_auto_approvable():
    assessment = _risk()
    assert assessment.score == 30
    assert not requires_manual_review(assessment, VerificationMethod.EMAIL, threshold=60)


def test_disposable_and_competing_claims_need_review():
    assessment = _risk(claimant_email="x@mailinator.com", competing_active_claims=1)
    assert assessment.score == 100
    assert requires_manual_review(assessment, VerificationMethod.EMAIL, threshold=60)


def test_business_identity_always_reviewed():
    assessment = _risk(method=VerificationMethod.BUSINESS_IDENTITY, business_email="owner@gmail.com")
    assert requires_manual_review(assessment, VerificationMethod.BUSINESS_IDENTITY, threshold=60)


def test_lifecycle_only_moves_forward():
    assert advance(BusinessStatus.PUBLISHED, BusinessStatus.SCORED) == BusinessStatus.PUBLISHED
    assert advance(BusinessStatus.SCORED, BusinessStatus.GENERATED) == BusinessStatus.GENERATED
    assert advance(BusinessStatus.ARCHIVED, BusinessStatus.CLAIMED) == BusinessStatus.ARCHIVED


def test_default_sequence_matches_spec_days():
    assert [s["day"] for s in DEFAULT_SEQUENCE] == [0, 3, 7, 14]


def test_render_message_includes_links_and_unsubscribe():
    subject, body = render_message(DEFAULT_SEQUENCE[0]["subject"], DEFAULT_SEQUENCE[0]["body"], {
        "business_name": "ABC", "city": "Angeles", "website_url": "http://w", "claim_url": "http://c",
        "unsubscribe_url": "http://u"})
    assert subject == "We Built a Website for Your Business"
    assert "Hi ABC" in body and "http://w" in body and "Unsubscribe: http://u" in body


def test_sandbox_blocks_unsafe_templates():
    with pytest.raises(SecurityError):
        render_message("{{ ''.__class__.__mro__ }}", "x", {})


def test_validate_sequence_rejects_duplicates():
    with pytest.raises(ValueError):
        validate_sequence([{"step": 0, "day": 0, "subject": "a", "body": "b"}] * 2)
