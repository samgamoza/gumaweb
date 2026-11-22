"""Discovery connectors (Crawl stage).

Phase 1 ships file-based importers (CSV/JSON). Directory and platform connectors
(DTI, Chamber, Yellow Pages, Google Business, Facebook) implement the same
protocol; they must respect each source's terms of service and robots.txt and
prefer official data exports/APIs over scraping.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, fields
from typing import Protocol

from app.domains.business_discovery.enums import DiscoverySource


@dataclass
class RawBusinessRecord:
    """Standardized record from 04-business-discovery-engine."""

    name: str
    industry: str | None = None
    city: str | None = None
    province: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    facebook: str | None = None
    google_business_url: str | None = None
    description: str | None = None
    source_ref: str | None = None

    @classmethod
    def from_mapping(cls, row: dict[str, object]) -> RawBusinessRecord:
        allowed = {f.name for f in fields(cls)}
        aliases = {"business_name": "name", "business_id": "source_ref"}
        data: dict[str, str | None] = {}
        for key, value in row.items():
            key = aliases.get(key.strip().lower(), key.strip().lower())
            if key in allowed:
                text = str(value).strip() if value is not None else ""
                data[key] = text or None
        if not data.get("name"):
            raise ValueError("record is missing 'name'")
        return cls(**data)  # type: ignore[arg-type]


@dataclass(frozen=True)
class InvalidRecord:
    """A source row that could not be mapped; reported per row instead of aborting the batch."""

    error: str


SourceItem = RawBusinessRecord | InvalidRecord


class BusinessSource(Protocol):
    source: DiscoverySource

    def fetch(self) -> Iterable[SourceItem]: ...


def _map_rows(rows: Iterable[object]) -> Iterator[SourceItem]:
    for row in rows:
        if not isinstance(row, dict):
            yield InvalidRecord("row is not an object")
            continue
        try:
            yield RawBusinessRecord.from_mapping(row)
        except ValueError as exc:
            yield InvalidRecord(str(exc))


class CsvSource:
    source = DiscoverySource.CSV_IMPORT

    def __init__(self, content: str) -> None:
        self._content = content

    def fetch(self) -> Iterator[SourceItem]:
        return _map_rows(csv.DictReader(io.StringIO(self._content)))


class JsonSource:
    source = DiscoverySource.CSV_IMPORT

    def __init__(self, content: str) -> None:
        self._content = content

    def fetch(self) -> Iterator[SourceItem]:
        data = json.loads(self._content)
        if not isinstance(data, list):
            raise ValueError("JSON import must be a list of business objects")
        return _map_rows(data)
