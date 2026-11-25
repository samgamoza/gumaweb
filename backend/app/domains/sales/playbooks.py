"""Outbound playbooks (A2): behaviour-driven, multi-channel follow-up, as pure rules.

A playbook is a list of steps. Each step is a rule that fires **at most once** per enrolled prospect, when its
trigger (`when`) has happened and its delay (`hours`) has passed:

| when                  | delay counts from   | fires if                      | skipped if                 |
|-----------------------|---------------------|-------------------------------|----------------------------|
| `enrolled`            | enrollment          | always                        | —                          |
| `not_opened` (`ref`)  | step `ref` was sent | no open, click or claim start | engaged; ref not sent      |
| `clicked_not_claimed` | first click         | no claim started since        | a claim was started        |
| `claim_abandoned`     | first claim start   | not claimed yet               | —                          |
| `no_engagement`       | enrollment          | no open, click or claim start | engaged; score too low     |

Channels: `email`; `call_task` (creates a task for a person; not a touch); `sms` (skipped until an SMS gateway and
phone opt-outs exist: decision E2 / step A4). Guardrails (quiet hours, weekly touch cap) defer a step, never skip it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

WHEN = ("enrolled", "not_opened", "clicked_not_claimed", "claim_abandoned", "no_engagement")
CHANNELS = ("email", "sms", "call_task")
TOUCH_CHANNELS = ("email", "sms")  # what counts toward the weekly cap and quiet hours
PH_TIME = timezone(timedelta(hours=8))

# The default onboarding playbook. Wording follows owner-triggered publishing: "ready", never "live".
DEFAULT_PLAYBOOK: dict[str, Any] = {
    "name": "Claim your website",
    "max_days": 21,
    "steps": [
        {"key": "intro", "channel": "email", "when": "enrolled", "hours": 0,
         "subject": "Your website is ready, {{ business_name }}",
         "body": ("Hi {{ business_name }},\n\nYour website is ready. We built it from your public business "
                  "listing, and it's yours to claim for free.\n\nSee it and claim it here:\n{{ claim_url }}\n\n"
                  "It takes about a minute.\n\nRegards,\nGumaWeb")},
        {"key": "resend", "channel": "email", "when": "not_opened", "ref": "intro", "hours": 48,
         "subject": "{{ business_name }}: your free website is waiting",
         "body": ("Hi {{ business_name }},\n\nIn case you missed it: your website is ready to claim, free.\n\n"
                  "{{ claim_url }}\n\nRegards,\nGumaWeb")},
        {"key": "waiting", "channel": "email", "when": "clicked_not_claimed", "hours": 24,
         "subject": "Your website is still waiting for you",
         "body": ("Hi {{ business_name }},\n\nYou took a look at your website. Claiming it is free and takes a "
                  "minute; you can change anything afterwards.\n\n{{ claim_url }}\n\nRegards,\nGumaWeb")},
        {"key": "almost", "channel": "email", "when": "claim_abandoned", "hours": 2,
         "subject": "Almost done: finish claiming your website",
         "body": ("Hi {{ business_name }},\n\nYou're one step away from owning your website.\n\n"
                  "{{ claim_url }}\n\nIf something didn't work, just reply to this email.\n\nRegards,\nGumaWeb")},
        {"key": "call", "channel": "call_task", "when": "no_engagement", "hours": 72, "min_score": 70,
         "title": "Call {{ business_name }} about their free website"},
    ],
}


class PlaybookError(ValueError):
    pass


def validate_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys: set[str] = set()
    for step in steps:
        key, channel, when = step.get("key"), step.get("channel"), step.get("when")
        if not key or key in keys:
            raise PlaybookError(f"each step needs a unique key (got {key!r})")
        if channel not in CHANNELS:
            raise PlaybookError(f"step {key}: channel must be one of {', '.join(CHANNELS)}")
        if when not in WHEN:
            raise PlaybookError(f"step {key}: when must be one of {', '.join(WHEN)}")
        if not isinstance(step.get("hours", 0), int | float) or step.get("hours", 0) < 0:
            raise PlaybookError(f"step {key}: hours must be a non-negative number")
        if when == "not_opened" and step.get("ref") not in keys:
            raise PlaybookError(f"step {key}: not_opened needs ref to an earlier step")
        if channel in ("email", "sms") and not step.get("body"):
            raise PlaybookError(f"step {key}: a message step needs a body")
        if channel == "email" and not step.get("subject"):
            raise PlaybookError(f"step {key}: an email step needs a subject")
        if channel == "call_task" and not step.get("title"):
            raise PlaybookError(f"step {key}: a call task needs a title")
        keys.add(key)
    return steps


@dataclass(frozen=True)
class Facts:
    """What has happened to one enrolled prospect, as the rules need it."""

    now: datetime
    enrolled_at: datetime
    done: dict[str, dict[str, Any]]  # step key -> {"status": "sent"|"skipped", "at": iso, ...}
    opened_refs: frozenset[str]  # keys of sent email steps whose message was opened
    first_click_at: datetime | None
    first_claim_start_at: datetime | None
    engaged: bool  # any open, click or claim start since enrollment
    score: int | None


@dataclass(frozen=True)
class Decision:
    action: str  # "fire" | "skip" | "wait"
    reason: str = ""


def decide(step: dict[str, Any], facts: Facts) -> Decision:
    when, delay = step["when"], timedelta(hours=float(step.get("hours", 0)))

    def due(anchor: datetime | None) -> bool:
        return anchor is not None and facts.now >= anchor + delay

    if when == "enrolled":
        return Decision("fire") if due(facts.enrolled_at) else Decision("wait")
    if when == "not_opened":
        ref = facts.done.get(step["ref"])
        if ref is None:
            return Decision("wait")
        if ref.get("status") != "sent":
            return Decision("skip", f"{step['ref']} was not sent")
        if not due(datetime.fromisoformat(ref["at"])):
            return Decision("wait")
        if step["ref"] in facts.opened_refs:
            return Decision("skip", "opened")
        # A click or claim start shows they read it even when the open pixel was blocked (images off).
        return Decision("skip", "engaged") if facts.engaged else Decision("fire")
    if when == "clicked_not_claimed":
        if not due(facts.first_click_at):
            return Decision("wait")
        return Decision("skip", "claim started") if facts.first_claim_start_at else Decision("fire")
    if when == "claim_abandoned":
        return Decision("fire") if due(facts.first_claim_start_at) else Decision("wait")
    # no_engagement
    if facts.engaged:
        return Decision("skip", "engaged")
    if not due(facts.enrolled_at):
        return Decision("wait")
    if step.get("min_score") is not None and (facts.score or 0) < step["min_score"]:
        return Decision("skip", "score below threshold")
    return Decision("fire")


def in_quiet_hours(now: datetime, start_hour: int, end_hour: int) -> bool:
    """Quiet hours in Philippine time; the window may wrap midnight (e.g. 20 → 8)."""
    hour = now.astimezone(PH_TIME).hour
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour
