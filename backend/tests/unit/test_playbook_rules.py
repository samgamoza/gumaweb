"""Outbound playbook rules (A2, pure)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domains.sales.playbooks import DEFAULT_PLAYBOOK, Facts, PlaybookError, decide, in_quiet_hours, validate_steps

T0 = datetime(2026, 11, 26, 2, tzinfo=UTC)  # 10:00 in Manila


def facts(now_h: float = 0, *, done=None, opened=(), click_h=None, claim_h=None, engaged=False, score=80) -> Facts:
    def at(h):
        return (None if h is None else T0 + timedelta(hours=h))
    return Facts(now=T0 + timedelta(hours=now_h), enrolled_at=T0, done=done or {}, opened_refs=frozenset(opened),
                 first_click_at=at(click_h), first_claim_start_at=at(claim_h), engaged=engaged, score=score)


STEPS = {s["key"]: s for s in DEFAULT_PLAYBOOK["steps"]}
SENT_INTRO = {"intro": {"status": "sent", "at": T0.isoformat(), "message_id": "m1"}}


def test_default_playbook_is_valid():
    assert validate_steps(DEFAULT_PLAYBOOK["steps"])


@pytest.mark.parametrize(("steps", "message"), [
    ([{"key": "a", "channel": "fax", "when": "enrolled", "body": "x"}], "channel"),
    ([{"key": "a", "channel": "email", "when": "someday", "subject": "s", "body": "x"}], "when"),
    ([{"key": "a", "channel": "email", "when": "not_opened", "ref": "zzz", "subject": "s", "body": "x"}], "ref"),
    ([{"key": "a", "channel": "email", "when": "enrolled", "body": "x"}], "subject"),
    ([{"key": "a", "channel": "call_task", "when": "enrolled"}], "title"),
    ([{"key": "a", "channel": "sms", "when": "enrolled", "body": "x"},
      {"key": "a", "channel": "sms", "when": "enrolled", "body": "x"}], "unique"),
])
def test_invalid_steps_are_rejected(steps, message):
    with pytest.raises(PlaybookError, match=message):
        validate_steps(steps)


def test_intro_fires_on_enrollment():
    assert decide(STEPS["intro"], facts()).action == "fire"


def test_resend_waits_48h_then_fires_unless_opened():
    assert decide(STEPS["resend"], facts(10, done=SENT_INTRO)).action == "wait"
    assert decide(STEPS["resend"], facts(49, done=SENT_INTRO)).action == "fire"
    assert decide(STEPS["resend"], facts(49, done=SENT_INTRO, opened={"intro"})).reason == "opened"
    assert decide(STEPS["resend"], facts(49, done=SENT_INTRO, engaged=True)).reason == "engaged"  # clicked
    skipped = {"intro": {"status": "skipped", "at": T0.isoformat()}}
    assert decide(STEPS["resend"], facts(49, done=skipped)).action == "skip"
    assert decide(STEPS["resend"], facts(49)).action == "wait"  # intro not decided yet


def test_click_and_claim_followups():
    assert decide(STEPS["waiting"], facts(30)).action == "wait"  # never clicked
    assert decide(STEPS["waiting"], facts(30, click_h=10)).action == "wait"  # 24h after the click is hour 34
    assert decide(STEPS["waiting"], facts(35, click_h=10)).action == "fire"
    assert decide(STEPS["waiting"], facts(35, click_h=10, claim_h=11)).reason == "claim started"
    assert decide(STEPS["almost"], facts(12, claim_h=11)).action == "wait"
    assert decide(STEPS["almost"], facts(14, claim_h=11)).action == "fire"


def test_call_task_only_for_unengaged_high_scorers():
    assert decide(STEPS["call"], facts(73)).action == "fire"
    assert decide(STEPS["call"], facts(10)).action == "wait"
    assert decide(STEPS["call"], facts(73, engaged=True)).reason == "engaged"
    assert decide(STEPS["call"], facts(73, score=40)).reason == "score below threshold"


def test_quiet_hours_wrap_midnight_in_manila_time():
    def manila(hour):
        return (datetime(2026, 11, 26, hour, tzinfo=UTC) - timedelta(hours=8))
    assert in_quiet_hours(manila(21), 20, 8) and in_quiet_hours(manila(7), 20, 8)
    assert not in_quiet_hours(manila(8), 20, 8) and not in_quiet_hours(manila(19), 20, 8)
    assert in_quiet_hours(manila(13), 12, 14) and not in_quiet_hours(manila(14), 12, 14)
    assert not in_quiet_hours(manila(3), 0, 0)  # start == end: no quiet hours
