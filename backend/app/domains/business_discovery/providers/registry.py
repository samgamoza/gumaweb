"""Which discovery sources exist, whether each is usable right now, and how to build one."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.domains.business_discovery.enums import DiscoverySource
from app.domains.business_discovery.providers.base import DiscoveryProvider, SourceCategory, SourceDescriptor
from app.domains.business_discovery.providers.fixture import FixtureDiscoveryProvider
from app.domains.business_discovery.providers.google_places import GooglePlacesDiscoveryProvider
from app.domains.business_discovery.providers.osm import OVERPASS_ENDPOINT, OsmDiscoveryProvider

SOURCE_LABELS: dict[str, DiscoverySource] = {
    "osm": DiscoverySource.OSM,
    "google_places": DiscoverySource.GOOGLE_BUSINESS,
    "fixture": DiscoverySource.FIXTURE,
}


class UnknownSourceError(ValueError):
    pass


class SourceUnavailableError(ValueError):
    """The source exists but is not configured (no key) or is disabled in this environment."""


@dataclass(frozen=True)
class DiscoveryConfig:
    google_maps_api_key: str | None = None
    overpass_endpoint: str = OVERPASS_ENDPOINT
    user_agent: str = "GumaWebBot/1.0 (+https://gumaweb.io/bot)"
    allow_fixture: bool = False


def describe_sources(config: DiscoveryConfig) -> list[SourceDescriptor]:
    sources = [
        SourceDescriptor("osm", "OpenStreetMap (Overpass)", SourceCategory.DIRECTORY, DiscoverySource.OSM,
                         requires_key=False, configured=True,
                         note="Free. Lower coverage, no ratings. Needs a city."),
        SourceDescriptor("google_places", "Google Maps (Places API)", SourceCategory.DIRECTORY,
                         DiscoverySource.GOOGLE_BUSINESS, requires_key=True,
                         configured=bool(config.google_maps_api_key), billed=True,
                         note="Best coverage, ratings and reviews. Billed per request beyond Google's free caps."),
    ]
    if config.allow_fixture:
        sources.append(SourceDescriptor("fixture", "Fixture (fictional sample listings)", SourceCategory.TEST,
                                        DiscoverySource.FIXTURE, requires_key=False, configured=True,
                                        note="Offline test data. Disabled in production."))
    return sources


def build_provider(source_id: str, client: httpx.Client, config: DiscoveryConfig) -> DiscoveryProvider:
    descriptor = next((s for s in describe_sources(config) if s.id == source_id), None)
    if descriptor is None:
        if source_id == "fixture":
            raise SourceUnavailableError("the fixture source is disabled in this environment")
        raise UnknownSourceError(f"unknown discovery source: {source_id}")
    if not descriptor.configured:
        raise SourceUnavailableError(f"{descriptor.name} is not configured (missing API key)")
    if source_id == "osm":
        return OsmDiscoveryProvider(client, endpoint=config.overpass_endpoint, user_agent=config.user_agent)
    if source_id == "google_places":
        return GooglePlacesDiscoveryProvider(client, config.google_maps_api_key or "")
    return FixtureDiscoveryProvider()
