"""Asset library (08): generate once, reuse thousands of times; plus the customer media library (12)."""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.image_client import ProceduralImageGenerator, build_image_generator
from app.core.config import Settings
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.domains.website_factory.images import (
    EXTENSIONS,
    UPLOAD_TYPES,
    ImageRequest,
    asset_seed,
    image_dimensions,
    sniff_image,
)
from app.models import Business, MediaAsset
from app.services.providers import providers

logger = logging.getLogger("gumaweb.assets")

LIBRARY_PREFIX = "_assets/library"
UPLOAD_PREFIX = "_assets/business"


def extension_for(mime: str) -> str:
    return next((ext for ext, m in EXTENSIONS.items() if m == mime), "bin")


class AssetService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # --- Library (generated, shared across businesses) ---------------------------------------
    def library_image(self, *, industry: str, category: str, palette: dict[str, str], style: str,
                      variety_seed: str) -> MediaAsset:
        """Return a library image, generating it only the first time a (style, variant) is needed.

        Procedural art is styled per template palette (`style` = template slug); photographic
        images from the GPU server are palette-independent (`style` = model)."""
        generator = build_image_generator(self.settings)
        if generator.name == "http":
            style = self.settings.image_model.rsplit("/", 1)[-1].lower()
        variant = asset_seed(variety_seed) % max(1, self.settings.image_library_variants)
        key_stem = f"{LIBRARY_PREFIX}/{industry}/{category}/{style}-{variant}"
        existing = self.db.scalar(select(MediaAsset).where(MediaAsset.storage_key.like(f"{key_stem}.%")))
        if existing:
            existing.usage_count += 1
            return existing

        req = ImageRequest(industry=industry, category=category, palette=palette,
                           seed=asset_seed(industry, category, style, str(variant)))
        try:
            image = generator.generate(req)
        except Exception as exc:  # GPU server down: never block site generation on imagery
            logger.warning("image generation via %s failed (%s); using procedural art", generator.name, exc)
            image = ProceduralImageGenerator().generate(req)
            key_stem = f"{LIBRARY_PREFIX}/{industry}/{category}/{style}-{variant}-fallback"
        key = f"{key_stem}.{extension_for(image.mime_type)}"
        providers.storage.put_object(key, image.data, image.mime_type)
        asset = MediaAsset(
            business_id=None, industry=industry, category=category, storage_key=key, mime_type=image.mime_type,
            sha256=hashlib.sha256(image.data).hexdigest(), size_bytes=len(image.data), width=image.width,
            height=image.height, tags=[style, image.model], alt_text="", source="generated",
            quality_score=80 if image.model.startswith("procedural") else None, usage_count=1,
        )
        self.db.add(asset)
        self.db.flush()
        return asset

    # --- Customer media library ---------------------------------------------------------------
    def upload(self, business: Business, data: bytes, alt_text: str | None) -> MediaAsset:
        if len(data) > self.settings.max_upload_mb * 1024 * 1024:
            raise ValidationFailedError(f"Images must be {self.settings.max_upload_mb} MB or smaller")
        mime = sniff_image(data)
        if mime is None:
            raise ValidationFailedError("Upload a JPEG, PNG or WebP image")
        digest = hashlib.sha256(data).hexdigest()
        duplicate = self.db.scalar(select(MediaAsset).where(MediaAsset.business_id == business.id,
                                                            MediaAsset.sha256 == digest))
        if duplicate:
            return duplicate
        width, height = image_dimensions(data, mime)
        key = f"{UPLOAD_PREFIX}/{business.id}/{uuid.uuid4().hex}.{UPLOAD_TYPES[mime]}"
        providers.storage.put_object(key, data, mime)
        asset = MediaAsset(business_id=business.id, industry=business.industry, category="upload",
                           storage_key=key, mime_type=mime, sha256=digest, size_bytes=len(data), width=width,
                           height=height, alt_text=(alt_text or "")[:255], source="upload")
        self.db.add(asset)
        self.db.commit()
        return asset

    def uploads(self, business: Business) -> Sequence[MediaAsset]:
        return self.db.scalars(
            select(MediaAsset).where(MediaAsset.business_id == business.id, MediaAsset.source == "upload")
            .order_by(MediaAsset.created_at.desc())
        ).all()

    def delete_upload(self, business: Business, asset_id: uuid.UUID) -> MediaAsset:
        asset = self.db.get(MediaAsset, asset_id)
        if asset is None or asset.business_id != business.id:
            raise NotFoundError("Image not found")
        providers.storage.delete_object(asset.storage_key)
        self.db.delete(asset)
        return asset

    def ensure_usable(self, business_id: uuid.UUID, asset_ids: Iterable[str]) -> None:
        """Content may reference the shared library or the business's own uploads only."""
        for raw in asset_ids:
            try:
                asset = self.db.get(MediaAsset, uuid.UUID(str(raw)))
            except ValueError:
                asset = None
            if asset is None or asset.business_id not in (None, business_id):
                raise ValidationFailedError(f"Unknown image {raw}")

    def load(self, asset_ids: Iterable[str]) -> dict[str, tuple[MediaAsset, bytes]]:
        resolved: dict[str, tuple[MediaAsset, bytes]] = {}
        for raw in set(asset_ids):
            try:
                asset = self.db.get(MediaAsset, uuid.UUID(str(raw)))
                if asset is not None:
                    resolved[str(raw)] = (asset, providers.storage.get_object(asset.storage_key))
            except (ValueError, FileNotFoundError, OSError) as exc:
                logger.warning("asset %s unavailable: %s", raw, exc)
        return resolved
