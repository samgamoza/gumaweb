"""Pure rules: suppression normalization/matching keys and contact promotion (port plan step 2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.domains.business_discovery.contacts import (
    ContactKind,
    ContactObservation,
    PolicyDecision,
    ValueType,
    VerificationStatus,
    choose_primary,
    is_promotable,
)
from app.domains.outreach.suppression import (
    SuppressionKind,
    normalize_domain,
    normalize_suppression,
    suppression_keys,
)

# --- suppression ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Acme.PH", "acme.ph"),
        ("  www.acme.ph. ", "acme.ph"),
        ("@acme.ph", "acme.ph"),
        ("mail.acme.com.ph", "mail.acme.com.ph"),
        ("xn--bcher-kva.example", "xn--bcher-kva.example"),
        ("acme", None),
        ("-acme.ph", None),
        ("acme_.ph", None),  # underscores can't occur, which also keeps LIKE wildcards out of SQL
        ("acme%.ph", None),
        ("a@acme.ph", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_domain(raw, expected):
    assert normalize_domain(raw) == expected


def test_normalize_suppression_email_and_domain():
    assert normalize_suppression(SuppressionKind.EMAIL, " Owner@Acme.PH ") == "owner@acme.ph"
    assert normalize_suppression(SuppressionKind.DOMAIN, "WWW.Acme.ph") == "acme.ph"
    with pytest.raises(ValueError):
        normalize_suppression(SuppressionKind.EMAIL, "not-an-email")
    with pytest.raises(ValueError):
        normalize_suppression(SuppressionKind.DOMAIN, "owner@acme.ph")


def test_suppression_keys_cover_address_and_its_domain():
    assert suppression_keys("Owner@Acme.ph") == [(SuppressionKind.EMAIL, "owner@acme.ph"),
                                                (SuppressionKind.DOMAIN, "acme.ph")]
    assert suppression_keys("garbage") == []
    assert suppression_keys(None) == []


# --- contact promotion ----------------------------------------------------------------------------

NOW = datetime(2026, 11, 25, tzinfo=UTC)


@dataclass
class C:
    value: str
    kind: ContactKind = ContactKind.EMAIL
    value_type: ValueType = ValueType.OBSERVED
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    policy_decision: PolicyDecision = PolicyDecision.ALLOW
    confidence: float = 0.8
    acquired_at: datetime | None = NOW


@pytest.mark.parametrize("value_type", [ValueType.PREDICTED, ValueType.DERIVED])
def test_guessed_or_derived_contacts_are_never_promoted_even_at_full_confidence(value_type):
    guess = C("info@acme.ph", value_type=value_type, confidence=1.0, verification_status=VerificationStatus.VERIFIED)
    assert not is_promotable(guess)
    assert choose_primary([guess], ContactKind.EMAIL) is None


def test_blocked_redacted_and_invalid_contacts_are_not_promoted():
    contacts = [C("a@x.ph", policy_decision=PolicyDecision.BLOCKED),
                C("b@x.ph", policy_decision=PolicyDecision.REDACTED),
                C("c@x.ph", verification_status=VerificationStatus.INVALID)]
    assert choose_primary(contacts, ContactKind.EMAIL) is None


def test_owner_names_are_never_promoted():
    assert not is_promotable(C("Maria Santos", kind=ContactKind.OWNER, value_type=ValueType.USER_SUPPLIED))


def test_ranking_verified_then_user_supplied_then_confidence_then_oldest():
    observed_high = C("high@x.ph", confidence=0.99)
    user = C("user@x.ph", value_type=ValueType.USER_SUPPLIED, confidence=0.5)
    verified = C("verified@x.ph", verification_status=VerificationStatus.VERIFIED, confidence=0.3)
    assert choose_primary([observed_high, user, verified], ContactKind.EMAIL) is verified
    assert choose_primary([observed_high, user], ContactKind.EMAIL) is user
    newer = C("newer@x.ph", confidence=0.7, acquired_at=NOW)
    older = C("older@x.ph", confidence=0.7, acquired_at=NOW - timedelta(days=3))
    assert choose_primary([newer, older], ContactKind.EMAIL) is older


def test_choose_primary_filters_by_kind():
    phone = C("639171234567", kind=ContactKind.PHONE)
    assert choose_primary([phone], ContactKind.EMAIL) is None
    assert choose_primary([phone], ContactKind.PHONE) is phone


@pytest.mark.parametrize("confidence", [-0.1, 1.5])
def test_observation_rejects_out_of_range_confidence(confidence):
    with pytest.raises(ValueError):
        ContactObservation(ContactKind.EMAIL, "a@x.ph", "test", confidence=confidence)
