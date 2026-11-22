"""Business email (Professional plan) - NOT YET CONNECTED TO A MAIL SERVER.

Placeholder until the mail-server adapter (Stalwart, via its JMAP management API) is built and
verified live. Every mutating operation answers 503 `business_email_unavailable`, so the portal
never pretends a mailbox exists. Domains (verification, website serving) work independently.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import GumaWebError
from app.models import CustomDomain


class EmailUnavailable(GumaWebError):
    status_code = 503
    code = "business_email_unavailable"


_MESSAGE = "Business email is coming soon: GumaWeb's mail server is not connected yet."


class MailService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def records_for(self, row: CustomDomain) -> list[dict[str, Any]]:
        return []

    def summary(self, row: CustomDomain) -> dict[str, Any] | None:
        return None

    def enable(self, row: CustomDomain) -> None:
        raise EmailUnavailable(_MESSAGE)

    def check_dns(self, row: CustomDomain) -> None:
        raise EmailUnavailable(_MESSAGE)

    def create_mailbox(self, row: CustomDomain, data: dict[str, Any]) -> dict[str, Any]:
        raise EmailUnavailable(_MESSAGE)

    def reset_password(self, row: CustomDomain, mailbox_id: uuid.UUID) -> dict[str, Any]:
        raise EmailUnavailable(_MESSAGE)

    def delete_mailbox(self, row: CustomDomain, mailbox_id: uuid.UUID) -> None:
        raise EmailUnavailable(_MESSAGE)

    def disable_for_domain(self, row: CustomDomain) -> None:
        return None  # nothing provisioned yet

    def enforce_plan(self, business_id: uuid.UUID) -> None:
        return None
