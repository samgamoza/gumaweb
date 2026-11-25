"""SSRF-hardened fetch. Ported from guma_os `safe-fetch.test.ts` (16 scenarios) plus the tightened cases.

No real network: DNS goes through an injected resolver and HTTP through httpx.MockTransport. Every
scenario maps to a concrete SSRF vector, so keep them all when refactoring.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable

import httpx
import pytest

from app.core.net import (
    UnsafeUrlError,
    is_never_allowed,
    is_private_address,
    public_address_for,
    safe_fetch,
)

PUBLIC = "93.184.216.34"


def resolver_to(*addresses: str) -> Callable[[str], list]:
    return lambda host: [ipaddress.ip_address(a) for a in addresses]


def no_dns(host: str) -> list:
    raise AssertionError(f"DNS must not be consulted for {host}")


def client_with(handler: Callable[[httpx.Request], httpx.Response]) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(record)), seen


def never_called(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"must not connect: {request.url}")


# --- protocol and host safety ---------------------------------------------------------------------


def test_rejects_non_http_scheme_before_connecting():
    client, seen = client_with(never_called)
    with pytest.raises(UnsafeUrlError):
        safe_fetch("file:///etc/passwd", client=client, resolver=no_dns)
    assert seen == []


def test_rejects_literal_loopback_without_dns():
    client, seen = client_with(never_called)
    with pytest.raises(UnsafeUrlError):
        safe_fetch("http://127.0.0.1/", client=client, resolver=no_dns)
    assert seen == []


def test_rejects_literal_cloud_metadata_address():
    client, _ = client_with(never_called)
    with pytest.raises(UnsafeUrlError):
        safe_fetch("http://169.254.169.254/latest/meta-data/", client=client, resolver=no_dns)


@pytest.mark.parametrize("url", ["http://localhost:8080/", "http://api.localhost/"])
def test_rejects_localhost_names(url):
    client, _ = client_with(never_called)
    with pytest.raises(UnsafeUrlError):
        safe_fetch(url, client=client, resolver=no_dns)


@pytest.mark.parametrize("url", ["http://10.0.0.5/", "http://172.20.0.5/", "http://192.168.1.5/"])
def test_rejects_rfc1918_literals(url):
    client, _ = client_with(never_called)
    with pytest.raises(UnsafeUrlError):
        safe_fetch(url, client=client, resolver=no_dns)


def test_allows_address_just_outside_private_range():
    client, _ = client_with(lambda r: httpx.Response(200, text="ok"))
    result = safe_fetch("http://public-looking.example.com/", client=client, resolver=resolver_to("172.32.0.1"))
    assert result.ok


def test_rejects_public_name_resolving_to_private_address_dns_rebinding_vector():
    client, seen = client_with(never_called)
    with pytest.raises(UnsafeUrlError):
        safe_fetch("http://looks-public.example.com/", client=client, resolver=resolver_to("169.254.169.254"))
    assert seen == []


def test_rejects_when_any_resolved_address_is_private():
    client, seen = client_with(never_called)
    with pytest.raises(UnsafeUrlError):
        safe_fetch("http://mixed.example.com/", client=client, resolver=resolver_to(PUBLIC, "10.0.0.1"))
    assert seen == []


def test_rejects_when_dns_fails():
    client, _ = client_with(never_called)
    with pytest.raises(UnsafeUrlError):
        safe_fetch("http://does-not-resolve.invalid/", client=client, resolver=lambda host: None)


def test_allows_public_address():
    client, _ = client_with(lambda r: httpx.Response(200, text="hello"))
    result = safe_fetch("http://public.example.com/", client=client, resolver=resolver_to(PUBLIC))
    assert result.ok and result.status == 200 and result.text == "hello"


@pytest.mark.parametrize("url", ["http://[::1]/", "http://[fe80::1]/", "http://[fd00::1]/"])
def test_rejects_ipv6_loopback_link_local_and_unique_local(url):
    client, _ = client_with(never_called)
    with pytest.raises(UnsafeUrlError):
        safe_fetch(url, client=client, resolver=no_dns)


def test_rejects_ipv4_mapped_ipv6_loopback():
    client, _ = client_with(never_called)
    with pytest.raises(UnsafeUrlError):
        safe_fetch("http://[::ffff:127.0.0.1]/", client=client, resolver=no_dns)


def test_rejects_cgnat_shared_address_space():
    client, _ = client_with(never_called)
    with pytest.raises(UnsafeUrlError):
        safe_fetch("http://carrier.example.com/", client=client, resolver=resolver_to("100.64.0.1"))


def test_rejects_credentials_in_url():
    client, _ = client_with(never_called)
    with pytest.raises(UnsafeUrlError):
        safe_fetch("http://user:pw@public.example.com/", client=client, resolver=resolver_to(PUBLIC))


def test_non_ok_status_is_a_result_not_an_error():
    client, _ = client_with(lambda r: httpx.Response(404, text="nope"))
    result = safe_fetch("http://public.example.com/missing", client=client, resolver=resolver_to(PUBLIC))
    assert not result.ok and result.status == 404


# --- DNS pinning (new: closes the check-then-resolve-again gap) ------------------------------------


def test_connects_to_the_validated_address_with_original_host_and_sni():
    client, seen = client_with(lambda r: httpx.Response(200, text="ok"))
    safe_fetch("https://shop.example.com:8443/contact?x=1", client=client, resolver=resolver_to(PUBLIC))
    request = seen[0]
    assert request.url.host == PUBLIC
    assert request.url.port == 8443
    assert request.url.path == "/contact" and request.url.query == b"x=1"
    assert request.headers["host"] == "shop.example.com:8443"
    assert request.extensions["sni_hostname"] == "shop.example.com"


def test_pins_ipv6_addresses_in_brackets():
    client, seen = client_with(lambda r: httpx.Response(200, text="ok"))
    safe_fetch("http://v6.example.com/", client=client, resolver=resolver_to("2606:2800:220:1::1"))
    assert seen[0].url.host == "2606:2800:220:1::1"
    assert seen[0].headers["host"] == "v6.example.com"


# --- redirects ------------------------------------------------------------------------------------


def test_follows_redirect_to_public_host_and_revalidates():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "step1.example.com":
            return httpx.Response(302, headers={"location": "http://step2.example.com/"})
        return httpx.Response(200, text="landed")

    client, seen = client_with(handler)
    result = safe_fetch("http://step1.example.com/", client=client, resolver=resolver_to(PUBLIC))
    assert result.text == "landed"
    assert result.url == "http://step2.example.com/"
    assert len(seen) == 2


def test_rejects_redirect_to_private_address_redirect_bypass():
    client, seen = client_with(
        lambda r: httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
    )
    with pytest.raises(UnsafeUrlError):
        safe_fetch("http://public-entry.example.com/", client=client, resolver=resolver_to(PUBLIC))
    assert len(seen) == 1  # never requests the malicious target


def test_redirect_without_location_is_a_non_ok_result():
    client, _ = client_with(lambda r: httpx.Response(302))
    result = safe_fetch("http://example.com/", client=client, resolver=resolver_to(PUBLIC))
    assert not result.ok and result.status == 302


def test_resolves_relative_redirects_against_the_original_host():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, text="moved")

    client, seen = client_with(handler)
    result = safe_fetch("http://example.com/old", client=client, resolver=resolver_to(PUBLIC))
    assert result.url == "http://example.com/new"
    assert seen[1].headers["host"] == "example.com"


def test_caps_the_redirect_chain():
    def handler(request: httpx.Request) -> httpx.Response:
        n = int(request.url.path.strip("/") or 0)
        return httpx.Response(302, headers={"location": f"/{n + 1}"})

    client, seen = client_with(handler)
    with pytest.raises(UnsafeUrlError):
        safe_fetch("http://example.com/0", client=client, resolver=resolver_to(PUBLIC), max_redirects=3)
    assert len(seen) == 4


# --- size cap and timeout -------------------------------------------------------------------------


def test_truncates_body_over_max_bytes():
    client, _ = client_with(lambda r: httpx.Response(200, content=b"x" * 5000))
    result = safe_fetch("http://example.com/", client=client, resolver=resolver_to(PUBLIC), max_bytes=2000)
    assert len(result.text) == 2000
    assert result.truncated


def test_small_body_is_not_marked_truncated():
    client, _ = client_with(lambda r: httpx.Response(200, content=b"small"))
    result = safe_fetch("http://example.com/", client=client, resolver=resolver_to(PUBLIC))
    assert result.text == "small" and not result.truncated


def test_timeout_raises_transport_error_rather_than_hanging():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client, _ = client_with(handler)
    with pytest.raises(httpx.TimeoutException):
        safe_fetch("http://slow.example.com/", client=client, resolver=resolver_to(PUBLIC), timeout=0.01)


# --- shared classifier (also used by webhook URL validation) --------------------------------------


@pytest.mark.parametrize(
    ("address", "private"),
    [
        (PUBLIC, False),
        ("8.8.8.8", False),
        ("10.1.2.3", True),
        ("127.0.0.1", True),
        ("169.254.169.254", True),
        ("100.64.0.1", True),
        ("0.0.0.0", True),
        ("::1", True),
        ("::ffff:10.0.0.1", True),
        ("2606:2800:220:1::1", False),
    ],
)
def test_is_private_address(address, private):
    assert is_private_address(ipaddress.ip_address(address)) is private


@pytest.mark.parametrize(
    "address", ["169.254.169.254", "fd00:ec2::254", "0.0.0.0", "224.0.0.1", "::ffff:169.254.169.254"]
)
def test_never_allowed_targets(address):
    assert is_never_allowed(ipaddress.ip_address(address))


def test_public_address_for_returns_the_first_validated_answer():
    assert str(public_address_for("example.com", resolver_to(PUBLIC, "8.8.8.8"))) == PUBLIC
