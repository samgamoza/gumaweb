from __future__ import annotations

from enum import StrEnum


class DomainStatus(StrEnum):
    PENDING = "pending"  # waiting for the owner's DNS verification record
    VERIFIED = "verified"
    FAILED = "failed"  # verification record disappeared after being verified


class MailboxKind(StrEnum):
    MAILBOX = "mailbox"  # a real inbox with a password
    FORWARD = "forward"  # an alias that forwards to other addresses
