"""DNS lookups for custom domains and business email (dnspython). Tests replace `providers.dns`."""

from __future__ import annotations

from typing import Protocol

import dns.exception
import dns.resolver


class DnsResolver(Protocol):
    def txt(self, name: str) -> list[str]: ...

    def mx(self, name: str) -> list[tuple[int, str]]: ...

    def cname(self, name: str) -> list[str]: ...

    def a(self, name: str) -> list[str]: ...


class LiveDnsResolver:
    """Queries the system resolver. Missing names return [] (not an error): the owner may not have
    added the record yet. Timeouts and server failures raise, so callers can say "try again"."""

    def __init__(self, timeout: float = 5.0) -> None:
        self.resolver = dns.resolver.Resolver()
        self.resolver.lifetime = timeout

    def _query(self, name: str, rdtype: str) -> list:
        try:
            return list(self.resolver.resolve(name, rdtype))
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            return []

    def txt(self, name: str) -> list[str]:
        return [b"".join(r.strings).decode("utf-8", "replace") for r in self._query(name, "TXT")]

    def mx(self, name: str) -> list[tuple[int, str]]:
        return sorted((r.preference, r.exchange.to_text().rstrip(".").lower()) for r in self._query(name, "MX"))

    def cname(self, name: str) -> list[str]:
        return [r.target.to_text().rstrip(".").lower() for r in self._query(name, "CNAME")]

    def a(self, name: str) -> list[str]:
        return [r.address for r in self._query(name, "A")]


DnsError = dns.exception.DNSException
