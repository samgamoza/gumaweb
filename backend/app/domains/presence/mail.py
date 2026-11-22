"""Business email rules: mailbox names and the DNS records the mail server asks owners to publish."""

from __future__ import annotations

import re
import shlex

from app.core.exceptions import ValidationFailedError

_LOCAL_PART = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
# Role addresses that receive abuse/DMARC reports: kept for the platform to route, not owner mailboxes.
RESERVED = {"postmaster", "abuse", "mailer-daemon", "hostmaster", "webmaster"}


def normalize_local_part(raw: str) -> str:
    local = raw.strip().lower()
    if "@" in local:
        local = local.split("@", 1)[0]
    if not _LOCAL_PART.match(local) or ".." in local:
        raise ValidationFailedError("Use letters, numbers, dots, dashes or underscores, like info or juan.cruz")
    if local in RESERVED:
        raise ValidationFailedError(f"{local}@ is reserved for the mail system")
    return local


def _purpose(rtype: str, name: str, value: str) -> tuple[str, bool]:
    """(what it's for, required for mail to work)"""
    if rtype == "MX":
        return "Receives your email", True
    if rtype == "TXT" and value.startswith("v=spf1"):
        return "Lets receivers know our servers may send for you (SPF)", True
    if rtype == "TXT" and "._domainkey." in name:
        return "Signs your outgoing email (DKIM)", True
    if rtype == "TXT" and name.startswith("_dmarc."):
        return "Tells receivers what to do with forged mail (DMARC)", True
    if rtype == "CNAME" and name.split(".", 1)[0] in {"autoconfig", "autodiscover", "ua-auto-config"}:
        return "Lets mail apps set themselves up", False
    if "mta-sts" in name or name.startswith("_smtp._tls."):
        return "Requires encrypted delivery (MTA-STS / TLS reporting)", False
    if rtype == "SRV":
        return "Helps mail and calendar apps find the server", False
    return "Recommended by the mail server", False


def parse_zone(zone: str) -> list[dict]:
    """Parse the mail server's zone snippet ("name. IN TYPE value" lines) into records for the owner."""
    records = []
    for line in zone.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        parts = line.split(None, 3)
        if len(parts) < 4 or parts[1].upper() != "IN":
            continue
        name, rtype, rest = parts[0].rstrip("."), parts[2].upper(), parts[3].strip()
        priority = None
        if rtype == "MX":
            pref, target = rest.split(None, 1)
            priority, value = int(pref), target.rstrip(".")
        elif rtype == "TXT":
            value = "".join(shlex.split(rest))  # joins quoted chunks, removes the quotes
        else:
            value = rest.rstrip(".")
        purpose, required = _purpose(rtype, name, value)
        record = {"type": rtype, "name": name, "value": value, "purpose": purpose, "required": required}
        if priority is not None:
            record["priority"] = priority
        records.append(record)
    return records


def missing_records(records: list[dict], lookup) -> list[str]:
    """Required records not (yet) visible in DNS. `lookup(type, name)` returns published values."""
    missing = []
    for r in records:
        if not r["required"]:
            continue
        found = lookup(r["type"], r["name"])
        if r["type"] == "MX":
            ok = any(host == r["value"].lower() for _, host in found)
        else:
            ok = any(v.replace('" "', "").strip('"') == r["value"] for v in found)
        if not ok:
            missing.append(f"{r['type']} {r['name']}")
    return missing
