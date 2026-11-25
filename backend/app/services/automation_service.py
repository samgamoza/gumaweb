"""Business automation execution: idempotent rule runs, presets, and scheduled triggers."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.domains.automation.rules import PRESETS, ActionType, Trigger, matches, render, validate_rule
from app.domains.billing.entitlements import Feature, has_feature
from app.domains.booking.enums import AppointmentStatus
from app.domains.crm.enums import OPEN_STAGES, ActivityType, ContactStage
from app.models import (
    Appointment,
    AutomationRule,
    AutomationRun,
    BookingSettings,
    Business,
    Contact,
    ContactActivity,
    Customer,
    User,
)
from app.services.business_events import contact_context
from app.services.entitlements import plan_for_business
from app.services.notifications import EmailMessage
from app.services.providers import providers

logger = logging.getLogger("gumaweb.automation")


class AutomationService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # --- Rules (owner) -----------------------------------------------------------------------
    def rules(self, business_id: uuid.UUID) -> Sequence[AutomationRule]:
        return self.db.scalars(select(AutomationRule).where(AutomationRule.business_id == business_id)
                               .order_by(AutomationRule.created_at)).all()

    def rule(self, business_id: uuid.UUID, rule_id: uuid.UUID) -> AutomationRule:
        rule = self.db.get(AutomationRule, rule_id)
        if rule is None or rule.business_id != business_id:
            raise NotFoundError("Automation not found")
        return rule

    def create(self, business_id: uuid.UUID, data: dict[str, Any]) -> AutomationRule:
        trigger = Trigger(data["trigger"])
        validate_rule(trigger, data.get("config") or {}, data.get("conditions") or {}, data["actions"])
        rule = AutomationRule(business_id=business_id, name=data["name"], trigger=trigger,
                              config=data.get("config") or {}, conditions=data.get("conditions") or {},
                              actions=data["actions"], enabled=data.get("enabled", True),
                              preset_key=data.get("preset_key"))
        self.db.add(rule)
        self.db.commit()
        return rule

    def update(self, rule: AutomationRule, changes: dict[str, Any]) -> AutomationRule:
        merged = {"trigger": rule.trigger, "config": rule.config, "conditions": rule.conditions,
                  "actions": rule.actions, **changes}
        validate_rule(Trigger(merged["trigger"]), merged["config"] or {}, merged["conditions"] or {},
                      merged["actions"])
        for field, value in changes.items():
            setattr(rule, field, value)
        self.db.commit()
        return rule

    def install_preset(self, business_id: uuid.UUID, key: str) -> AutomationRule:
        preset = next((p for p in PRESETS if p["key"] == key), None)
        if preset is None:
            raise ValidationFailedError(f"Unknown preset '{key}'")
        return self.create(business_id, {**preset, "preset_key": key})

    def runs(self, business_id: uuid.UUID, limit: int = 100) -> Sequence[AutomationRun]:
        return self.db.scalars(select(AutomationRun).where(AutomationRun.business_id == business_id)
                               .order_by(AutomationRun.created_at.desc()).limit(limit)).all()

    # --- Execution ---------------------------------------------------------------------------
    def run_trigger(self, business_id: uuid.UUID, trigger: Trigger, subject_type: str, subject_id: str,
                    context: dict[str, Any]) -> dict[str, int]:
        features, _ = plan_for_business(self.db, business_id)
        stats = {"ran": 0, "skipped": 0}
        if not has_feature(features, Feature.AUTOMATION):
            return stats
        rules = self.db.scalars(select(AutomationRule).where(
            AutomationRule.business_id == business_id, AutomationRule.trigger == trigger,
            AutomationRule.enabled.is_(True))).all()
        for rule in rules:
            if not matches(rule.conditions, context):
                continue
            ran = self._execute(rule, subject_type, subject_id, context)
            stats["ran" if ran else "skipped"] += 1
        self.db.commit()
        return stats

    def _execute(self, rule: AutomationRule, subject_type: str, subject_id: str, context: dict[str, Any]) -> bool:
        key = f"{rule.id}:{rule.trigger.value}:{subject_type}:{subject_id}"
        if context.get("idempotency_suffix"):
            key += f":{context['idempotency_suffix']}"
        run = AutomationRun(rule_id=rule.id, business_id=rule.business_id, idempotency_key=key[:200],
                            subject_type=subject_type, subject_id=subject_id, status="running")
        try:
            with self.db.begin_nested():
                self.db.add(run)
        except IntegrityError:
            return False  # already handled (replay, overlapping tick)
        business = self.db.get(Business, rule.business_id)
        variables = {
            "business": {"name": business.name, "phone": business.phone, "email": business.email},
            "contact": context.get("contact") or {}, "appointment": context.get("appointment") or {},
            "call": context.get("call") or {}, "idle_days": rule.config.get("idle_days"),
        }
        results, failed = [], False
        for action in rule.actions:
            try:
                results.append(self._action(rule, action, variables))
            except Exception as exc:  # one failing action must not block the others
                logger.warning("automation %s action %s failed: %s", rule.id, action.get("type"), exc)
                results.append({"type": action.get("type"), "status": "failed", "error": str(exc)[:300]})
                failed = True
        run.results = results
        run.status = "failed" if failed else ("skipped" if all(r["status"] == "skipped" for r in results)
                                              else "succeeded")
        self.db.flush()
        return True

    def _owner_email(self, business_id: uuid.UUID) -> str | None:
        customer = self.db.scalar(select(Customer).where(Customer.business_id == business_id))
        user = self.db.get(User, customer.user_id) if customer else None
        if user:
            return user.email
        business = self.db.get(Business, business_id)
        return business.email if business else None

    def _action(self, rule: AutomationRule, action: dict[str, Any], v: dict[str, Any]) -> dict[str, Any]:
        kind = ActionType(action["type"])
        contact_data = v["contact"]
        contact = self.db.get(Contact, uuid.UUID(contact_data["id"])) if contact_data.get("id") else None
        if kind == ActionType.EMAIL_CONTACT:
            if not (contact and contact.email):
                return {"type": kind.value, "status": "skipped", "reason": "contact has no email"}
            providers.email.send(EmailMessage(to=contact.email, subject=render(action["subject"], v),
                                              text=render(action["body"], v)))
            self._log(contact, ActivityType.EMAIL, f"Automation '{rule.name}' sent: {render(action['subject'], v)}")
        elif kind == ActionType.SMS_CONTACT:
            if not (contact and contact.phone):
                return {"type": kind.value, "status": "skipped", "reason": "contact has no phone"}
            providers.sms.send(contact.phone, render(action["body"], v)[:480])
            self._log(contact, ActivityType.NOTE, f"Automation '{rule.name}' sent an SMS")
        elif kind == ActionType.NOTIFY_OWNER:
            to = self._owner_email(rule.business_id)
            if not to:
                return {"type": kind.value, "status": "skipped", "reason": "no owner email"}
            providers.email.send(EmailMessage(to=to, subject=render(action["subject"], v),
                                              text=render(action["body"], v)))
        elif kind == ActionType.SET_STAGE:
            if not contact:
                return {"type": kind.value, "status": "skipped", "reason": "no contact"}
            target = ContactStage(action["stage"])
            if contact.stage != target:  # direct update: automations never re-trigger themselves
                self._log(contact, ActivityType.STAGE_CHANGE, f"{contact.stage.value} → {target.value} (automation)")
                contact.stage = target
        elif kind == ActionType.ADD_TAG:
            if not contact:
                return {"type": kind.value, "status": "skipped", "reason": "no contact"}
            tag = action["tag"].strip()[:40]
            if tag not in (contact.tags or []):
                contact.tags = [*(contact.tags or []), tag]
        return {"type": kind.value, "status": "done"}

    def _log(self, contact: Contact, type_: ActivityType, body: str) -> None:
        contact.activities.append(ContactActivity(type=type_, body=body[:4000], data={"automation": True},
                                                  occurred_at=datetime.now(UTC)))

    # --- Scheduled triggers --------------------------------------------------------------------
    def tick(self, now: datetime | None = None) -> dict[str, int]:
        """Appointment reminders and idle-lead follow-ups. Safe to run from every worker (idempotent)."""
        now = now or datetime.now(UTC)
        stats = {"reminders": 0, "idle": 0}
        rules = self.db.scalars(select(AutomationRule).where(
            AutomationRule.enabled.is_(True),
            AutomationRule.trigger.in_([Trigger.APPOINTMENT_REMINDER, Trigger.CONTACT_IDLE]))).all()
        for rule in rules:
            features, _ = plan_for_business(self.db, rule.business_id)
            if not has_feature(features, Feature.AUTOMATION):
                continue
            if rule.trigger == Trigger.APPOINTMENT_REMINDER:
                stats["reminders"] += self._reminders(rule, now)
            else:
                stats["idle"] += self._idle(rule, now)
        self.db.commit()
        return stats

    def _reminders(self, rule: AutomationRule, now: datetime) -> int:
        from app.services.booking_service import BookingService  # local import: avoid a cycle

        horizon = now + timedelta(hours=int(rule.config["hours_before"]))
        appts = self.db.scalars(select(Appointment).where(
            Appointment.business_id == rule.business_id, Appointment.status == AppointmentStatus.CONFIRMED,
            Appointment.starts_at > now, Appointment.starts_at <= horizon)).all()
        booking = BookingService(self.db, self.settings)
        row = self.db.get(BookingSettings, rule.business_id) or booking.settings_for(rule.business_id)
        count = 0
        for appt in appts:
            context: dict[str, Any] = {"appointment": booking.appointment_context(appt, row)}
            if appt.contact_id and (contact := self.db.get(Contact, appt.contact_id)):
                context["contact"] = contact_context(contact)
            if matches(rule.conditions, context) and self._execute(rule, "appointment", str(appt.id), context):
                count += 1
        return count

    def _idle(self, rule: AutomationRule, now: datetime) -> int:
        cutoff = now - timedelta(days=int(rule.config["idle_days"]))
        contacts = self.db.scalars(select(Contact).where(
            Contact.business_id == rule.business_id, Contact.stage.in_(OPEN_STAGES),
            Contact.last_activity_at.is_not(None), Contact.last_activity_at < cutoff).limit(500)).all()
        count = 0
        for contact in contacts:
            context = {"contact": contact_context(contact),
                       # one follow-up per quiet period: a new touch starts a new period
                       "idempotency_suffix": contact.last_activity_at.isoformat()}
            if matches(rule.conditions, context) and self._execute(rule, "contact", str(contact.id), context):
                count += 1
        return count
