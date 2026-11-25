"""Discovery provider port: one interface over every business-listing source.

Ported from guma_os `@guma/provider` (`DiscoveryProvider`, `DiscoveredBusiness`, `DiscoveryQuery`). A
provider only fetches and maps listings; normalization, dedupe, scoring and storage stay in
`BusinessService.import_records`, so every source goes through the same pipeline as a CSV import.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.domains.business_discovery.enums import DiscoverySource
from app.domains.business_discovery.sources import RawBusinessRecord


class SourceCategory(StrEnum):
    """How a source finds businesses (for grouping in the admin source picker)."""

    DIRECTORY = "directory"  # map/listing directories: OSM, Google Places
    REGISTRY = "registry"  # membership or government registries: chambers of commerce
    TEST = "test"  # offline fixtures


class DiscoveryError(Exception):
    """The source could not answer (HTTP error, bad response). The run is recorded as failed."""


class DiscoveryQuotaExceeded(DiscoveryError):
    """The source refused for quota/rate reasons (e.g. Google 429). Retry later, not sooner."""


@dataclass(frozen=True)
class DiscoveryQuery:
    category: str | None = None  # e.g. "dental clinic"
    city: str | None = None  # e.g. "Cebu City"
    query: str | None = None  # free text; overrides category/city where the source supports it
    limit: int = 30

    def __post_init__(self) -> None:
        if not (self.category or self.city or self.query):
            raise ValueError("give at least a category, a city or a query")
        if not 1 <= self.limit <= 500:
            raise ValueError("limit must be between 1 and 500")


@dataclass(frozen=True)
class DiscoveredBusiness:
    """One listing as a source reports it: facts only, no score (scoring happens on import)."""

    name: str
    source: str  # provider id
    category: str | None = None
    address: str | None = None
    city: str | None = None
    province: str | None = None
    phone: str | None = None
    website: str | None = None
    rating: float | None = None
    review_count: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    place_id: str | None = None  # provider-native id (Google place id, "osm:node/123"); stored as source_ref
    owner: str | None = None  # a named person, when the source lists one

    def to_raw_record(self) -> RawBusinessRecord:
        return RawBusinessRecord(
            name=self.name,
            industry=self.category,
            city=self.city,
            province=self.province,
            address=self.address,
            phone=self.phone,
            website=self.website,
            source_ref=self.place_id,
            latitude=str(self.latitude) if self.latitude is not None else None,
            longitude=str(self.longitude) if self.longitude is not None else None,
        )


@dataclass(frozen=True)
class SourceDescriptor:
    id: str
    name: str
    category: SourceCategory
    discovery_source: DiscoverySource  # how businesses from it are labelled
    requires_key: bool
    configured: bool  # usable right now (key present, not disabled)
    billed: bool = False  # each call can cost money
    note: str | None = None


class DiscoveryProvider(Protocol):
    id: str
    name: str

    def discover(self, query: DiscoveryQuery) -> list[DiscoveredBusiness]: ...
