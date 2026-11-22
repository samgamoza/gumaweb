"""Online booking (14 Business tier: booking; 12 AI Receptionist: appointment_booking groundwork)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import generate_url_token, hash_token
from app.domains.billing.entitlements import Feature, has_feature
from app.domains.booking.availability import BookingRules, available_slots, is_bookable, validate_rules
from app.domains.booking.enums import BLOCKING_STATUSES, AppointmentStatus
from app.domains.crm.enums import ActivityType, ContactSource
from app.domains.website_factory.enums import WebsiteStatus
from app.models import Appointment, BookingSettings, Business, Website
from app.repositories.repositories import WebsiteRepository
from app.services.crm_service import CrmService
from app.services.entitlements import plan_for_business, refresh_site
from app.services.notifications import EmailMessage
from app.services.providers import providers
from app.services.support import Actor, EventType, record_event

OWNER_ACTIONS = {
    "confirm": (AppointmentStatus.CONFIRMED, (AppointmentStatus.PENDING,)),
    "cancel": (AppointmentStatus.CANCELLED, BLOCKING_STATUSES),
    "complete": (AppointmentStatus.COMPLETED, (AppointmentStatus.CONFIRMED,)),
    "no_show": (AppointmentStatus.NO_SHOW, (AppointmentStatus.CONFIRMED,)),
}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)  # SQLite returns naive UTC


class BookingService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.crm = CrmService(db, settings)

    # --- Settings (owner) --------------------------------------------------------------------
    def settings_for(self, business_id: uuid.UUID, lock: bool = False) -> BookingSettings:
        if lock:  # serializes concurrent bookings for one business (row lock on PostgreSQL)
            row = self.db.scalar(select(BookingSettings).where(BookingSettings.business_id == business_id)
                                 .with_for_update())
        else:
            row = self.db.get(BookingSettings, business_id)
        if row is None:
            row = BookingSettings(business_id=business_id)
            self.db.add(row)
            self.db.flush()
        return row

    @staticmethod
    def rules(row: BookingSettings) -> BookingRules:
        return BookingRules(timezone=row.timezone, slot_minutes=row.slot_minutes, buffer_minutes=row.buffer_minutes,
                            lead_time_hours=row.lead_time_hours, max_days_ahead=row.max_days_ahead,
                            weekly_hours=row.weekly_hours)

    def update_settings(self, business: Business, changes: dict[str, Any], actor: Actor) -> BookingSettings:
        row = self.settings_for(business.id)
        before = (row.enabled, list(row.services))
        for field, value in changes.items():
            setattr(row, field, value)
        validate_rules(self.rules(row))
        names = [s["name"].strip().lower() for s in row.services]
        if len(names) != len(set(names)):
            raise ValidationFailedError("Service names must be unique")
        if row.enabled and not row.services:
            raise ValidationFailedError("Add at least one bookable service before enabling booking")
        if (row.enabled, list(row.services)) != before:
            refresh_site(self.db, self.settings, business.id, actor)
        self.db.commit()
        return row

    # --- Public booking ----------------------------------------------------------------------
    def _bookable_site(self, subdomain: str) -> tuple[Website, BookingSettings]:
        website = WebsiteRepository(self.db).by_subdomain(subdomain)
        if website is None or website.status != WebsiteStatus.PUBLISHED:
            raise NotFoundError("Site not found")
        row = self.db.get(BookingSettings, website.business_id)
        features, _ = plan_for_business(self.db, website.business_id)
        if row is None or not row.enabled or not has_feature(features, Feature.BOOKING):
            raise NotFoundError("Online booking is not available for this business")
        return website, row

    def _service(self, row: BookingSettings, name: str) -> dict[str, Any]:
        service = next((s for s in row.services if s["name"].lower() == name.strip().lower()), None)
        if service is None:
            raise ValidationFailedError("Unknown service")
        return service

    def _busy(self, business_id: uuid.UUID, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        rows = self.db.execute(
            select(Appointment.starts_at, Appointment.ends_at).where(
                Appointment.business_id == business_id, Appointment.status.in_(BLOCKING_STATUSES),
                Appointment.starts_at < end, Appointment.ends_at > start)
        ).all()
        return [(_aware(s), _aware(e)) for s, e in rows]

    def public_info(self, subdomain: str) -> dict[str, Any]:
        website, row = self._bookable_site(subdomain)
        return {"business_name": website.business.name, "timezone": row.timezone,
                "services": row.services, "max_days_ahead": row.max_days_ahead}

    def slots(self, subdomain: str, day: date, service_name: str, now: datetime | None = None) -> list[datetime]:
        website, row = self._bookable_site(subdomain)
        service = self._service(row, service_name)
        rules = self.rules(row)
        day_start = datetime.combine(day, datetime.min.time(), rules.tz)
        busy = self._busy(website.business_id, day_start - timedelta(hours=12), day_start + timedelta(hours=36))
        return available_slots(rules, day, int(service["duration_minutes"]), busy, now or datetime.now(UTC))

    def book(self, subdomain: str, data: dict[str, Any], now: datetime | None = None) -> tuple[Appointment, str]:
        now = now or datetime.now(UTC)
        website, _ = self._bookable_site(subdomain)
        row = self.settings_for(website.business_id, lock=True)
        service = self._service(row, data["service"])
        start: datetime = data["start"]
        duration = int(service["duration_minutes"])
        end = start + timedelta(minutes=duration)
        busy = self._busy(website.business_id, start - timedelta(hours=12), end + timedelta(hours=12))
        if not is_bookable(self.rules(row), start, duration, busy, now):
            raise ConflictError("That time is no longer available. Please pick another slot.", code="slot_taken")

        contact = self.crm.capture(
            website.business_id, name=data["name"], email=data.get("email"), phone=data.get("phone"),
            source=ContactSource.BOOKING, activity=ActivityType.BOOKING,
            body=f"Booked {service['name']} for {start.astimezone(self.rules(row).tz):%a %d %b %Y %I:%M %p}",
            data={"service": service["name"], "starts_at": start.isoformat()},
        )
        token = generate_url_token()
        appointment = Appointment(
            business_id=website.business_id, contact_id=contact.id, service_name=service["name"],
            starts_at=start.astimezone(UTC), ends_at=end.astimezone(UTC),
            status=AppointmentStatus.CONFIRMED if row.auto_confirm else AppointmentStatus.PENDING,
            customer_name=data["name"], customer_email=contact.email, customer_phone=contact.phone,
            notes=data.get("notes"), manage_token_hash=hash_token(token),
        )
        try:
            with self.db.begin_nested():
                self.db.add(appointment)
        except IntegrityError as exc:  # unique (business, start) among active bookings
            raise ConflictError("That time is no longer available. Please pick another slot.",
                                code="slot_taken") from exc
        record_event(self.db, EventType.APPOINTMENT_BOOKED, "appointment", appointment.id,
                     {"business_id": str(website.business_id), "status": appointment.status.value})
        self.db.commit()
        self._notify_booked(website, row, appointment, token)
        return appointment, token

    def _local(self, row: BookingSettings, dt: datetime) -> str:
        return f"{_aware(dt).astimezone(self.rules(row).tz):%A, %d %B %Y at %I:%M %p}"

    def _notify_booked(self, website: Website, row: BookingSettings, appt: Appointment, token: str) -> None:
        business = website.business
        when = self._local(row, appt.starts_at)
        manage = f"{self.settings.frontend_url.rstrip('/')}/booking/{token}"
        state = "is confirmed" if appt.status == AppointmentStatus.CONFIRMED else "was received and awaits confirmation"
        if appt.customer_email:
            providers.email.send(EmailMessage(
                to=appt.customer_email, subject=f"Your {appt.service_name} booking with {business.name}",
                text=f"Hi {appt.customer_name},\n\nYour booking for {appt.service_name} on {when} {state}.\n\n"
                     f"View or cancel: {manage}\n\n{business.name}",
            ))
        owner_email = business.email
        if owner_email:
            providers.email.send(EmailMessage(
                to=owner_email, subject=f"New booking: {appt.service_name} on {when}",
                text=f"{appt.customer_name} booked {appt.service_name} on {when}.\n"
                     f"Contact: {appt.customer_email or '-'} / {appt.customer_phone or '-'}\n"
                     f"Notes: {appt.notes or '-'}",
            ))

    def by_token(self, token: str) -> Appointment:
        appt = self.db.scalar(select(Appointment).where(Appointment.manage_token_hash == hash_token(token)))
        if appt is None:
            raise NotFoundError("Booking not found")
        return appt

    def cancel_by_token(self, token: str) -> Appointment:
        appt = self.by_token(token)
        if appt.status not in BLOCKING_STATUSES:
            raise ConflictError(f"This booking is already {appt.status.value}")
        if _aware(appt.starts_at) <= datetime.now(UTC):
            raise ConflictError("Past bookings cannot be cancelled online")
        appt.status = AppointmentStatus.CANCELLED
        appt.cancelled_at = datetime.now(UTC)
        if appt.contact_id:
            contact = self.crm.find(appt.business_id, appt.customer_email, appt.customer_phone)
            if contact:
                self.crm._log(contact, ActivityType.BOOKING, f"Cancelled {appt.service_name}", {}, None)
        self.db.commit()
        return appt

    def summary(self, appt: Appointment) -> dict[str, Any]:
        row = self.settings_for(appt.business_id)
        business = self.db.get(Business, appt.business_id)
        return {"business_name": business.name if business else "", "service": appt.service_name,
                "when": self._local(row, appt.starts_at), "status": appt.status.value,
                "cancellable": appt.status in BLOCKING_STATUSES and _aware(appt.starts_at) > datetime.now(UTC)}

    # --- Owner -------------------------------------------------------------------------------
    def appointments(self, business_id: uuid.UUID, start: datetime | None, end: datetime | None,
                     status: AppointmentStatus | None) -> Sequence[Appointment]:
        stmt = select(Appointment).where(Appointment.business_id == business_id)
        if start:
            stmt = stmt.where(Appointment.starts_at >= start)
        if end:
            stmt = stmt.where(Appointment.starts_at < end)
        if status:
            stmt = stmt.where(Appointment.status == status)
        return self.db.scalars(stmt.order_by(Appointment.starts_at).limit(500)).all()

    def owner_action(self, business_id: uuid.UUID, appointment_id: uuid.UUID, action: str) -> Appointment:
        appt = self.db.get(Appointment, appointment_id)
        if appt is None or appt.business_id != business_id:
            raise NotFoundError("Appointment not found")
        if action not in OWNER_ACTIONS:
            raise ValidationFailedError(f"Unknown action '{action}'")
        target, allowed_from = OWNER_ACTIONS[action]
        if appt.status not in allowed_from:
            raise ConflictError(f"Cannot {action} a {appt.status.value} appointment")
        appt.status = target
        if target == AppointmentStatus.CANCELLED:
            appt.cancelled_at = datetime.now(UTC)
        self.db.commit()
        if appt.customer_email and target in (AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED):
            row = self.settings_for(business_id)
            business = self.db.get(Business, business_id)
            providers.email.send(EmailMessage(
                to=appt.customer_email,
                subject=f"Your booking with {business.name if business else 'us'} was {target.value}",
                text=f"Hi {appt.customer_name},\n\nYour {appt.service_name} booking on "
                     f"{self._local(row, appt.starts_at)} was {target.value}.",
            ))
        return appt
