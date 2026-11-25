"""OpenStreetMap discovery through the Overpass API: real businesses, no key, no card.

Ported from guma_os `adapter-maps/src/osm.ts`. Overpass is a free community service, so be a good
citizen: identify via User-Agent, keep queries bounded, and never remove the pause between queries in
batch crawls. Coverage is lower than Google's and OSM has no ratings, but it costs nothing.

Change from the original: an unknown city is looked up as a Philippine administrative boundary by name
(trying "X", "X City" and "City of X", since OSM names cities inconsistently) instead of silently falling
back to a Metro Manila bounding box, which returned Manila results for any other city. Two PH cities can
share a name (San Fernando in Pampanga and in La Union): both match.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.domains.business_discovery.providers.base import (
    DiscoveredBusiness,
    DiscoveryError,
    DiscoveryQuery,
    DiscoveryQuotaExceeded,
)

OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"

# Bounding boxes (south, west, north, east): faster and more reliable than an area lookup for big cities.
CITY_BBOX: dict[str, tuple[float, float, float, float]] = {
    "quezon city": (14.6, 120.98, 14.78, 121.13),
    "makati": (14.53, 121.0, 14.58, 121.04),
    "manila": (14.55, 120.96, 14.63, 121.02),
    "taguig": (14.48, 121.03, 14.57, 121.08),
    "pasig": (14.53, 121.05, 14.6, 121.1),
    "cebu city": (10.28, 123.85, 10.42, 123.94),
    "davao city": (7.02, 125.4, 7.15, 125.65),
    "iloilo city": (10.68, 122.53, 10.75, 122.6),
    "baguio": (16.38, 120.56, 16.44, 120.62),
    "cagayan de oro": (8.44, 124.6, 8.51, 124.68),
    "bacolod": (10.62, 122.92, 10.7, 122.99),
}
CITY_ALIASES = {"makati city": "makati", "taguig city": "taguig", "pasig city": "pasig", "baguio city": "baguio",
                "cagayan de oro city": "cagayan de oro", "bacolod city": "bacolod", "city of manila": "manila"}

# Human category -> OSM tag selectors. First matching row wins.
_CATEGORY_TABLE: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("dental", "dentist"), ('["amenity"="dentist"]', '["healthcare"="dentist"]')),
    (("restaurant", "eatery", "resto"), ('["amenity"="restaurant"]',)),
    (("cafe", "coffee"), ('["amenity"="cafe"]',)),
    (("bakery", "bake"), ('["shop"="bakery"]',)),
    (("salon", "hair", "barber"), ('["shop"="hairdresser"]', '["shop"="beauty"]')),
    (("spa",), ('["leisure"="spa"]', '["shop"="beauty"]')),
    (("gym", "fitness"), ('["leisure"="fitness_centre"]',)),
    (("auto", "car repair", "mechanic"), ('["shop"="car_repair"]',)),
    (("vet", "veterinary"), ('["amenity"="veterinary"]',)),
    (("pharmacy", "drugstore"), ('["amenity"="pharmacy"]',)),
    (("hardware",), ('["shop"="hardware"]', '["shop"="doityourself"]')),
    (("plumb",), ('["craft"="plumber"]',)),
    (("electrician", "electrical"), ('["craft"="electrician"]',)),
    (("law", "legal", "attorney"), ('["office"="lawyer"]',)),
    (("real estate", "realty", "property"), ('["office"="estate_agent"]',)),
    (("hotel", "inn", "lodging"), ('["tourism"="hotel"]',)),
    (("laundry", "laundromat"), ('["shop"="laundry"]',)),
    (("car wash",), ('["amenity"="car_wash"]',)),
    (("print", "printing"), ('["shop"="copyshop"]',)),
    (("travel",), ('["shop"="travel_agency"]',)),
    (("pet",), ('["shop"="pet"]',)),
    (("clinic", "medical"), ('["amenity"="clinic"]', '["healthcare"="clinic"]')),
]


def _safe_term(value: str) -> str:
    """Strip everything but letters, digits and spaces, so user text can't break out of Overpass QL."""
    return re.sub(r"[^a-z0-9 ]", "", value.lower()).strip()


def category_to_selectors(category: str | None) -> list[str]:
    term = (category or "").lower()
    for matches, selectors in _CATEGORY_TABLE:
        if any(m in term for m in matches):
            return list(selectors)
    safe = _safe_term(term)
    if safe:  # unknown category: businesses whose name contains the term
        return [f'["name"~"{safe}",i]["shop"]', f'["name"~"{safe}",i]["amenity"]', f'["name"~"{safe}",i]["office"]']
    return ['["shop"]']


def city_name_variants(city: str) -> list[str]:
    """OSM names PH cities inconsistently: "Angeles" (official "City of Angeles"), "Cebu City", "Makati"."""
    name = re.sub(r"\s+", " ", re.sub(r"[^\w \-]", "", city)).strip()
    base = re.sub(r"(?i)^city of ", "", re.sub(r"(?i) city$", "", name)).strip()
    return list(dict.fromkeys(v for v in (name, base, f"{base} City", f"City of {base}") if base and v))


def _area_lookup(city: str) -> str:
    """The city's administrative boundary inside the Philippines, so a same-named place abroad can't match."""
    variants = city_name_variants(city)
    if not variants:
        raise DiscoveryError(f"not a usable city name: {city!r}")
    pattern = "^(" + "|".join(variants) + ")$"
    return ('area["ISO3166-1"="PH"]["admin_level"="2"]->.ph;\n'
            f'rel(area.ph)["boundary"="administrative"]["name"~"{pattern}",i];\n'
            "map_to_area->.city;\n")


def build_query(query: DiscoveryQuery, timeout_seconds: int = 25) -> str:
    """Overpass QL for `query`. Requires a city: a country-wide scan is too heavy for a shared service."""
    if not query.city:
        raise DiscoveryError("OpenStreetMap discovery needs a city")
    selectors = category_to_selectors(query.category or query.query)
    city_key = query.city.strip().lower()
    city_key = CITY_ALIASES.get(city_key, city_key)
    head = f"[out:json][timeout:{timeout_seconds}];"
    if city_key in CITY_BBOX:
        s, w, n, e = CITY_BBOX[city_key]
        scope = f"({s},{w},{n},{e})"
        area = ""
    else:
        area = _area_lookup(query.city)
        scope = "(area.city)"
    body = "\n".join(f"  nwr{sel}{scope};" for sel in selectors)
    return f"{head}\n{area}(\n{body}\n);\nout center tags {query.limit};"


def map_element(element: dict[str, Any], query: DiscoveryQuery) -> DiscoveredBusiness | None:
    """One Overpass element -> DiscoveredBusiness; None for unnamed elements."""
    tags: dict[str, str] = element.get("tags") or {}
    name = tags.get("name") or tags.get("name:en")
    if not name:
        return None
    address = " ".join(p for p in (tags.get("addr:housenumber"), tags.get("addr:street"),
                                   tags.get("addr:barangay") or tags.get("addr:suburb")) if p) or None
    center = element.get("center") or {}
    return DiscoveredBusiness(
        name=name,
        source="osm",
        category=query.category or tags.get("shop") or tags.get("amenity") or tags.get("office")
        or tags.get("craft") or tags.get("healthcare"),
        address=address,
        city=query.city or tags.get("addr:city"),
        province=tags.get("addr:province"),
        phone=tags.get("phone") or tags.get("contact:phone") or tags.get("contact:mobile"),
        website=tags.get("website") or tags.get("contact:website") or tags.get("url"),
        latitude=element.get("lat", center.get("lat")),
        longitude=element.get("lon", center.get("lon")),
        place_id=f"osm:{element.get('type')}/{element.get('id')}",
    )


class OsmDiscoveryProvider:
    id = "osm"
    name = "OpenStreetMap (Overpass)"

    def __init__(self, client: httpx.Client, *, endpoint: str = OVERPASS_ENDPOINT, user_agent: str,
                 timeout: float = 40.0) -> None:
        self.client = client
        self.endpoint = endpoint
        self.user_agent = user_agent
        self.timeout = timeout

    def discover(self, query: DiscoveryQuery) -> list[DiscoveredBusiness]:
        ql = build_query(query)
        try:
            response = self.client.post(self.endpoint, data={"data": ql}, timeout=self.timeout,
                                        headers={"User-Agent": self.user_agent})
        except httpx.HTTPError as exc:
            raise DiscoveryError(f"Overpass request failed: {exc}") from exc
        if response.status_code == 429:
            raise DiscoveryQuotaExceeded("Overpass rate limit (429); wait before the next query")
        if response.status_code != 200:
            raise DiscoveryError(f"Overpass error {response.status_code}: {response.text[:200]}")
        try:
            elements = response.json().get("elements") or []
        except ValueError as exc:
            raise DiscoveryError("Overpass returned invalid JSON") from exc
        found: list[DiscoveredBusiness] = []
        for element in elements:
            business = map_element(element, query)
            if business is not None:
                found.append(business)
            if len(found) >= query.limit:
                break
        return found
