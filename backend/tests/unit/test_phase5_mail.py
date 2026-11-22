import json

import httpx
import pytest

from app.core.exceptions import ConflictError, ValidationFailedError
from app.domains.presence.mail import missing_records, normalize_local_part, parse_zone
from app.services.mail_provider import DisabledMailProvider, EmailUnavailable, StalwartMailProvider

# Captured verbatim from Stalwart 1.1.1 (x:Domain/get dnsZoneFile) during the live probe.
REAL_ZONE = (
    'v1-ed25519-20261122._domainkey.bellavista-demo.ph. IN TXT "v=DKIM1; k=ed25519; h=sha256; '
    'p=vXQaBeTSpa3bZjd1yjbocD+42T6IiOUb+SDKyS7sSw4="\n'
    'bellavista-demo.ph. IN TXT "v=spf1 mx -all"\n'
    "bellavista-demo.ph. IN MX 10 mail.gumaweb.test.\n"
    '_dmarc.bellavista-demo.ph. IN TXT "v=DMARC1; p=reject; rua=mailto:postmaster@bellavista-demo.ph"\n'
    "_imaps._tcp.bellavista-demo.ph. IN SRV 0 1 993 mail.gumaweb.test.\n"
    "mta-sts.bellavista-demo.ph. IN CNAME mail.gumaweb.test.\n"
    "autoconfig.bellavista-demo.ph. IN CNAME mail.gumaweb.test.\n"
)


def test_parse_real_stalwart_zone():
    records = {(r["type"], r["name"]): r for r in parse_zone(REAL_ZONE)}
    mx = records[("MX", "bellavista-demo.ph")]
    assert mx["value"] == "mail.gumaweb.test" and mx["priority"] == 10 and mx["required"]
    dkim = records[("TXT", "v1-ed25519-20261122._domainkey.bellavista-demo.ph")]
    assert dkim["value"].startswith("v=DKIM1; k=ed25519") and '"' not in dkim["value"] and dkim["required"]
    assert records[("TXT", "_dmarc.bellavista-demo.ph")]["required"]
    assert records[("CNAME", "autoconfig.bellavista-demo.ph")]["required"] is False
    assert records[("SRV", "_imaps._tcp.bellavista-demo.ph")]["value"] == "0 1 993 mail.gumaweb.test"


def test_missing_records_compares_published_dns():
    records = parse_zone(REAL_ZONE)
    published = {("MX", "bellavista-demo.ph"): [(10, "mail.gumaweb.test")],
                 ("TXT", "bellavista-demo.ph"): ["v=spf1 mx -all", "google-site-verification=x"]}
    missing = missing_records(records, lambda t, n: published.get((t, n), []))
    assert missing == ["TXT v1-ed25519-20261122._domainkey.bellavista-demo.ph", "TXT _dmarc.bellavista-demo.ph"]


def test_mailbox_names():
    assert normalize_local_part(" Juan.Cruz ") == "juan.cruz"
    assert normalize_local_part("info@bellavista.ph") == "info"
    for bad in ("postmaster", "a..b", "-x", "x y", "", "ä"):
        with pytest.raises(ValidationFailedError):
            normalize_local_part(bad)


def _stalwart(responses: list[tuple[str, dict]]) -> tuple[StalwartMailProvider, list[dict]]:
    """Replays method responses in order and records the requests."""
    sent: list[dict] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append(body)
        name, result = queue.pop(0)
        return httpx.Response(200, json={"methodResponses": [[name, result, "c"]], "sessionState": "s"})

    client = httpx.Client(base_url="http://stalwart", transport=httpx.MockTransport(handler))
    return StalwartMailProvider("http://stalwart", "admin", "x", client=client), sent


def test_stalwart_adapter_requests_match_the_live_api():
    provider, sent = _stalwart([
        ("x:Domain/query", {"ids": []}),
        ("x:Domain/set", {"created": {"n": {"id": "c"}}}),
        ("x:Account/set", {"created": {"n": {"id": "a"}}}),
        ("x:Account/set", {"notCreated": {"n": {"type": "primaryKeyViolation", "properties": ["email"]}}}),
        ("x:MailingList/set", {"created": {"n": {"id": "b"}}}),
        ("x:DkimSignature/query", {"ids": ["k1", "k2"]}),
        ("x:DkimSignature/set", {"destroyed": ["k1", "k2"]}),
        ("x:Domain/set", {"destroyed": ["c"]}),
    ])
    assert provider.ensure_domain("bellavista-demo.ph") == "c"
    assert provider.create_mailbox("c", "info", "Front desk", "s3cret", 2048) == "a"
    with pytest.raises(ConflictError):
        provider.create_mailbox("c", "info", None, "s3cret", 2048)
    assert provider.create_forward("c", "orders", ["owner@gmail.com"]) == "b"
    provider.delete_domain("c")

    account = sent[2]["methodCalls"][0][1]["create"]["n"]
    assert sent[2]["using"] == ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"]
    assert account["credentials"] == {"0": {"@type": "Password", "secret": "s3cret"}}  # map form, not a list
    assert account["quotas"] == {"maxDiskQuota": 2048 * 1024 * 1024}
    assert sent[4]["methodCalls"][0][1]["create"]["n"]["recipients"] == {"owner@gmail.com": True}
    assert [c["methodCalls"][0][0] for c in sent[-3:]] == ["x:DkimSignature/query", "x:DkimSignature/set",
                                                          "x:Domain/set"]  # keys before the domain


def test_disabled_provider_is_honest():
    with pytest.raises(EmailUnavailable):
        DisabledMailProvider().ensure_domain("x.ph")
