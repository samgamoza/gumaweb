"""Outbound priority score and readiness (A1, pure rules)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domains.sales import ProspectStage as S
from app.domains.sales.priority import ChannelQuality as Q
from app.domains.sales.priority import PriorityInput, is_ready, score_priority

NOW = datetime(2026, 11, 26, 9, tzinfo=UTC)


def test_fit_plus_reachability():
    result = score_priority(PriorityInput(opportunity_score=80, email=Q.OBSERVED, phone=Q.LISTED, now=NOW))
    assert result.score == 32 + 16 + 8
    assert result.channels == ["email", "phone"]
    assert result.reasons[0] == "fit 32: opportunity score 80"


def test_guessed_contacts_are_not_usable():
    result = score_priority(PriorityInput(opportunity_score=70, email=Q.GUESSED, phone=Q.NONE, now=NOW))
    assert result.channels == [] and "no usable channel" in result.reasons
    assert result.score == 28


def test_engagement_takes_the_strongest_signal_and_decays():
    def score(**last):
        return score_priority(PriorityInput(opportunity_score=0, email=Q.NONE, phone=Q.NONE, now=NOW,
                                            last_engagement=last)).score

    assert score(email_opened=NOW - timedelta(days=1), link_clicked=NOW - timedelta(days=2)) == 20  # max, not sum
    assert score(claim_started=NOW - timedelta(days=10)) == 15  # half after a week
    assert score(link_clicked=NOW - timedelta(days=20)) == 5
    assert score(claim_started=NOW - timedelta(days=45)) == 0


def test_score_is_capped_at_100():
    result = score_priority(PriorityInput(opportunity_score=100, email=Q.CONFIRMED, phone=Q.CONFIRMED, now=NOW,
                                          last_engagement={"claim_started": NOW}))
    assert result.score == 100


def test_readiness():
    later = NOW + timedelta(days=1)
    assert is_ready(S.ENGAGED, ["email"], None, NOW)
    assert not is_ready(S.ENGAGED, [], None, NOW)
    assert not is_ready(S.CLAIMED, ["email"], None, NOW) and not is_ready(S.DO_NOT_CONTACT, ["phone"], None, NOW)
    assert not is_ready(S.LOST, ["email"], None, NOW)  # lost without a cooldown stays out
    assert not is_ready(S.LOST, ["email"], later, NOW) and is_ready(S.LOST, ["email"], NOW, later)
