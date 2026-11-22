"""Brand kit: colours taken from the site's template palette, a monogram, and readable text colours."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SKIP = {"the", "and", "of", "&", "inc", "corp", "corporation", "co", "company", "ltd", "llc", "opc"}
DEFAULT_PRIMARY = "#1d4ed8"
DEFAULT_ACCENT = "#0f172a"
DARK_TEXT = "#111827"
LIGHT_TEXT = "#ffffff"


@dataclass(frozen=True)
class Brand:
    name: str
    initials: str
    primary: str
    accent: str
    surface: str
    text_on_primary: str  # WCAG-checked
    text_on_accent: str

    def as_dict(self) -> dict[str, str]:
        return {"initials": self.initials, "primary": self.primary, "accent": self.accent,
                "surface": self.surface, "text_on_primary": self.text_on_primary,
                "text_on_accent": self.text_on_accent}


def initials(name: str) -> str:
    """'Bella Vista Dental Clinic' -> 'BV'; 'Santos Plumbing' -> 'SP'; 'Glow' -> 'GL'."""
    words = [w for w in re.findall(r"[A-Za-z0-9]+", name) if w.lower() not in _SKIP]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def _valid(color: str | None, fallback: str) -> str:
    if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return color.lower()
    if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{3}", color):
        return "#" + "".join(c * 2 for c in color[1:]).lower()
    return fallback


def rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def luminance(color: str) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable_on(background: str) -> str:
    """White or near-black, whichever contrasts more with the background."""
    return LIGHT_TEXT if contrast(LIGHT_TEXT, background) >= contrast(DARK_TEXT, background) else DARK_TEXT


def mix(a: str, b: str, t: float = 0.5) -> str:
    ra, ga, ba = rgb(a)
    rb, gb, bb = rgb(b)
    return f"#{round(ra + (rb - ra) * t):02x}{round(ga + (gb - ga) * t):02x}{round(ba + (bb - ba) * t):02x}"


def build_brand(name: str, palette: dict[str, str]) -> Brand:
    primary = _valid(palette.get("primary"), DEFAULT_PRIMARY)
    accent = _valid(palette.get("accent"), DEFAULT_ACCENT)
    if contrast(primary, accent) < 1.3:  # gradient would look flat: darken the accent
        accent = mix(accent, "#000000", 0.45)
    surface = _valid(palette.get("surface"), "#f8fafc")
    return Brand(name=name, initials=initials(name), primary=primary, accent=accent, surface=surface,
                 text_on_primary=readable_on(primary), text_on_accent=readable_on(accent))
