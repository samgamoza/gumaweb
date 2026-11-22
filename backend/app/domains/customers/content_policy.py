"""Which content a customer may edit in the portal, and validation of edits.

Customers edit content (not structure); layout changes stay template-driven so
sites remain consistent and re-renderable. Images are referenced by asset id
(ownership is checked by the service layer).
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import ValidationFailedError

EDITABLE_FIELDS: dict[str, dict[str, type | tuple[type, ...]]] = {
    "hero": {"headline": str, "subheadline": str, "cta_label": str, "image": (dict, type(None))},
    "about": {"heading": str, "company_story": str, "mission_statement": str, "service_summary": str},
    "services": {"heading": str, "intro": str, "items": list},
    "faq": {"heading": str, "items": list},
    "cta": {"heading": str, "text": str, "button_label": str},
    "contact": {"heading": str, "intro": str, "phone": (str, type(None)), "email": (str, type(None)),
                "address": (str, type(None))},
    "testimonials": {"heading": str, "items": list},
    "gallery": {"heading": str, "images": list},
}
MAX_TEXT = 2000
MAX_ITEMS = 30
_ITEM_FIELDS = {
    "services": {"name", "description"},
    "faq": {"question", "answer"},
    "testimonials": {"author", "quote"},
    "gallery": {"asset_id", "alt"},
}
MAX_GALLERY = 24


def validate_section_update(section_key: str, updates: dict[str, Any]) -> dict[str, Any]:
    allowed = EDITABLE_FIELDS.get(section_key)
    if allowed is None:
        raise ValidationFailedError(f"Section '{section_key}' is not editable")
    clean: dict[str, Any] = {}
    for field, value in updates.items():
        if field not in allowed:
            raise ValidationFailedError(f"Field '{field}' is not editable in '{section_key}'")
        if not isinstance(value, allowed[field]):
            raise ValidationFailedError(f"Field '{section_key}.{field}' has the wrong type")
        if isinstance(value, str):
            value = value.strip()
            if len(value) > MAX_TEXT:
                raise ValidationFailedError(f"Field '{section_key}.{field}' exceeds {MAX_TEXT} characters")
        if isinstance(value, list):
            value = _validate_items(section_key, value)
        if field == "image" and value is not None:
            value = _validate_image(value)
        clean[field] = value
    return clean


def _validate_image(value: dict[str, Any]) -> dict[str, str]:
    if not isinstance(value.get("asset_id"), str) or not set(value) <= {"asset_id", "alt"}:
        raise ValidationFailedError("Image must be {asset_id, alt}")
    return {"asset_id": value["asset_id"], "alt": str(value.get("alt", ""))[:255].strip(), "source": "upload"}


def referenced_assets(section: dict[str, Any]) -> list[str]:
    refs = [section["image"]["asset_id"]] if isinstance(section.get("image"), dict) else []
    return refs + [i["asset_id"] for i in section.get("images", []) if isinstance(i, dict)]


def _validate_items(section_key: str, items: list[Any]) -> list[dict[str, str]]:
    if len(items) > (MAX_GALLERY if section_key == "gallery" else MAX_ITEMS):
        raise ValidationFailedError(f"'{section_key}' allows at most {MAX_ITEMS} items")
    expected = _ITEM_FIELDS[section_key]
    result = []
    for item in items:
        if not isinstance(item, dict) or set(item) != expected:
            raise ValidationFailedError(f"Each '{section_key}' item needs exactly: {', '.join(sorted(expected))}")
        if not all(isinstance(v, str) and len(v) <= MAX_TEXT for v in item.values()):
            raise ValidationFailedError(f"Invalid '{section_key}' item values")
        result.append({k: v.strip() for k, v in item.items()})
    return result
