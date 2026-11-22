"""Artifact storage for published sites.

Layout (identical for local disk and S3-compatible object storage):
    _releases/<subdomain>/v<version>/...   immutable build artifacts (rollback)
    <subdomain>/...                        live site served by nginx / CDN
    _d/<domain>/...                        live copy for a verified custom domain (Phase 5)
"""

from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from app.domains.presence.domains import DOMAIN_PATTERN
from app.domains.publishing.subdomain import SUBDOMAIN_RE

RELEASES_TO_KEEP = 3


@dataclass(frozen=True)
class PublishResult:
    artifact_path: str
    file_count: int
    size_bytes: int


def _safe_key(key: str) -> str:
    path = PurePosixPath(key)
    if path.is_absolute() or ".." in path.parts or not key:
        raise ValueError(f"unsafe artifact path: {key!r}")
    return path.as_posix()


def _check_subdomain(subdomain: str) -> None:
    if not SUBDOMAIN_RE.match(subdomain):
        raise ValueError(f"invalid subdomain: {subdomain!r}")


_DOMAIN_RE = re.compile(rf"^{DOMAIN_PATTERN}$")
DOMAIN_PREFIX = "_d"


def _check_domain(domain: str) -> None:
    if not _DOMAIN_RE.match(domain) or len(domain) > 253:
        raise ValueError(f"invalid domain: {domain!r}")


ASSET_PREFIX = "_assets/"


def _asset_key(key: str) -> str:
    key = _safe_key(key)
    if not key.startswith(ASSET_PREFIX):
        raise ValueError(f"asset keys must start with {ASSET_PREFIX!r}")
    return key


class SiteStorage(Protocol):
    name: str

    def publish(self, subdomain: str, version: int, files: dict[str, bytes]) -> PublishResult: ...

    def unpublish(self, subdomain: str) -> None: ...

    # Custom domains: a live copy of the site under _d/<domain>/ (nginx maps the Host header to it)
    def publish_domain(self, domain: str, files: dict[str, bytes]) -> None: ...

    def unpublish_domain(self, domain: str) -> None: ...

    # Asset library objects (images), under _assets/
    def put_object(self, key: str, data: bytes, content_type: str) -> None: ...

    def get_object(self, key: str) -> bytes: ...

    def delete_object(self, key: str) -> None: ...


class LocalSiteStorage:
    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = root

    def publish(self, subdomain: str, version: int, files: dict[str, bytes]) -> PublishResult:
        _check_subdomain(subdomain)
        release = self.root / "_releases" / subdomain / f"v{version}"
        if release.exists():
            shutil.rmtree(release)
        size = 0
        for key, data in files.items():
            target = release / _safe_key(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            size += len(data)

        self._swap(self.root / subdomain, release)
        self._prune(subdomain)
        return PublishResult(str(release.relative_to(self.root).as_posix()), len(files), size)

    def _swap(self, live: Path, source: Path) -> None:
        """Atomic-ish swap: stage a copy, then rename over the live directory."""
        tag = uuid.uuid4().hex[:8]
        staging = live.parent / f".{live.name}.staging-{tag}"
        shutil.copytree(source, staging)
        if live.exists():
            retired = live.parent / f".{live.name}.retired-{tag}"
            live.rename(retired)
            staging.rename(live)
            shutil.rmtree(retired, ignore_errors=True)
        else:
            staging.rename(live)

    def unpublish(self, subdomain: str) -> None:
        _check_subdomain(subdomain)
        shutil.rmtree(self.root / subdomain, ignore_errors=True)

    def publish_domain(self, domain: str, files: dict[str, bytes]) -> None:
        _check_domain(domain)
        build = self.root / DOMAIN_PREFIX / f".build-{domain}-{uuid.uuid4().hex[:8]}"
        try:
            for key, data in files.items():
                target = build / _safe_key(key)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            self._swap(self.root / DOMAIN_PREFIX / domain, build)
        finally:
            shutil.rmtree(build, ignore_errors=True)

    def unpublish_domain(self, domain: str) -> None:
        _check_domain(domain)
        shutil.rmtree(self.root / DOMAIN_PREFIX / domain, ignore_errors=True)

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        target = self.root / _asset_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def get_object(self, key: str) -> bytes:
        return (self.root / _asset_key(key)).read_bytes()

    def delete_object(self, key: str) -> None:
        (self.root / _asset_key(key)).unlink(missing_ok=True)

    def _prune(self, subdomain: str) -> None:
        releases_dir = self.root / "_releases" / subdomain
        releases = sorted(
            (p for p in releases_dir.iterdir() if p.name.startswith("v") and p.name[1:].isdigit()),
            key=lambda p: int(p.name[1:]),
        )
        for old in releases[:-RELEASES_TO_KEEP]:
            shutil.rmtree(old, ignore_errors=True)


class S3SiteStorage:
    """MinIO / Ceph RGW / any S3-compatible store. Requires `boto3` (requirements/prod.txt)."""

    name = "s3"

    def __init__(self, bucket: str, endpoint_url: str | None, access_key: str | None,
                 secret_key: str | None, region: str) -> None:
        import boto3

        self.bucket = bucket
        self.client = boto3.client(
            "s3", endpoint_url=endpoint_url, aws_access_key_id=access_key,
            aws_secret_access_key=secret_key, region_name=region,
        )

    @staticmethod
    def _content_type(key: str) -> str:
        return {
            ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "application/javascript",
            ".xml": "application/xml", ".txt": "text/plain", ".json": "application/json",
            ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
        }.get(PurePosixPath(key).suffix, "application/octet-stream")

    def publish(self, subdomain: str, version: int, files: dict[str, bytes]) -> PublishResult:
        _check_subdomain(subdomain)
        prefix = f"_releases/{subdomain}/v{version}/"
        size = 0
        for key, data in files.items():
            safe = _safe_key(key)
            for full_key in (prefix + safe, f"{subdomain}/{safe}"):
                self.client.put_object(
                    Bucket=self.bucket, Key=full_key, Body=data, ContentType=self._content_type(safe)
                )
            size += len(data)
        live_keys = {f"{subdomain}/{_safe_key(k)}" for k in files}
        stale = [k for k in self._list(f"{subdomain}/") if k not in live_keys]
        self._delete(stale)
        return PublishResult(prefix.rstrip("/"), len(files), size)

    def unpublish(self, subdomain: str) -> None:
        _check_subdomain(subdomain)
        self._delete(self._list(f"{subdomain}/"))

    def publish_domain(self, domain: str, files: dict[str, bytes]) -> None:
        _check_domain(domain)
        prefix = f"{DOMAIN_PREFIX}/{domain}/"
        live_keys = set()
        for key, data in files.items():
            safe = _safe_key(key)
            live_keys.add(prefix + safe)
            self.client.put_object(Bucket=self.bucket, Key=prefix + safe, Body=data,
                                   ContentType=self._content_type(safe))
        self._delete([k for k in self._list(prefix) if k not in live_keys])

    def unpublish_domain(self, domain: str) -> None:
        _check_domain(domain)
        self._delete(self._list(f"{DOMAIN_PREFIX}/{domain}/"))

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=_asset_key(key), Body=data, ContentType=content_type)

    def get_object(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=_asset_key(key))["Body"].read()

    def delete_object(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=_asset_key(key))

    def _list(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys += [obj["Key"] for obj in page.get("Contents", [])]
        return keys

    def _delete(self, keys: list[str]) -> None:
        for i in range(0, len(keys), 1000):
            batch = [{"Key": k} for k in keys[i : i + 1000]]
            if batch:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": batch})
