"""Mail server adapters. Stalwart (self-hosted, local-first) via its JMAP management API.

Verified against Stalwart 1.1.1 (stalwartlabs/stalwart:v1). Facts that shaped this adapter:
- Management calls are JMAP methods on POST /jmap/ with capability "urn:stalwart:jmap".
- Domains get DKIM keys automatically; `dnsZoneFile` lists every record to publish.
- Collections are maps keyed by index: credentials {"0": {"@type": "Password", "secret": ...}}.
- Forwarding to outside addresses is a MailingList whose `recipients` is a set {"a@b.ph": true}.
- A domain can only be destroyed after its DkimSignature objects.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from app.core.exceptions import ConflictError, GumaWebError


class MailProviderError(GumaWebError):
    status_code = 502
    code = "mail_server_error"


class EmailUnavailable(GumaWebError):
    status_code = 503
    code = "business_email_unavailable"


class MailProvider(Protocol):
    name: str

    def ensure_domain(self, domain: str) -> str: ...

    def zone(self, domain_ref: str) -> str: ...

    def delete_domain(self, domain_ref: str) -> None: ...

    def create_mailbox(self, domain_ref: str, local_part: str, display_name: str | None, password: str,
                       quota_mb: int) -> str: ...

    def set_password(self, mailbox_ref: str, password: str) -> None: ...

    def delete_mailbox(self, mailbox_ref: str) -> None: ...

    def create_forward(self, domain_ref: str, local_part: str, targets: list[str]) -> str: ...

    def delete_forward(self, forward_ref: str) -> None: ...


class DisabledMailProvider:
    """No mail server configured: business email is honestly unavailable."""

    name = "disabled"

    def _unavailable(self, *_: Any, **__: Any) -> Any:
        raise EmailUnavailable("Business email is not available yet: no mail server is connected.")

    ensure_domain = zone = delete_domain = create_mailbox = set_password = _unavailable
    delete_mailbox = create_forward = delete_forward = _unavailable


class StalwartMailProvider:
    name = "stalwart"
    USING = ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"]

    def __init__(self, base_url: str, username: str, secret: str, timeout: float = 20.0,
                 client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(base_url=base_url.rstrip("/"), auth=(username, secret), timeout=timeout)

    def _call(self, method: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.client.post("/jmap/", json={"using": self.USING, "methodCalls": [[method, args, "c"]]})
        except httpx.HTTPError as exc:
            raise MailProviderError(f"The mail server is unreachable: {exc}") from exc
        if response.status_code != 200:
            raise MailProviderError(f"The mail server answered HTTP {response.status_code}")
        name, result, _ = response.json()["methodResponses"][0]
        if name == "error":
            raise MailProviderError(f"Mail server rejected {method}: {result.get('description') or result['type']}")
        return result

    def _create(self, method: str, obj: dict[str, Any]) -> str:
        result = self._call(method, {"create": {"n": obj}})
        if "n" in (result.get("created") or {}):
            return result["created"]["n"]["id"]
        error = (result.get("notCreated") or {}).get("n", {})
        if error.get("type") == "primaryKeyViolation":
            raise ConflictError("That address already exists")
        raise MailProviderError(f"Mail server could not create it: {error.get('description') or error.get('type')}")

    def _destroy(self, method: str, ids: list[str]) -> None:
        if not ids:
            return
        result = self._call(method, {"destroy": ids})
        failed = {k: v for k, v in (result.get("notDestroyed") or {}).items() if v.get("type") != "notFound"}
        if failed:
            raise MailProviderError(f"Mail server could not delete: {failed}")

    # --- Domains -----------------------------------------------------------------------------
    def ensure_domain(self, domain: str) -> str:
        ids = self._call("x:Domain/query", {"filter": {"name": domain}}).get("ids") or []
        if ids:
            return ids[0]
        return self._create("x:Domain/set", {"name": domain, "description": "GumaWeb customer domain"})

    def zone(self, domain_ref: str) -> str:
        found = self._call("x:Domain/get", {"ids": [domain_ref], "properties": ["dnsZoneFile"]}).get("list") or []
        if not found:
            raise MailProviderError("The mail server no longer knows this domain")
        return found[0].get("dnsZoneFile") or ""

    def delete_domain(self, domain_ref: str) -> None:
        signatures = self._call("x:DkimSignature/query", {"filter": {"domainId": domain_ref}}).get("ids") or []
        self._destroy("x:DkimSignature/set", signatures)  # the domain can't go while keys reference it
        self._destroy("x:Domain/set", [domain_ref])

    # --- Mailboxes and forwards -----------------------------------------------------------------
    def create_mailbox(self, domain_ref: str, local_part: str, display_name: str | None, password: str,
                       quota_mb: int) -> str:
        return self._create("x:Account/set", {
            "@type": "User", "name": local_part, "domainId": domain_ref, "description": display_name,
            "credentials": {"0": {"@type": "Password", "secret": password}},
            "quotas": {"maxDiskQuota": quota_mb * 1024 * 1024},
        })

    def set_password(self, mailbox_ref: str, password: str) -> None:
        result = self._call("x:Account/set", {"update": {mailbox_ref: {
            "credentials": {"0": {"@type": "Password", "secret": password}}}}})
        if mailbox_ref not in (result.get("updated") or {}):
            raise MailProviderError("The mail server could not change the password")

    def delete_mailbox(self, mailbox_ref: str) -> None:
        self._destroy("x:Account/set", [mailbox_ref])

    def create_forward(self, domain_ref: str, local_part: str, targets: list[str]) -> str:
        return self._create("x:MailingList/set", {
            "name": local_part, "domainId": domain_ref, "recipients": {t: True for t in targets}})

    def delete_forward(self, forward_ref: str) -> None:
        self._destroy("x:MailingList/set", [forward_ref])


def bootstrap_stalwart(url: str, recovery_admin: str, recovery_secret: str, *, hostname: str,
                       default_domain: str) -> dict[str, str]:
    """First-run setup of a fresh Stalwart (replaces its web wizard). Uses the STALWART_RECOVERY_ADMIN
    credentials and returns the permanent administrator account, which Stalwart reveals only once."""
    with httpx.Client(base_url=url.rstrip("/"), auth=(recovery_admin, recovery_secret), timeout=30) as client:
        response = client.post("/jmap/", json={"using": StalwartMailProvider.USING, "methodCalls": [[
            "x:Bootstrap/set", {"update": {"singleton": {
                "defaultHostname": hostname, "defaultDomain": default_domain,
                "requestTlsCertificate": not hostname.endswith((".test", ".local", ".localhost")),
                "generateDkimKeys": True,
                "tracer": {"@type": "Stdout", "level": "info", "ansi": False, "multiline": False, "enable": True,
                           "lossy": False, "events": {}, "eventsPolicy": "exclude"},
            }}}, "c"]]})
    response.raise_for_status()
    name, result, _ = response.json()["methodResponses"][0]
    updated = (result.get("updated") or {}).get("singleton") if name != "error" else None
    if not updated:
        raise MailProviderError(f"Stalwart bootstrap failed: {result}")
    return {"username": updated["username"], "secret": updated["secret"]}
