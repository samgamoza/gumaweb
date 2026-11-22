from enum import StrEnum


class AppointmentStatus(StrEnum):
    PENDING = "pending"  # awaiting owner confirmation (auto_confirm off)
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


# Statuses that occupy a time slot.
BLOCKING_STATUSES = (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)
