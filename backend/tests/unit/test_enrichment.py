"""Contact enrichment: extraction, tech signals and tiers (port plan step 4). No network.

Ports the guma_os enrichment.test.ts / domain-signals / rdap / hunter cases; MX checks live in the API
tests because they go through the injectable DNS resolver.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from app.core.net import SafeFetchResult, UnsafeUrlError
from app.domains.enrichment.extract import (
    detect_tech_stack,
    domain_of,
    extract_contacts,
    extract_json_ld_contacts,
    is_plausible_email,
)
from app.domains.enrichment.tiers import (
    RDAP_GUESS_CONFIDENCE,
    EnrichmentResult,
    EnrichmentTarget,
    Found,
    HunterTier,
    RdapTier,
    TierStep,
    WebsiteScrapeTier,
    contact_page_url,
    run_waterfall,
)

# --- extract_contacts -----------------------------------------------------------------------------


def test_finds_mailto_plain_text_and_tel():
    page = """<a href="mailto:Hello@Shop.ph?subject=hi">Email</a> or write sales@shop.ph today.
              <a href="tel:+63 2 8123 4567">Call</a>"""
    found = extract_contacts(page)
    assert found.emails == ["hello@shop.ph", "sales@shop.ph"]
    assert found.phones == ["+63281234567"]


def test_decodes_entities_and_percent_encoding():
    found = extract_contacts('<a href="mailto:info%40bakery.ph">x</a> or orders&#64;bakery.ph')
    assert found.emails == ["info@bakery.ph", "orders@bakery.ph"]


def test_dedupes_and_strips_trailing_dot():
    assert extract_contacts("a@shop.ph. A@SHOP.PH, a@shop.ph").emails == ["a@shop.ph"]


@pytest.mark.parametrize("junk", ["noreply@shop.ph", "webmaster@shop.ph", "x@sentry.io", "y@o123.ingest.sentry.io",
                                  "logo@2x.png", "user@example.com", "you@yourdomain.com"])
def test_rejects_infrastructure_tracker_and_asset_artifacts(junk):
    assert not is_plausible_email(junk)
    assert extract_contacts(f"contact {junk}").emails == []


def test_short_phone_numbers_are_ignored_and_empty_pages_find_nothing():
    found = extract_contacts('<a href="tel:123">x</a><p>nothing here</p>')
    assert (found.emails, found.phones) == ([], [])


# --- JSON-LD --------------------------------------------------------------------------------------


def ld(obj: object) -> str:
    return f'<script type="application/ld+json">{json.dumps(obj)}</script>'


def test_json_ld_organization_graph_and_contact_points():
    page = ld({"@type": "LocalBusiness", "email": "mailto:Owner@Bakery.ph", "telephone": "+63 917 555 0101"}) + ld(
        {"@graph": [{"@type": ["Organization"], "contactPoint": [{"email": "orders@bakery.ph"},
                                                                 {"telephone": "(02) 8555-0102"}]}]})
    found = extract_json_ld_contacts(page)
    assert found.emails == ["owner@bakery.ph", "orders@bakery.ph"]
    assert found.phones == ["+639175550101", "0285550102"]


def test_json_ld_ignores_non_organizations_and_survives_malformed_blocks():
    page = ld({"@type": "Person", "email": "person@x.ph"}) + \
        '<script type="application/ld+json">{"@type": "Organization", "email": </script>'
    assert extract_json_ld_contacts(page).emails == []


def test_json_ld_processing_is_capped_at_five_blocks():
    page = "".join(ld({"@type": "Organization", "email": f"o{i}@x.ph"}) for i in range(8))
    assert len(extract_json_ld_contacts(page).emails) == 5


def test_json_ld_results_merge_into_extract_contacts():
    page = '<a href="mailto:a@x.ph">a</a>' + ld({"@type": "Organization", "email": "b@x.ph"})
    assert extract_contacts(page).emails == ["a@x.ph", "b@x.ph"]


# --- domain and tech stack ------------------------------------------------------------------------


@pytest.mark.parametrize(("website", "domain"), [
    ("https://www.Bakery.ph/menu", "bakery.ph"), ("bakery.ph", "bakery.ph"),
    ("http://shop.example:8080", "shop.example"),
    (None, None), ("", None), ("http://", None),
])
def test_domain_of(website, domain):
    assert domain_of(website) == domain


@pytest.mark.parametrize(("page", "headers", "expected"), [
    ('<link href="/wp-content/themes/x.css">', {}, ["wordpress"]),
    ('<meta name="generator" content="WordPress 6.5">', {}, ["wordpress"]),
    ('<script src="https://cdn.shopify.com/s.js">', {}, ["shopify"]),
    ("", {"X-Shopify-Stage": "production"}, ["shopify"]),
    ('<img src="https://static.wixstatic.com/a.png">', {}, ["wix"]),
    ("", {"x-wix-request-id": "1"}, ["wix"]),
    ('<link href="https://static1.squarespace.com/x.css">', {}, ["squarespace"]),
    ("", {"X-Powered-By": "PHP/7.2"}, ["header:php/7.2"]),
    ("<p>plain</p>", {}, []),
])
def test_detect_tech_stack(page, headers, expected):
    assert detect_tech_stack(page, headers) == expected


# --- website scrape tier --------------------------------------------------------------------------


def page_result(text: str, *, url: str = "https://shop.ph/", status: int = 200,
                content_type: str = "text/html; charset=utf-8") -> SafeFetchResult:
    return SafeFetchResult(ok=200 <= status < 300, status=status, headers=httpx.Headers({"content-type": content_type}),
                           text=text, url=url)


def fetcher(pages: dict[str, SafeFetchResult | Exception]) -> tuple[Callable[[str], SafeFetchResult], list[str]]:
    calls: list[str] = []

    def fetch(url: str) -> SafeFetchResult:
        calls.append(url)
        outcome = pages.get(url, page_result("", status=404, url=url))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return fetch, calls


def test_scrape_without_website_does_nothing():
    fetch, calls = fetcher({})
    assert WebsiteScrapeTier(fetch).enrich(EnrichmentTarget("No Site", None)).emails == []
    assert calls == []


def test_scrape_homepage_email_attributes_source_and_page():
    home = '<a href="mailto:hi@shop.ph">x</a> <a href="tel:0917 555 0101">t</a>'
    fetch, calls = fetcher({"https://shop.ph": page_result(home, url="https://shop.ph/")})
    result = WebsiteScrapeTier(fetch).enrich(EnrichmentTarget("Shop", "https://shop.ph"))
    assert result.emails == [Found("hi@shop.ph", "website_scrape", "https://shop.ph/")]
    assert result.phones[0].value == "09175550101"
    assert calls == ["https://shop.ph"]  # found on the homepage: /contact not fetched


def test_scrape_falls_back_to_contact_page_and_merges():
    fetch, calls = fetcher({
        "https://shop.ph": page_result('<link href="/wp-content/x.css"><a href="tel:+63 2 8555 0100">t</a>'),
        "https://shop.ph/contact": page_result("Email orders@shop.ph", url="https://shop.ph/contact"),
    })
    result = WebsiteScrapeTier(fetch).enrich(EnrichmentTarget("Shop", "shop.ph"))
    assert calls == ["https://shop.ph", "https://shop.ph/contact"]
    assert [e.value for e in result.emails] == ["orders@shop.ph"]
    assert result.emails[0].source_ref == "https://shop.ph/contact"
    assert result.tech_stack == ["wordpress"] and len(result.phones) == 1


@pytest.mark.parametrize("failure", [UnsafeUrlError("private"), httpx.ConnectTimeout("slow")])
def test_scrape_never_raises_on_refusal_or_network_failure(failure):
    fetch, _ = fetcher({"https://shop.ph": failure, "https://shop.ph/contact": failure})
    assert WebsiteScrapeTier(fetch).enrich(EnrichmentTarget("Shop", "https://shop.ph")) == EnrichmentResult()


def test_scrape_ignores_error_pages_and_non_html():
    fetch, _ = fetcher({"https://shop.ph": page_result("a@shop.ph", status=500),
                        "https://shop.ph/contact": page_result("b@shop.ph", content_type="application/pdf")})
    assert WebsiteScrapeTier(fetch).enrich(EnrichmentTarget("Shop", "https://shop.ph")).emails == []


def test_contact_page_url():
    assert contact_page_url("https://shop.ph/menu?x=1#top") == "https://shop.ph/contact"
    assert contact_page_url("http://") is None


# --- RDAP -----------------------------------------------------------------------------------------


def mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(record)), seen


def vcard_entity(*props: list) -> dict:
    return {"roles": ["registrar"], "vcardArray": ["vcard", [["version", {}, "text", "4.0"], *props]]}


def test_rdap_findings_are_guesses_never_emails():
    client, seen = mock_client(lambda r: httpx.Response(200, json={"entities": [
        vcard_entity(["email", {}, "text", "Domains@Proxy-Registrar.example"]),
        vcard_entity(["email", {}, "text", "abuse@registrar.example"]),  # abuse desks are infrastructure: dropped
        vcard_entity(["tel", {}, "uri", "tel:+1"])]}))
    result = RdapTier(client, base_url="https://rdap.test/domain").enrich(EnrichmentTarget("Shop", "https://www.shop.ph"))
    assert str(seen[0].url) == "https://rdap.test/domain/shop.ph"
    assert result.emails == []
    assert result.guessed_emails == [Found("domains@proxy-registrar.example", "rdap", "https://rdap.test/domain/shop.ph",
                                           RDAP_GUESS_CONFIDENCE)]


@pytest.mark.parametrize("response", [
    httpx.Response(200, json={"entities": [{"roles": ["registrant"]}]}),  # live-verified redacted shape
    httpx.Response(200, json={"entities": "nonsense"}),
    httpx.Response(404),
    httpx.Response(200, text="not json"),
])
def test_rdap_odd_or_redacted_responses_find_nothing(response):
    client, _ = mock_client(lambda r: response)
    assert RdapTier(client).enrich(EnrichmentTarget("Shop", "https://shop.ph")) == EnrichmentResult()


def test_rdap_without_website_makes_no_request():
    client, seen = mock_client(lambda r: httpx.Response(500))
    RdapTier(client).enrich(EnrichmentTarget("Shop", None))
    assert seen == []


# --- Hunter ---------------------------------------------------------------------------------------


def hunter_body(*emails: tuple[str, int]) -> dict:
    return {"data": {"emails": [{"value": v, "confidence": c} for v, c in emails]}}


def test_hunter_needs_a_key():
    with pytest.raises(ValueError):
        HunterTier(httpx.Client(), "")


def test_hunter_searches_by_domain_and_filters_low_confidence():
    body = hunter_body(("Owner@Shop.ph", 91), ("x@shop.ph", 20))
    client, seen = mock_client(lambda r: httpx.Response(200, json=body))
    result = HunterTier(client, "key", endpoint="https://hunter.test/v2/domain-search").enrich(
        EnrichmentTarget("Shop", "https://www.shop.ph"))
    params = seen[0].url.params
    assert (params["domain"], params["api_key"], "company" in params) == ("shop.ph", "key", False)
    assert result.emails == [Found("owner@shop.ph", "hunter", "hunter:domain:shop.ph", 0.91)]
    assert result.billed_calls == {"hunter": 1}


def test_hunter_falls_back_to_company_search_without_website():
    client, seen = mock_client(lambda r: httpx.Response(200, json=hunter_body()))
    HunterTier(client, "key").enrich(EnrichmentTarget("Davao Sunrise Bakery", None))
    assert seen[0].url.params["company"] == "Davao Sunrise Bakery" and "domain" not in seen[0].url.params


@pytest.mark.parametrize("response", [httpx.Response(429), httpx.Response(401), httpx.Response(200, text="x")])
def test_hunter_failures_find_nothing_but_still_count_the_call(response):
    client, _ = mock_client(lambda r: response)
    result = HunterTier(client, "key").enrich(EnrichmentTarget("Shop", "https://shop.ph"))
    assert result.emails == [] and result.billed_calls == {"hunter": 1}


def test_hunter_with_neither_website_nor_name_makes_no_request():
    client, seen = mock_client(lambda r: httpx.Response(200, json=hunter_body()))
    assert HunterTier(client, "key").enrich(EnrichmentTarget("", None)).billed_calls == {}
    assert seen == []


# --- waterfall ------------------------------------------------------------------------------------


class StubTier:
    billed = False

    def __init__(self, tier_id: str, result: EnrichmentResult | Exception) -> None:
        self.id = self.name = tier_id
        self.result = result
        self.calls = 0

    def enrich(self, target: EnrichmentTarget) -> EnrichmentResult:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


T = EnrichmentTarget("Shop", "https://shop.ph", score=50)


def test_waterfall_stops_at_first_real_email_and_keeps_earlier_phones():
    first = StubTier("free", EnrichmentResult(phones=[Found("0917", "free")]))
    second = StubTier("paid", EnrichmentResult(emails=[Found("a@shop.ph", "paid")]))
    third = StubTier("never", EnrichmentResult(emails=[Found("b@shop.ph", "never")]))
    result = run_waterfall([TierStep(first), TierStep(second), TierStep(third)], T)
    assert [e.value for e in result.emails] == ["a@shop.ph"] and result.phones[0].value == "0917"
    assert (result.tiers_run, third.calls) == (["free", "paid"], 0)


def test_guesses_never_stop_the_waterfall():
    guess = StubTier("rdap", EnrichmentResult(guessed_emails=[Found("proxy@registrar.example", "rdap")]))
    real = StubTier("hunter", EnrichmentResult(emails=[Found("owner@shop.ph", "hunter")]))
    result = run_waterfall([TierStep(guess), TierStep(real)], T)
    assert real.calls == 1 and len(result.guessed_emails) == 1 and result.emails[0].source == "hunter"


def test_should_try_skips_a_paid_tier_for_low_scorers():
    paid = StubTier("paid", EnrichmentResult(emails=[Found("a@shop.ph", "paid")]))
    result = run_waterfall([TierStep(paid, should_try=lambda t: (t.score or 0) >= 80)], T)
    assert (paid.calls, result.tiers_run, result.emails) == (0, [], [])


def test_a_raising_tier_does_not_break_the_waterfall():
    boom = StubTier("boom", RuntimeError("bug"))
    ok = StubTier("ok", EnrichmentResult(emails=[Found("a@shop.ph", "ok")]))
    result = run_waterfall([TierStep(boom), TierStep(ok)], T)
    assert result.tiers_run == ["boom", "ok"] and result.emails[0].value == "a@shop.ph"


def test_billed_calls_accumulate():
    a = StubTier("a", EnrichmentResult(billed_calls={"hunter": 1}))
    b = StubTier("b", EnrichmentResult(billed_calls={"hunter": 2}))
    assert run_waterfall([TierStep(a), TierStep(b)], T).billed_calls == {"hunter": 3}
