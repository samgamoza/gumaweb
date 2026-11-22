"""Phase 5 (Digital Presence Factory) aggregates: presence kits, custom domains, business email."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.domains.presence.enums import DomainStatus, MailboxKind


class PresenceKit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Social kit, Google Business pack and SEO profile for one business, rebuilt on every publish.
    Copy is stored; images are rendered on first request and cached per kit version (`rendered`)."""

    __tablename__ = "presence_kits"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    website_version: Mapped[int | None] = mapped_column(Integer)
    brand: Mapped[dict[str, Any]] = mapped_column(default=dict)
    social: Mapped[dict[str, Any]] = mapped_column(default=dict)
    google: Mapped[dict[str, Any]] = mapped_column(default=dict)
    seo: Mapped[dict[str, Any]] = mapped_column(default=dict)
    rendered: Mapped[dict[str, Any]] = mapped_column(default=dict)  # asset name -> storage key (this version)
    checklist: Mapped[dict[str, Any]] = mapped_column(default=dict)  # Google Business step -> done timestamp
    generated_at: Mapped[datetime | None]


class CustomDomain(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An owner's own domain, proven by a TXT record at _gumaweb.<domain>. Used for the website and email."""

    __tablename__ = "custom_domains"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    domain: Mapped[str] = mapped_column(String(253), unique=True)  # lowercase ASCII (IDNA)
    status: Mapped[DomainStatus] = mapped_column(enum_type(DomainStatus), default=DomainStatus.PENDING)
    verification_token: Mapped[str] = mapped_column(String(64))
    verified_at: Mapped[datetime | None]
    last_checked_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(String(500))
    serve_website: Mapped[bool] = mapped_column(Boolean, default=False)


class MailDomain(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Business email enabled on a verified domain. The mail server (Stalwart) generates and rotates the
    DKIM keys and reports the DNS records it needs; we cache those records for the owner."""

    __tablename__ = "mail_domains"

    domain_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("custom_domains.id", ondelete="CASCADE"), unique=True)
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    provider_ref: Mapped[str] = mapped_column(String(64))  # mail server's domain id
    dns_records: Mapped[list[Any]] = mapped_column(default=list)
    # dns_pending (records not all found yet) | active | suspended (plan no longer includes email)
    status: Mapped[str] = mapped_column(String(16), default="dns_pending")
    dns_checked_at: Mapped[datetime | None]
    dns_missing: Mapped[list[Any]] = mapped_column(default=list)


class Mailbox(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mailboxes"
    __table_args__ = (UniqueConstraint("mail_domain_id", "local_part", name="uq_mailboxes_domain_local_part"),)

    mail_domain_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mail_domains.id", ondelete="CASCADE"),
                                                      index=True)
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    local_part: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str | None] = mapped_column(String(120))
    kind: Mapped[MailboxKind] = mapped_column(enum_type(MailboxKind), default=MailboxKind.MAILBOX)
    forward_to: Mapped[list[Any]] = mapped_column(default=list)
    quota_mb: Mapped[int] = mapped_column(Integer, default=1024)
    provider_ref: Mapped[str] = mapped_column(String(64))  # mail server's account / mailing-list id
