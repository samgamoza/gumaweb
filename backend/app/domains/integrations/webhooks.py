"""Guma OS integration layer: signed outbound webhooks, API key format, SSRF-safe URLs."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from app.core.exceptions import ValidationFailedError

API_KEY_PREFIX = "gw_live_"


class WebhookEvent(StrEnum):
    LEAD_CAPTURED = "lead.captured"
    LEAD_HOT = "lead.hot"
    CONTACT_STAGE_CHANGED = "contact.stage_changed"
    APPOINTMENT_BOOKED = "appointment.booked"
    APPOINTMENT_CANCELLED = "appointment.cancelled"
    CALL_COMPLETED = "call.completed"


def generate_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def endpoint_secret(server_key: str, endpoint_id: str, version: int) -> str:
    """Derived, never stored: HMAC(server key, endpoint id + version). Rotating = bumping the version."""
    digest = hmac.new(server_key.encode(), f"webhook:{endpoint_id}:{version}".encode(), hashlib.sha256).hexdigest()
    return f"whsec_{digest[:40]}"


def sign(secret: str, body: bytes, timestamp: int | None = None) -> str:
    """`GumaWeb-Signature: t=<unix>,v1=<hex hmac-sha256 of "<t>.<body>">` (replay-resistant via timestamp)."""
    ts = timestamp or int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify(secret: str, body: bytes, header: str, tolerance_seconds: int = 300, now: int | None = None) -> bool:
    """Reference verifier for receivers (also used in tests)."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs((now or int(time.time())) - ts) > tolerance_seconds:
        return False
    expected = sign(secret, body, ts).split("v1=")[1]
    return hmac.compare_digest(expected, parts.get("v1", ""))


def encode_payload(event_type: str, data: dict[str, Any], delivery_id: str) -> bytes:
    """`event_type` is a WebhookEvent value, or "ping" for test deliveries."""
    return json.dumps({"id": delivery_id, "type": event_type, "created": int(time.time()), "data": data},
                      default=str, separators=(",", ":")).encode()


def _addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address] | None:
    try:
        return [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, None)]
    except socket.gaierror:
        return None


def _is_private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def _never_allowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # Cloud metadata services (169.254.169.254 is link-local; AWS's IPv6 endpoint fd00:ec2::254 is ULA) and
    # unspecified/multicast addresses are never legitimate receivers, even in local development.
    return ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip == ipaddress.ip_address("fd00:ec2::254")


def validate_webhook_url(url: str, *, allow_private: bool, require_https: bool) -> str:
    """Block SSRF: webhook targets may not point into our own network (metadata service, databases...)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise ValidationFailedError("Webhook URL must be an http(s) URL")
    if require_https and parsed.scheme != "https":
        raise ValidationFailedError("Webhook URL must use https")
    if parsed.username or parsed.password:
        raise ValidationFailedError("Webhook URL must not contain credentials")
    addresses = _addresses(parsed.hostname)
    if not addresses:
        raise ValidationFailedError("Webhook URL host does not resolve")
    # allow_private (local development only) opens LAN/loopback, never metadata or link-local targets.
    if any(_never_allowed(ip) for ip in addresses) or (not allow_private and any(_is_private(ip) for ip in addresses)):
        raise ValidationFailedError("Webhook URL must point to a public internet address")
    return url
