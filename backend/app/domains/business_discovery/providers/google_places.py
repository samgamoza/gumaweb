"""Google Places API (New) Text Search discovery.

Ported from guma_os `adapter-maps/src/discovery.ts` (GoogleMapsDiscoveryProvider). Needs a key on a
billing-enabled Google Cloud project; usage is billed per request beyond Google's free monthly caps.
The field mask keeps the response, and the per-request SKU, to what we actually use. Demo-tier keys cap
at about 100 text searches a day and then answer 429 RESOURCE_EXHAUSTED.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.domains.business_discovery.providers.base import (
    DiscoveredBusiness,
    DiscoveryError,
    DiscoveryQuery,
    DiscoveryQuotaExceeded,
)

PLACES_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join(f"places.{f}" for f in (
    "id", "displayName", "primaryType", "primaryTypeDisplayName", "formattedAddress", "nationalPhoneNumber",
    "websiteUri", "rating", "userRatingCount", "location", "businessStatus",
))
MAX_RESULTS_PER_REQUEST = 20  # Places Text Search page size cap


def text_query(query: DiscoveryQuery, country: str = "Philippines") -> str:
    """e.g. "dental clinic in Quezon City, Philippines"."""
    if query.query:
        return query.query
    return f"{' in '.join(p for p in (query.category, query.city) if p)}, {country}"


def map_place(place: dict[str, Any], query: DiscoveryQuery) -> DiscoveredBusiness | None:
    name = (place.get("displayName") or {}).get("text")
    if not name or place.get("businessStatus") == "CLOSED_PERMANENTLY":
        return None
    location = place.get("location") or {}
    return DiscoveredBusiness(
        name=name,
        source="google_places",
        category=query.category or (place.get("primaryTypeDisplayName") or {}).get("text") or place.get("primaryType"),
        address=place.get("formattedAddress"),
        city=query.city,
        phone=place.get("nationalPhoneNumber"),
        website=place.get("websiteUri"),
        rating=place.get("rating"),
        review_count=place.get("userRatingCount"),
        latitude=location.get("latitude"),
        longitude=location.get("longitude"),
        place_id=place.get("id"),
    )


class GooglePlacesDiscoveryProvider:
    id = "google_places"
    name = "Google Maps (Places API)"

    def __init__(self, client: httpx.Client, api_key: str, *, endpoint: str = PLACES_ENDPOINT,
                 region_code: str = "PH", timeout: float = 15.0) -> None:
        if not api_key:
            raise ValueError("Google Places discovery needs GOOGLE_MAPS_API_KEY")
        self.client = client
        self.api_key = api_key
        self.endpoint = endpoint
        self.region_code = region_code
        self.timeout = timeout

    def discover(self, query: DiscoveryQuery) -> list[DiscoveredBusiness]:
        body = {"textQuery": text_query(query), "regionCode": self.region_code,
                "pageSize": min(query.limit, MAX_RESULTS_PER_REQUEST)}
        headers = {"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": FIELD_MASK}
        try:
            response = self.client.post(self.endpoint, json=body, headers=headers, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise DiscoveryError(f"Google Places request failed: {exc}") from exc
        if response.status_code == 429:
            raise DiscoveryQuotaExceeded("Google Places quota exhausted (429 RESOURCE_EXHAUSTED)")
        if response.status_code != 200:
            # Google error bodies can echo request details; keep only the status and message.
            try:
                message = response.json().get("error", {}).get("message", "")
            except ValueError:
                message = ""
            raise DiscoveryError(f"Google Places error {response.status_code}: {message[:200]}")
        try:
            places = response.json().get("places") or []
        except ValueError as exc:
            raise DiscoveryError("Google Places returned invalid JSON") from exc
        found = [b for b in (map_place(p, query) for p in places) if b is not None]
        return found[: query.limit]
