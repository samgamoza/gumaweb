"""Infrastructure providers (composition root). Tests replace attributes on `providers`."""

from __future__ import annotations

from app.core.config import get_settings
from app.domains.publishing.renderer import SiteRenderer
from app.domains.publishing.storage import LocalSiteStorage, S3SiteStorage, SiteStorage
from app.services.notifications import (
    ConsoleEmailSender,
    ConsoleSmsSender,
    EmailSender,
    SmsSender,
    SmtpEmailSender,
)


class Providers:
    def __init__(self) -> None:
        self._email: EmailSender | None = None
        self._sms: SmsSender | None = None
        self._storage: SiteStorage | None = None
        self._renderer: SiteRenderer | None = None

    @property
    def email(self) -> EmailSender:
        if self._email is None:
            settings = get_settings()
            self._email = SmtpEmailSender(settings) if settings.email_backend == "smtp" else ConsoleEmailSender()
        return self._email

    @email.setter
    def email(self, value: EmailSender) -> None:
        self._email = value

    @property
    def sms(self) -> SmsSender:
        if self._sms is None:
            self._sms = ConsoleSmsSender()
        return self._sms

    @sms.setter
    def sms(self, value: SmsSender) -> None:
        self._sms = value

    @property
    def storage(self) -> SiteStorage:
        if self._storage is None:
            s = get_settings()
            if s.storage_backend == "s3":
                self._storage = S3SiteStorage(s.s3_bucket, s.s3_endpoint_url, s.s3_access_key,
                                              s.s3_secret_key, s.s3_region)
            else:
                s.generated_sites_dir.mkdir(parents=True, exist_ok=True)
                self._storage = LocalSiteStorage(s.generated_sites_dir)
        return self._storage

    @storage.setter
    def storage(self, value: SiteStorage) -> None:
        self._storage = value

    @property
    def renderer(self) -> SiteRenderer:
        if self._renderer is None:
            self._renderer = SiteRenderer(get_settings().templates_dir)
        return self._renderer

    @renderer.setter
    def renderer(self, value: SiteRenderer) -> None:
        self._renderer = value

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]


providers = Providers()
