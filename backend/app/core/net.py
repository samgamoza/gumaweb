"""Outbound network safety: one SSRF policy for every request to a host we do not control.

Two callers today: webhook delivery (`domains/integrations/webhooks.py`, validates a customer-supplied
URL) and crawling discovered business websites (`safe_fetch`). Both use the same address classifier.

`safe_fetch` threats mitigated (ported from guma_os `adapter-maps/src/safe-fetch.ts`, then tightened):

* Non-http(s) schemes and URLs carrying credentials are refused.
* The host is resolved and **every** resolved address is checked; a public-looking name that resolves to
  a private, loopback, link-local (incl. cloud metadata 169.254.169.254), shared (CGNAT), reserved or
  multicast address is refused exactly like a literal one. IPv4-mapped IPv6 is unwrapped first.
* **DNS rebinding:** the connection goes to the address that was just validated, not to a second DNS
  answer. The original hostname is still sent as the HTTP `Host` and as the TLS SNI/certificate name, so
  virtual hosting and certificate verification work normally.
* Redirects are followed manually and every hop is re-validated; the chain is capped.
* The body is streamed with a hard byte cap (a truncated body is returned, never an unbounded read).

Non-goal: this protects a public-site crawler from being pointed at internal infrastructure. It is not a
general-purpose sandbox for arbitrary attacker-chosen requests.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str], list[IPAddress] | None]

DEFAULT_TIMEOUT_SECONDS = 6.0
DEFAULT_MAX_BYTES = 2_000_000  # a business "about"/"contact" page has no legitimate reason to exceed this
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_USER_AGENT = "GumaWebBot/1.0 (+https://gumaweb.io/bot)"

_AWS_IPV6_METADATA = ipaddress.ip_address("fd00:ec2::254")


class UnsafeUrlError(Exception):
    """This URL must not be fetched. Crawler callers treat it as a normal non-fatal miss."""


def resolve_addresses(host: str) -> list[IPAddress] | None:
    """Every address `host` resolves to, or None when it does not resolve."""
    try:
        return [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, None)]
    except (socket.gaierror, UnicodeError, ValueError):
        return None


def _unwrap(ip: IPAddress) -> IPAddress:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def is_private_address(ip: IPAddress) -> bool:
    """Not a public internet address: private, loopback, link-local, shared/CGNAT, reserved or multicast."""
    ip = _unwrap(ip)
    return (not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast)


def is_never_allowed(ip: IPAddress) -> bool:
    """Never a legitimate target, even in local development: metadata services, unspecified, multicast."""
    ip = _unwrap(ip)
    return ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip == _AWS_IPV6_METADATA


def public_address_for(host: str, resolver: Resolver = resolve_addresses) -> IPAddress:
    """Validate `host` and return the address to connect to. Raises UnsafeUrlError if any answer is unsafe."""
    bare = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        literal: IPAddress | None = ipaddress.ip_address(bare)
    except ValueError:
        literal = None
    if literal is not None:
        if is_private_address(literal):
            raise UnsafeUrlError(f"refusing to fetch a non-public address: {bare}")
        return literal
    if bare.lower() == "localhost" or bare.lower().endswith(".localhost"):
        raise UnsafeUrlError("refusing to fetch localhost")
    addresses = resolver(bare)
    if not addresses:
        raise UnsafeUrlError(f"DNS resolution failed for {bare}")
    for ip in addresses:
        if is_private_address(ip):
            raise UnsafeUrlError(f"refusing to fetch {bare}: resolves to a non-public address ({ip})")
    return addresses[0]


@dataclass(frozen=True)
class SafeFetchResult:
    ok: bool
    status: int
    headers: httpx.Headers
    text: str
    url: str  # final URL after redirects
    truncated: bool = False


def _pinned_request(url: str, ip: IPAddress, user_agent: str) -> tuple[str, dict[str, str], dict[str, str]]:
    """Rewrite `url` to connect to `ip`, keeping the original host for Host and TLS SNI."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    ip_text = f"[{ip}]" if isinstance(ip, ipaddress.IPv6Address) else str(ip)
    netloc = f"{ip_text}:{parts.port}" if parts.port else ip_text
    pinned = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
    host_header = f"{host}:{parts.port}" if parts.port else host
    headers = {"Host": host_header, "User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
    extensions = {"sni_hostname": host} if parts.scheme == "https" else {}
    return pinned, headers, extensions


def _read_bounded(response: httpx.Response, max_bytes: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        if total + len(chunk) > max_bytes:
            chunks.append(chunk[: max_bytes - total])
            return b"".join(chunks), True
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks), False


def safe_fetch(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    user_agent: str = DEFAULT_USER_AGENT,
    client: httpx.Client | None = None,
    resolver: Resolver = resolve_addresses,
) -> SafeFetchResult:
    """GET `url` under the SSRF policy above.

    Ordinary HTTP outcomes (404, 500, a redirect with no Location) come back as a result; check `.ok`.
    Raises UnsafeUrlError when the request must not proceed, and httpx.HTTPError on transport failures
    (timeout, TLS, connection refused). Crawler callers treat both as "nothing found here".
    """
    own_client = client is None
    http = client or httpx.Client(timeout=timeout, follow_redirects=False)
    try:
        current = url
        for _hop in range(max_redirects + 1):
            parts = urlsplit(current)
            if parts.scheme not in ("http", "https"):
                raise UnsafeUrlError(f"unsupported scheme: {parts.scheme or '(none)'}")
            if not parts.hostname:
                raise UnsafeUrlError("URL has no host")
            if parts.username or parts.password:
                raise UnsafeUrlError("URL must not contain credentials")
            ip = public_address_for(parts.hostname, resolver)
            pinned, headers, extensions = _pinned_request(current, ip, user_agent)
            request = http.build_request("GET", pinned, headers=headers, extensions=extensions, timeout=timeout)
            response = http.send(request, stream=True, follow_redirects=False)
            try:
                if 300 <= response.status_code < 400:
                    location = response.headers.get("location")
                    if not location:
                        return SafeFetchResult(False, response.status_code, response.headers, "", current)
                    current = urljoin(current, location)  # re-validated at the top of the next hop
                    continue
                body, truncated = _read_bounded(response, max_bytes)
                text = body.decode(response.encoding or "utf-8", errors="replace")
                return SafeFetchResult(response.is_success, response.status_code, response.headers, text, current,
                                       truncated)
            finally:
                response.close()
        raise UnsafeUrlError(f"too many redirects (>{max_redirects}) fetching {url}")
    finally:
        if own_client:
            http.close()
