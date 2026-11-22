"""Outbound notifications. Local-first: SMTP to a self-hosted MTA (Postfix,
Mailpit in dev); SMS gateway adapter is a Phase 2 seam."""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from typing import Protocol

from app.core.config import Settings

logger = logging.getLogger("gumaweb.notifications")


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str | None = None


class EmailSender(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class SmsSender(Protocol):
    def send(self, phone: str, text: str) -> None: ...


class ConsoleEmailSender:
    def send(self, message: EmailMessage) -> None:
        logger.info("EMAIL to=%s subject=%r\n%s", message.to, message.subject, message.text)


class MemoryEmailSender:
    """Test double that records messages."""

    def __init__(self) -> None:
        self.outbox: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.outbox.append(message)


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, message: EmailMessage) -> None:
        mime = MimeMessage()
        mime["From"] = self.settings.email_from
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.text)
        if message.html:
            mime.add_alternative(message.html, subtype="html")
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as smtp:
            if self.settings.smtp_use_tls:
                smtp.starttls()
            if self.settings.smtp_user and self.settings.smtp_password:
                smtp.login(self.settings.smtp_user, self.settings.smtp_password)
            smtp.send_message(mime)


class ConsoleSmsSender:
    def send(self, phone: str, text: str) -> None:
        logger.info("SMS to=%s: %s", phone, text)


class MemorySmsSender:
    def __init__(self) -> None:
        self.outbox: list[tuple[str, str]] = []

    def send(self, phone: str, text: str) -> None:
        self.outbox.append((phone, text))
