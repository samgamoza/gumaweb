"""Image Factory (08): asset categories, prompt builder, procedural artwork, upload validation.

Honesty policy: generated images are decorative/illustrative only (hero and
section backgrounds). They are never presented as the business's own work,
staff or premises - galleries show owner-uploaded photos exclusively.
"""

from __future__ import annotations

import hashlib
import math
import random
import struct
from dataclasses import dataclass

from app.domains.business_profile.industry_catalog import get_industry

# Doc 08 asset categories per vertical; "hero" is the one used by Phase 2 templates.
ASSET_CATEGORIES: dict[str, tuple[str, ...]] = {
    "construction": ("hero", "service", "contact"),
    "medical": ("hero", "services", "waiting_room"),
    "resort": ("hero", "rooms", "amenities", "location"),
    "restaurant": ("hero", "dishes", "interior"),
    "default": ("hero", "service"),
}

_SCENES: dict[str, str] = {
    "construction": "a modern residential building under construction at golden hour, scaffolding, clean site",
    "plumbing": "clean modern bathroom with chrome fixtures, soft daylight",
    "electrical": "neatly organized electrical panel and warm interior lighting",
    "restaurant": "warm inviting Filipino restaurant table with shared dishes, shallow depth of field",
    "medical_clinic": "bright calm clinic reception with plants, natural light",
    "dental": "modern bright dental clinic treatment room, calm atmosphere",
    "legal": "elegant law office with bookshelves and a wooden desk, soft light",
    "accounting": "tidy modern office desk with documents and a laptop, natural light",
    "education": "cheerful classroom with books and colorful learning materials",
    "beauty": "serene salon interior with mirrors and soft warm lighting",
    "resort": "tropical beach resort with palm trees and clear turquoise water at sunset",
    "retail": "neatly arranged local store shelves, warm lighting",
    "auto_repair": "clean auto repair garage with a car on a lift, organized tools",
    "general": "welcoming modern small business storefront, daylight",
}

NEGATIVE_PROMPT = "text, watermark, logo, signage with words, people's faces, distorted, low quality"


@dataclass(frozen=True)
class ImageRequest:
    industry: str
    category: str
    palette: dict[str, str]
    seed: int
    width: int = 1600
    height: int = 900


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    mime_type: str
    width: int
    height: int
    model: str


def image_prompt(industry: str, category: str, city: str | None = None) -> str:
    """Location- and industry-specific prompt; no business names (images are reusable across businesses)."""
    scene = _SCENES.get(industry, _SCENES["general"])
    label = get_industry(industry).label.lower()
    place = " in the Philippines" if not city else " in a Philippine town"
    return (f"Professional website {category} photograph for a {label} business{place}: {scene}. "
            "Photorealistic, high quality, natural colors, wide composition with negative space.")


def asset_seed(*parts: str) -> int:
    return int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:4], "big")


def _hex(color: str, fallback: str) -> str:
    return color if isinstance(color, str) and color.startswith("#") and len(color) in (4, 7) else fallback


def procedural_svg(req: ImageRequest) -> GeneratedImage:
    """Deterministic abstract artwork in the template palette - zero inference cost."""
    rng = random.Random(req.seed)
    w, h = req.width, req.height
    primary = _hex(req.palette.get("primary", ""), "#1d4ed8")
    accent = _hex(req.palette.get("accent", ""), "#0f172a")
    surface = _hex(req.palette.get("surface", ""), "#f5f7fa")
    shapes = []
    for i in range(7):  # soft orbs
        r = rng.randint(h // 6, h // 2)
        shapes.append(
            f'<circle cx="{rng.randint(0, w)}" cy="{rng.randint(0, h)}" r="{r}" '
            f'fill="{primary if i % 2 else surface}" opacity="{rng.uniform(0.08, 0.22):.2f}"/>'
        )
    for layer in range(3):  # flowing waves
        amp, phase, base = rng.randint(30, 90), rng.uniform(0, math.tau), h * (0.55 + 0.13 * layer)
        points = " ".join(
            f"L{x},{base + amp * math.sin(x / w * math.tau * (1 + layer * 0.5) + phase):.1f}"
            for x in range(0, w + 40, 40)
        )
        shapes.append(f'<path d="M0,{h} {points} L{w},{h} Z" fill="{primary}" opacity="{0.18 + layer * 0.12:.2f}"/>')
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'preserveAspectRatio="xMidYMid slice" role="img" aria-hidden="true">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{accent}"/><stop offset="1" stop-color="{primary}"/></linearGradient></defs>'
        f'<rect width="{w}" height="{h}" fill="url(#g)"/>{"".join(shapes)}</svg>'
    )
    return GeneratedImage(svg.encode(), "image/svg+xml", w, h, "procedural-v1")


# --- Upload validation ------------------------------------------------------------------------
UPLOAD_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
EXTENSIONS = {**{v: k for k, v in UPLOAD_TYPES.items()}, "svg": "image/svg+xml"}


def sniff_image(data: bytes) -> str | None:
    """Identify raster images by magic bytes. SVG uploads are refused (script injection risk)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_dimensions(data: bytes, mime: str) -> tuple[int | None, int | None]:
    try:
        if mime == "image/png":
            return struct.unpack(">II", data[16:24])
        if mime == "image/jpeg":
            i = 2
            while i < len(data):
                marker, length = data[i + 1], struct.unpack(">H", data[i + 2: i + 4])[0]
                if marker in (0xC0, 0xC1, 0xC2):
                    h, w = struct.unpack(">HH", data[i + 5: i + 9])
                    return w, h
                i += 2 + length
    except (struct.error, IndexError):
        pass
    return None, None
