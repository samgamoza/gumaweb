"""Discovery providers (port plan step 3). No network: HTTP goes through httpx.MockTransport.

Ports the guma_os `discovery.test.ts` cases (fixture filtering, OSM selectors/bbox/mapping, Google key
requirement, source selection) and adds provider-over-HTTP, error and injection cases.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.parse import parse_qs

import httpx
import pytest

from app.domains.business_discovery.enums import DiscoverySource
from app.domains.business_discovery.providers.base import (
    DiscoveredBusiness,
    DiscoveryError,
    DiscoveryQuery,
    DiscoveryQuotaExceeded,
)
from app.domains.business_discovery.providers.fixture import FIXTURE_BUSINESSES, FixtureDiscoveryProvider
from app.domains.business_discovery.providers.google_places import (
    FIELD_MASK,
    GooglePlacesDiscoveryProvider,
    map_place,
    text_query,
)
from app.domains.business_discovery.providers.osm import (
    CITY_BBOX,
    OsmDiscoveryProvider,
    build_query,
    category_to_selectors,
    city_name_variants,
    map_element,
)
from app.domains.business_discovery.providers.registry import (
    DiscoveryConfig,
    SourceUnavailableError,
    UnknownSourceError,
    build_provider,
    describe_sources,
)


def client_with(handler: Callable[[httpx.Request], httpx.Response]) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(record)), seen


# --- query ----------------------------------------------------------------------------------------


def test_query_needs_something_to_search_for_and_a_sane_limit():
    with pytest.raises(ValueError):
        DiscoveryQuery()
    with pytest.raises(ValueError):
        DiscoveryQuery(category="bakery", limit=0)
    with pytest.raises(ValueError):
        DiscoveryQuery(category="bakery", limit=501)


def test_discovered_business_maps_to_an_import_record():
    record = DiscoveredBusiness(name="Cebu Smile Dental", source="osm", category="dental clinic", city="Cebu City",
                                phone="+63 32 555 0101", latitude=10.3, longitude=123.9,
                                place_id="osm:node/42").to_raw_record()
    assert (record.name, record.industry, record.city, record.source_ref) == (
        "Cebu Smile Dental", "dental clinic", "Cebu City", "osm:node/42")
    assert (record.latitude, record.longitude) == ("10.3", "123.9")


# --- fixture --------------------------------------------------------------------------------------


def test_fixture_filters_by_category_city_and_limit():
    provider = FixtureDiscoveryProvider()
    dental = provider.discover(DiscoveryQuery(category="Dental"))
    assert dental and all("dental" in b.category.lower() for b in dental)
    cebu = provider.discover(DiscoveryQuery(city="Cebu City"))
    assert cebu and all(b.city == "Cebu City" for b in cebu)
    assert len(provider.discover(DiscoveryQuery(query="a", limit=3))) == 3
    assert provider.discover(DiscoveryQuery(city="Nowhere")) == []


def test_fixture_data_is_unmistakably_fictional():
    for b in FIXTURE_BUSINESSES:
        assert " 555 " in b.phone, b.name
        assert b.website is None or b.website.endswith(".example"), b.name


# --- OpenStreetMap --------------------------------------------------------------------------------


def test_known_categories_map_to_osm_tags():
    assert '["amenity"="dentist"]' in category_to_selectors("dental clinic")
    assert category_to_selectors("Bakery") == ['["shop"="bakery"]']
    assert category_to_selectors("plumbing services") == ['["craft"="plumber"]']


def test_unknown_category_falls_back_to_a_sanitized_name_match():
    selectors = category_to_selectors('artisanal widget"];out;(node(1);')
    assert all('name"~"artisanal widgetoutnode1"' in s for s in selectors)
    assert all('"];' not in s for s in selectors)  # cannot break out of the filter


def test_query_uses_a_bounding_box_for_known_cities():
    ql = build_query(DiscoveryQuery(category="bakery", city="Cebu City", limit=12))
    s, w, n, e = CITY_BBOX["cebu city"]
    assert f'nwr["shop"="bakery"]({s},{w},{n},{e});' in ql
    assert ql.rstrip().endswith("out center tags 12;")
    assert build_query(DiscoveryQuery(category="bakery", city="Makati City")).count("(14.53,121.0,14.58,121.04)") == 1


def test_query_looks_up_other_cities_as_a_philippine_boundary_with_name_variants():
    ql = build_query(DiscoveryQuery(category="plumber", city='Angeles "City"'))
    assert 'area["ISO3166-1"="PH"]["admin_level"="2"]->.ph;' in ql
    assert '["name"~"^(Angeles City|Angeles|City of Angeles)$",i];' in ql
    assert "map_to_area->.city;" in ql
    assert 'nwr["craft"="plumber"](area.city);' in ql


@pytest.mark.parametrize(("city", "variants"), [
    ("Angeles City", ["Angeles City", "Angeles", "City of Angeles"]),
    ("City of San Fernando", ["City of San Fernando", "San Fernando", "San Fernando City"]),
    ("Parañaque", ["Parañaque", "Parañaque City", "City of Parañaque"]),
    ('Bad"];out;(', ["Badout", "Badout City", "City of Badout"]),
])
def test_city_name_variants(city, variants):
    assert city_name_variants(city) == variants


def test_unusable_city_name_is_rejected():
    with pytest.raises(DiscoveryError):
        build_query(DiscoveryQuery(category="bakery", city='"];'))


def test_osm_needs_a_city():
    with pytest.raises(DiscoveryError):
        build_query(DiscoveryQuery(category="bakery"))


def test_map_element_and_skip_unnamed():
    q = DiscoveryQuery(category="dental clinic", city="Cebu City")
    named = map_element({"type": "way", "id": 42, "center": {"lat": 10.3, "lon": 123.9},
                         "tags": {"name": "Cebu Smile Dental", "amenity": "dentist", "phone": "+63 32 555 0101",
                                  "contact:website": "https://smile.example", "addr:street": "Osmena Blvd"}}, q)
    assert named.name == "Cebu Smile Dental" and named.place_id == "osm:way/42" and named.source == "osm"
    assert (named.latitude, named.longitude) == (10.3, 123.9)
    assert named.website == "https://smile.example" and named.address == "Osmena Blvd"
    assert map_element({"type": "node", "id": 7, "tags": {}}, q) is None


def overpass_ok(elements: list[dict]) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(200, json={"elements": elements})


def test_osm_provider_posts_the_query_with_a_user_agent_and_respects_limit():
    elements = [{"type": "node", "id": i, "lat": 10.3, "lon": 123.9, "tags": {"name": f"Bakery {i}"}}
                for i in range(5)] + [{"type": "node", "id": 99, "tags": {}}]
    client, seen = client_with(overpass_ok(elements))
    provider = OsmDiscoveryProvider(client, endpoint="https://overpass.test/api", user_agent="GumaWebBot/test")
    found = provider.discover(DiscoveryQuery(category="bakery", city="Cebu City", limit=3))
    assert [b.name for b in found] == ["Bakery 0", "Bakery 1", "Bakery 2"]
    request = seen[0]
    assert request.method == "POST" and str(request.url) == "https://overpass.test/api"
    assert request.headers["user-agent"] == "GumaWebBot/test"
    assert '["shop"="bakery"]' in parse_qs(request.content.decode())["data"][0]


@pytest.mark.parametrize(("status", "error"), [(429, DiscoveryQuotaExceeded), (504, DiscoveryError)])
def test_osm_provider_errors(status, error):
    client, _ = client_with(lambda r: httpx.Response(status, text="busy"))
    with pytest.raises(error):
        OsmDiscoveryProvider(client, user_agent="x").discover(DiscoveryQuery(category="bakery", city="Cebu City"))


def test_osm_provider_rejects_invalid_json():
    client, _ = client_with(lambda r: httpx.Response(200, text="<html>maintenance</html>"))
    with pytest.raises(DiscoveryError):
        OsmDiscoveryProvider(client, user_agent="x").discover(DiscoveryQuery(category="bakery", city="Cebu City"))


def test_osm_provider_wraps_transport_errors():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client, _ = client_with(boom)
    with pytest.raises(DiscoveryError):
        OsmDiscoveryProvider(client, user_agent="x").discover(DiscoveryQuery(category="bakery", city="Cebu City"))


# --- Google Places --------------------------------------------------------------------------------


def test_google_text_query():
    assert text_query(DiscoveryQuery(category="dental clinic", city="Quezon City")) == \
        "dental clinic in Quezon City, Philippines"
    assert text_query(DiscoveryQuery(city="Cebu City")) == "Cebu City, Philippines"
    assert text_query(DiscoveryQuery(query="vegan bakery near Ayala")) == "vegan bakery near Ayala"


def test_google_map_place_and_skip_closed():
    q = DiscoveryQuery(category="bakery", city="Davao City")
    place = {"id": "ChIJabc", "displayName": {"text": "Sunrise Bakery"}, "formattedAddress": "1 Main St, Davao",
             "nationalPhoneNumber": "0917 555 0133", "rating": 4.4, "userRatingCount": 143,
             "location": {"latitude": 7.07, "longitude": 125.6}}
    b = map_place(place, q)
    assert (b.name, b.place_id, b.rating, b.review_count, b.source) == (
        "Sunrise Bakery", "ChIJabc", 4.4, 143, "google_places")
    assert map_place({**place, "businessStatus": "CLOSED_PERMANENTLY"}, q) is None
    assert map_place({"id": "x"}, q) is None


def test_google_provider_requires_a_key():
    with pytest.raises(ValueError):
        GooglePlacesDiscoveryProvider(httpx.Client(), "")


def test_google_provider_sends_key_field_mask_and_caps_page_size():
    client, seen = client_with(lambda r: httpx.Response(200, json={"places": [
        {"id": f"p{i}", "displayName": {"text": f"Shop {i}"}} for i in range(20)]}))
    found = GooglePlacesDiscoveryProvider(client, "test-key").discover(
        DiscoveryQuery(category="bakery", city="Davao City", limit=50))
    assert len(found) == 20
    request = seen[0]
    assert request.headers["x-goog-api-key"] == "test-key"
    assert request.headers["x-goog-fieldmask"] == FIELD_MASK
    body = json.loads(request.content)
    assert body == {"textQuery": "bakery in Davao City, Philippines", "regionCode": "PH", "pageSize": 20}


def test_google_quota_error():
    client, _ = client_with(lambda r: httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}}))
    with pytest.raises(DiscoveryQuotaExceeded):
        GooglePlacesDiscoveryProvider(client, "k").discover(DiscoveryQuery(category="bakery", city="Cebu City"))


def test_google_error_message_is_trimmed_and_never_echoes_the_key():
    client, _ = client_with(lambda r: httpx.Response(403, json={"error": {"message": "API key not valid"}}))
    with pytest.raises(DiscoveryError) as caught:
        GooglePlacesDiscoveryProvider(client, "secret-key-123").discover(DiscoveryQuery(city="Cebu City"))
    assert "403" in str(caught.value) and "API key not valid" in str(caught.value)
    assert "secret-key-123" not in str(caught.value)


# --- registry -------------------------------------------------------------------------------------


def test_sources_reflect_configuration():
    without = {s.id: s for s in describe_sources(DiscoveryConfig())}
    assert without["osm"].configured and not without["osm"].requires_key
    assert without["google_places"].requires_key and not without["google_places"].configured
    assert without["google_places"].billed
    assert "fixture" not in without
    assert describe_sources(DiscoveryConfig(google_maps_api_key="k"))[1].configured
    labels = {s.id: s.discovery_source for s in describe_sources(DiscoveryConfig(allow_fixture=True))}
    assert labels == {"osm": DiscoverySource.OSM, "google_places": DiscoverySource.GOOGLE_BUSINESS,
                      "fixture": DiscoverySource.FIXTURE}


def test_build_provider_refuses_unknown_unconfigured_and_disabled_sources():
    client = httpx.Client()
    with pytest.raises(UnknownSourceError):
        build_provider("yellow_pages", client, DiscoveryConfig())
    with pytest.raises(SourceUnavailableError):
        build_provider("google_places", client, DiscoveryConfig())
    with pytest.raises(SourceUnavailableError):
        build_provider("fixture", client, DiscoveryConfig(allow_fixture=False))
    assert build_provider("osm", client, DiscoveryConfig()).id == "osm"
    assert build_provider("google_places", client, DiscoveryConfig(google_maps_api_key="k")).id == "google_places"
    assert build_provider("fixture", client, DiscoveryConfig(allow_fixture=True)).id == "fixture"
