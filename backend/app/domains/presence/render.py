"""Presence images rendered locally with Pillow: brand gradients, waves and fitted text.

Social platforms and Google need raster images (no SVG), at their own sizes and crops:
profile pictures are shown as circles, Facebook crops cover sides on mobile, and Stories
overlay UI at the top and bottom. Text is kept inside each format's safe zone.
Images are text-and-brand cards only: never fake photos of the business.
"""

from __future__ import annotations

import hashlib
import io
import math
import random
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from app.domains.presence.brand import Brand, contrast, mix, readable_on, rgb


@dataclass(frozen=True)
class AssetSpec:
    width: int
    height: int
    kind: str  # logo | profile | cover | post | story
    tier: str  # basic (every plan) | full (presence kit)
    label: str


ASSETS: dict[str, AssetSpec] = {
    "logo": AssetSpec(1024, 1024, "logo", "basic", "Logo (transparent PNG)"),
    "profile": AssetSpec(1080, 1080, "profile", "basic", "Profile picture (Facebook, Instagram, TikTok)"),
    "facebook-cover": AssetSpec(1640, 624, "cover", "basic", "Facebook cover"),
    "story": AssetSpec(1080, 1920, "story", "full", "Story (Instagram/Facebook)"),
    "google-logo": AssetSpec(720, 720, "profile", "full", "Google Business logo"),
    "google-cover": AssetSpec(1024, 576, "cover", "full", "Google Business cover"),
}
POST_SPEC = AssetSpec(1080, 1080, "post", "full", "Post image")


def spec_for(name: str) -> AssetSpec | None:
    return POST_SPEC if name.startswith("post-") else ASSETS.get(name)


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def _seed(*parts: str) -> random.Random:
    return random.Random(int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:4], "big"))


def _text_color(brand: Brand) -> str:
    """Readable against both ends of the gradient (the darker-contrast end decides)."""
    candidates = [brand.text_on_primary, brand.text_on_accent, "#ffffff", "#111827"]
    return max(candidates, key=lambda c: min(contrast(c, brand.primary), contrast(c, brand.accent),
                                             contrast(c, mix(brand.primary, brand.accent))))


def _background(brand: Brand, w: int, h: int, key: str) -> Image.Image:
    """Diagonal gradient (accent -> primary) with translucent waves, deterministic per asset."""
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    a, b = rgb(brand.accent), rgb(brand.primary)
    span = w + h
    for i in range(0, span, 2):  # anti-diagonal bands give a diagonal gradient cheaply
        t = i / span
        color = tuple(round(a[c] + (b[c] - a[c]) * t) for c in range(3))
        draw.line([(i, 0), (0, i)], fill=color, width=3)
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    rng = _seed(brand.name, key)
    light = rgb(brand.surface)
    for layer in range(3):
        amp, phase = rng.uniform(0.03, 0.08) * h, rng.uniform(0, math.tau)
        base = h * (0.78 + 0.08 * layer)
        freq = math.tau * (1 + 0.4 * layer)
        points = [(x, base + amp * math.sin(x / w * freq + phase)) for x in range(0, w + 20, 20)]
        od.polygon([(0, h), *points, (w, h)], fill=(*light, 26 + 12 * layer))
    return Image.alpha_composite(img.convert("RGBA"), overlay)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit(draw: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int, start: int, minimum: int,
         max_lines: int) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    size = start
    while True:
        font = _font(size)
        lines = _wrap(draw, text, font, max_w)
        height = len(lines) * size * 1.15
        widest = max((draw.textlength(line, font=font) for line in lines), default=0)
        if (len(lines) <= max_lines and height <= max_h and widest <= max_w) or size <= minimum:
            return font, lines[:max_lines]
        size = max(minimum, int(size * 0.9))


def _block(draw: ImageDraw.ImageDraw, lines: list[str], font: ImageFont.FreeTypeFont, cx: int, top: float,
           color: str, bold: bool = True) -> float:
    """Centered lines starting at `top`; returns the y below the block."""
    size = font.size
    for line in lines:
        width = draw.textlength(line, font=font)
        draw.text((cx - width / 2, top), line, font=font, fill=color,
                  stroke_width=max(1, size // 28) if bold else 0, stroke_fill=color)
        top += size * 1.15
    return top


def _monogram(brand: Brand, diameter: int, fill: str, text: str) -> Image.Image:
    scale = 4  # supersample for smooth circle edges
    big = Image.new("RGBA", (diameter * scale, diameter * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.ellipse([0, 0, diameter * scale - 1, diameter * scale - 1], fill=fill)
    font = _font(int(diameter * scale * (0.42 if len(brand.initials) <= 2 else 0.32)))
    box = d.textbbox((0, 0), brand.initials, font=font, stroke_width=diameter * scale // 60)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text(((diameter * scale - tw) / 2 - box[0], (diameter * scale - th) / 2 - box[1]), brand.initials, font=font,
           fill=text, stroke_width=diameter * scale // 60, stroke_fill=text)
    return big.resize((diameter, diameter), Image.LANCZOS)


def render(name: str, brand: Brand, *, headline: str = "", subline: str = "") -> bytes:
    spec = spec_for(name)
    if spec is None:
        raise KeyError(name)
    w, h = spec.width, spec.height
    if spec.kind == "logo":
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        img.alpha_composite(_monogram(brand, w, brand.primary, brand.text_on_primary))
        return _png(img)
    if spec.kind == "profile":
        # Shown as a circle: a solid square in the brand colour with the monogram in the central 64%.
        img = Image.new("RGBA", (w, h), (*rgb(brand.primary), 255))
        inner = int(w * 0.64)
        img.alpha_composite(_monogram(brand, inner, brand.accent if brand.accent != brand.primary else "#000000",
                                      brand.text_on_accent), ((w - inner) // 2, (h - inner) // 2))
        return _png(img)

    img = _background(brand, w, h, name)
    draw = ImageDraw.Draw(img)
    color = _text_color(brand)
    soft = mix(color, brand.primary, 0.25)
    if spec.kind == "cover":
        safe_w = int(w * 0.62)  # survives mobile side-cropping
        font, lines = _fit(draw, headline or brand.name, safe_w, int(h * 0.42), int(h * 0.2), 24, 2)
        sub_font, sub_lines = _fit(draw, subline, safe_w, int(h * 0.16), int(h * 0.075), 16, 2)
        block_h = len(lines) * font.size * 1.15 + (len(sub_lines) * sub_font.size * 1.15 + h * 0.03 if subline else 0)
        y = (h - block_h) / 2 - h * 0.06
        y = _block(draw, lines, font, w // 2, y, color)
        if subline:
            _block(draw, sub_lines, sub_font, w // 2, y + h * 0.03, soft, bold=False)
        return _png(img)

    # post / story cards
    margin = int(w * 0.1)
    top_safe, bottom_safe = (int(h * 0.14), int(h * 0.2)) if spec.kind == "story" else (int(h * 0.08), int(h * 0.1))
    badge = int(w * 0.13)
    img.alpha_composite(_monogram(brand, badge, brand.surface, brand.primary), (margin, top_safe))
    font, lines = _fit(draw, headline or brand.name, w - 2 * margin, int(h * 0.38), int(w * 0.12), 28, 4)
    block_h = len(lines) * font.size * 1.15
    y = top_safe + badge + (h - top_safe - bottom_safe - badge - block_h) / 2 - h * 0.04
    _block(draw, lines, font, w // 2, y, color)
    if subline:
        sub_font, sub_lines = _fit(draw, subline, w - 2 * margin, int(h * 0.1), int(w * 0.045), 18, 2)
        _block(draw, sub_lines, sub_font, w // 2, h - bottom_safe - len(sub_lines) * sub_font.size * 1.15, soft,
               bold=False)
    return _png(img)


def _png(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


__all__ = ["ASSETS", "POST_SPEC", "AssetSpec", "readable_on", "render", "spec_for"]
