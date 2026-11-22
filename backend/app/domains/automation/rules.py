"""Business automation (20-roadmap Phase 4 `business_automation`): when <trigger> [if <conditions>] do <actions>.

Pure rule vocabulary, validation, matching and rendering. Execution (idempotent,
via the job queue) lives in services/automation_service.py.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from jinja2 import TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment

from app.core.exceptions import ValidationFailedError
from app.domains.crm.enums import ContactSource, ContactStage


class Trigger(StrEnum):
    LEAD_CAPTURED = "lead_captured"  # a new contact arrived from any channel
    LEAD_BECAME_HOT = "lead_became_hot"  # lead score crossed the hot threshold
    STAGE_CHANGED = "stage_changed"
    APPOINTMENT_BOOKED = "appointment_booked"
    APPOINTMENT_CANCELLED = "appointment_cancelled"
    APPOINTMENT_REMINDER = "appointment_reminder"  # scheduled: config.hours_before
    CONTACT_IDLE = "contact_idle"  # scheduled: config.idle_days without activity
    CALL_COMPLETED = "call_completed"


SCHEDULED_TRIGGERS = (Trigger.APPOINTMENT_REMINDER, Trigger.CONTACT_IDLE)


class ActionType(StrEnum):
    EMAIL_CONTACT = "email_contact"
    SMS_CONTACT = "sms_contact"
    NOTIFY_OWNER = "notify_owner"
    SET_STAGE = "set_stage"
    ADD_TAG = "add_tag"


_ACTION_FIELDS: dict[ActionType, set[str]] = {
    ActionType.EMAIL_CONTACT: {"subject", "body"},
    ActionType.SMS_CONTACT: {"body"},
    ActionType.NOTIFY_OWNER: {"subject", "body"},
    ActionType.SET_STAGE: {"stage"},
    ActionType.ADD_TAG: {"tag"},
}
MAX_ACTIONS = 5

_env = SandboxedEnvironment(autoescape=False)


def render(template: str, variables: dict[str, Any]) -> str:
    """Owner-written templates render in a Jinja sandbox (no attribute access to internals)."""
    return _env.from_string(template).render(**variables).strip()


def validate_rule(trigger: Trigger, config: dict[str, Any], conditions: dict[str, Any],
                  actions: list[dict[str, Any]]) -> None:
    if trigger == Trigger.APPOINTMENT_REMINDER and not 1 <= int(config.get("hours_before", 0)) <= 168:
        raise ValidationFailedError("Reminders need hours_before between 1 and 168")
    if trigger == Trigger.CONTACT_IDLE and not 1 <= int(config.get("idle_days", 0)) <= 90:
        raise ValidationFailedError("Idle follow-ups need idle_days between 1 and 90")
    unknown = set(conditions) - {"sources", "stages", "min_score", "services"}
    if unknown:
        raise ValidationFailedError(f"Unknown conditions: {', '.join(sorted(unknown))}")
    for source in conditions.get("sources", []):
        ContactSource(source)
    for stage in conditions.get("stages", []):
        ContactStage(stage)
    if not 1 <= len(actions) <= MAX_ACTIONS:
        raise ValidationFailedError(f"A rule needs 1-{MAX_ACTIONS} actions")
    for action in actions:
        try:
            kind = ActionType(action.get("type"))
        except ValueError as exc:
            raise ValidationFailedError(f"Unknown action {action.get('type')!r}") from exc
        missing = _ACTION_FIELDS[kind] - {k for k, v in action.items() if v}
        if missing:
            raise ValidationFailedError(f"{kind.value} needs: {', '.join(sorted(missing))}")
        if kind == ActionType.SET_STAGE:
            ContactStage(action["stage"])
        for field in ("subject", "body"):
            if field in action:
                if len(action[field]) > (200 if field == "subject" else 4000):
                    raise ValidationFailedError(f"{kind.value} {field} is too long")
                try:
                    _env.parse(action[field])
                except TemplateSyntaxError as exc:
                    raise ValidationFailedError(f"Template error in {kind.value} {field}: {exc.message}") from exc


def matches(conditions: dict[str, Any], context: dict[str, Any]) -> bool:
    contact = context.get("contact") or {}
    if conditions.get("sources") and contact.get("source") not in conditions["sources"]:
        return False
    if conditions.get("stages") and contact.get("stage") not in conditions["stages"]:
        return False
    if conditions.get("min_score") is not None and (contact.get("lead_score") or 0) < int(conditions["min_score"]):
        return False
    appointment = context.get("appointment") or {}
    return not (conditions.get("services") and appointment.get("service") not in conditions["services"])


PRESETS: list[dict[str, Any]] = [
    {
        "key": "thank_new_leads", "name": "Thank new leads", "trigger": Trigger.LEAD_CAPTURED, "config": {},
        "conditions": {"sources": ["contact_form", "chatbot"]},
        "actions": [{"type": "email_contact", "subject": "Thanks for contacting {{ business.name }}",
                     "body": "Hi {{ contact.first_name }},\n\nThanks for reaching out to {{ business.name }}. "
                             "We received your message and will get back to you soon.\n\n{{ business.name }}"}],
    },
    {
        "key": "appointment_reminder", "name": "Remind customers 24 hours before", "trigger":
            Trigger.APPOINTMENT_REMINDER, "config": {"hours_before": 24}, "conditions": {},
        "actions": [{"type": "email_contact", "subject": "Reminder: {{ appointment.service }} tomorrow",
                     "body": "Hi {{ contact.first_name }},\n\nThis is a reminder of your {{ appointment.service }} "
                             "on {{ appointment.when }} with {{ business.name }}.\n\nSee you soon!"}],
    },
    {
        "key": "hot_lead_alert", "name": "Tell me about hot leads", "trigger": Trigger.LEAD_BECAME_HOT, "config": {},
        "conditions": {},
        "actions": [{"type": "notify_owner", "subject": "Hot lead: {{ contact.name }}",
                     "body": "{{ contact.name }} ({{ contact.phone or contact.email }}) looks ready to buy "
                             "(score {{ contact.lead_score }}).\nWhy: {{ contact.reasons }}"}],
    },
    {
        "key": "idle_follow_up", "name": "Follow up quiet leads after 3 days", "trigger": Trigger.CONTACT_IDLE,
        "config": {"idle_days": 3}, "conditions": {"stages": ["new", "contacted"]},
        "actions": [{"type": "notify_owner", "subject": "Follow up with {{ contact.name }}",
                     "body": "{{ contact.name }} hasn't heard from you in {{ idle_days }} days. "
                             "A quick call could win the job."},
                    {"type": "add_tag", "tag": "follow-up"}],
    },
]
