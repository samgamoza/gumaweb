"""Digital Presence Factory: builds each business's presence kit from the facts behind its website."""

from __future__ import annotations

import io
import json
import logging
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.domains.billing.entitlements import Feature, PlanUpgradeRequired, has_feature
from app.domains.business_discovery.normalization import normalize_phone
from app.domains.business_profile.industry_catalog import get_industry
from app.domains.presence.brand import Brand, build_brand
from app.domains.presence.facts import PresenceFacts
from app.domains.presence.google_business import CHECKLIST, google_business_pack
from app.domains.presence.render import ASSETS, render, spec_for
from app.domains.presence.seo_profile import seo_profile
from app.domains.presence.social import social_kit
from app.models import BookingSettings, Business, PresenceKit, Website
from app.repositories.repositories import WebsiteRepository
from app.services.entitlements import plan_for_business
from app.services.providers import providers

logger = logging.getLogger("gumaweb.presence")
PREFIX = "_assets/presence"


class PresenceService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # --- Facts -------------------------------------------------------------------------------
    def facts(self, business: Business, website: Website) -> PresenceFacts:
        content = {k: row.content for k, row in WebsiteRepository(self.db).content_map(website.id).items()}
        profile = business.profile
        industry = (profile.industry if profile else business.industry) or "general"
        services = [(i.get("name", ""), i.get("description", "")) for i in content.get("services", {}).get("items", [])
                    if i.get("name")]
        faq = [(i.get("question", ""), i.get("answer", "")) for i in content.get("faq", {}).get("items", [])
               if i.get("question") and i.get("answer")]
        booking = self.db.get(BookingSettings, business.id)
        features, _ = plan_for_business(self.db, business.id)
        # Opening hours are only stated when the owner configured them; we never assume them.
        hours = booking.weekly_hours if booking and booking.enabled and has_feature(features, Feature.BOOKING) else None
        palette = ((website.template.theme or {}).get("palette", {}) if website.template else {})
        seo = website.seo
        return PresenceFacts(
            name=business.name, industry=industry, industry_label=get_industry(industry).label,
            city=business.city, province=business.province, address=business.address,
            postal_code=business.postal_code,
            phone=normalize_phone(business.phone, self.settings.default_country_code),
            email=business.email, website_url=website.url or self.settings.site_url(website.subdomain),
            tagline=(profile.tagline if profile else None) or content.get("hero", {}).get("subheadline"),
            about=content.get("about", {}).get("company_story"),
            services=services, faq=faq, booking_enabled=hours is not None and bool(booking and booking.services),
            weekly_hours=hours, palette=palette,
            local_keywords=list(seo.local_keywords if seo else []),
            facebook_url=business.facebook, google_business_url=business.google_business_url,
            schema_markup=dict(seo.schema_markup if seo else {}),
        )

    # --- Kit ---------------------------------------------------------------------------------
    def kit_for(self, business: Business) -> PresenceKit:
        kit = self.db.query(PresenceKit).filter_by(business_id=business.id).one_or_none()
        website = business.website_record
        if kit is None or (website and kit.website_version != website.version):
            kit = self.generate(business)
        return kit

    def generate(self, business: Business) -> PresenceKit:
        website = business.website_record
        if website is None or not website.blueprint:
            raise ValidationFailedError("Generate the website first; the presence kit is built from it")
        facts = self.facts(business, website)
        brand = build_brand(facts.name, facts.palette)
        site_contact = {k: row.content for k, row in WebsiteRepository(self.db).content_map(website.id).items()} \
            .get("contact", {})
        kit = self.db.query(PresenceKit).filter_by(business_id=business.id).one_or_none()
        if kit is None:
            kit = PresenceKit(business_id=business.id, version=0, checklist={}, rendered={})
            self.db.add(kit)
        old_rendered = dict(kit.rendered or {})
        kit.version += 1
        kit.website_version = website.version
        kit.brand = brand.as_dict()
        kit.social = social_kit(facts)
        kit.google = google_business_pack(facts)
        kit.seo = seo_profile(
            facts, site_contact=site_contact, audit=website.seo.audit if website.seo else None,
            normalize_phone=lambda p: normalize_phone(p, self.settings.default_country_code))
        kit.rendered = {}
        kit.generated_at = datetime.now(UTC)
        self.db.flush()
        for key in old_rendered.values():  # images of the previous version are stale
            try:
                providers.storage.delete_object(key)
            except (FileNotFoundError, OSError) as exc:
                logger.info("stale presence asset %s already gone: %s", key, exc)
        return kit

    def _brand(self, kit: PresenceKit, business: Business) -> Brand:
        b = kit.brand
        return Brand(name=business.name, initials=b["initials"], primary=b["primary"], accent=b["accent"],
                     surface=b["surface"], text_on_primary=b["text_on_primary"], text_on_accent=b["text_on_accent"])

    # --- Entitlements -----------------------------------------------------------------------
    def tiers(self, business_id: uuid.UUID) -> dict[str, bool]:
        features, _ = plan_for_business(self.db, business_id)
        return {"basic": has_feature(features, Feature.SOCIAL_KIT), "full": has_feature(features, Feature.PRESENCE_KIT)}

    def _require_tier(self, business_id: uuid.UUID, tier: str) -> None:
        features, plan = plan_for_business(self.db, business_id)
        feature = Feature.PRESENCE_KIT if tier == "full" else Feature.SOCIAL_KIT
        if not has_feature(features, feature):
            raise PlanUpgradeRequired(f"This part of the presence kit is not included in the {plan} plan")

    # --- Images ------------------------------------------------------------------------------
    def asset_names(self, kit: PresenceKit) -> list[str]:
        return list(ASSETS) + [f"post-{p['key']}" for p in kit.social.get("posts", [])]

    def _card_text(self, kit: PresenceKit, business: Business, name: str) -> dict[str, str]:
        services_line = kit.social.get("services_line") or ""
        if name == "facebook-cover":
            return {"headline": business.name, "subline": services_line}
        if name == "google-cover":
            return {"headline": business.name,
                    "subline": ", ".join(p for p in [business.city, business.province] if p)}
        if name == "story":
            booking = any(p["key"] == "booking" for p in kit.social.get("posts", []))
            return {"headline": "Book online" if booking else "Visit our website", "subline": business.name}
        if name.startswith("post-"):
            post = next((p for p in kit.social.get("posts", []) if f"post-{p['key']}" == name), None)
            if post is None:
                raise NotFoundError("Unknown image")
            return {"headline": post["card_headline"], "subline": post["card_subline"]}
        return {}

    def asset(self, business: Business, name: str) -> bytes:
        kit = self.kit_for(business)
        spec = spec_for(name)
        if spec is None or name not in self.asset_names(kit):
            raise NotFoundError("Unknown image")
        self._require_tier(business.id, spec.tier)
        key = (kit.rendered or {}).get(name)
        if key:
            try:
                return providers.storage.get_object(key)
            except (FileNotFoundError, OSError):
                logger.info("cached presence asset %s missing; re-rendering", key)
        data = render(name, self._brand(kit, business), **self._card_text(kit, business, name))
        key = f"{PREFIX}/{business.id}/v{kit.version}/{name}.png"
        providers.storage.put_object(key, data, "image/png")
        kit.rendered = {**(kit.rendered or {}), name: key}
        self.db.commit()
        return data

    # --- Downloads and progress -----------------------------------------------------------------
    def zip_kit(self, business: Business) -> bytes:
        self._require_tier(business.id, "full")
        kit = self.kit_for(business)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in self.asset_names(kit):
                zf.writestr(f"images/{name}.png", self.asset(business, name))
            zf.writestr("social/bios.txt", "\n\n".join(f"{k.title()}:\n{v}" for k, v in kit.social["bios"].items()))
            zf.writestr("social/hashtags.txt", " ".join(kit.social["hashtags"]))
            zf.writestr("social/posts.txt", "\n\n---\n\n".join(
                f"{p['title']} (image: images/post-{p['key']}.png)\n\n{p['caption']}" for p in kit.social["posts"]))
            zf.writestr("google-business/listing.txt", _google_text(kit.google))
            zf.writestr("seo/profile.json", json.dumps(kit.seo, indent=2, ensure_ascii=False))
            zf.writestr("README.txt", README.format(name=business.name))
        return buffer.getvalue()

    def set_step(self, business: Business, step: str, done: bool) -> PresenceKit:
        if step not in {k for k, _ in CHECKLIST}:
            raise ValidationFailedError("Unknown checklist step")
        self._require_tier(business.id, "full")
        kit = self.kit_for(business)
        checklist = dict(kit.checklist or {})
        if done:
            checklist[step] = datetime.now(UTC).isoformat()
        else:
            checklist.pop(step, None)
        kit.checklist = checklist
        self.db.commit()
        return kit

    def view(self, business: Business) -> dict[str, Any]:
        """The kit as the portal sees it: locked parts are withheld, not just hidden in the UI."""
        kit = self.kit_for(business)
        self.db.commit()
        tiers = self.tiers(business.id)
        assets = [{"name": n, "label": (spec_for(n).label if n in ASSETS else "Post image"),
                   "width": spec_for(n).width, "height": spec_for(n).height, "tier": spec_for(n).tier,
                   "locked": not tiers[spec_for(n).tier]} for n in self.asset_names(kit)]
        social = dict(kit.social)
        if not tiers["full"]:
            social = {"bios": social["bios"], "hashtags": social["hashtags"], "posts": []}
        return {
            "version": kit.version, "generated_at": kit.generated_at, "brand": kit.brand, "tiers": tiers,
            "assets": assets, "social": social,
            "google": kit.google if tiers["full"] else None,
            "seo": kit.seo if tiers["full"] else None,
            "checklist": kit.checklist if tiers["full"] else {},
        }


def _google_text(g: dict[str, Any]) -> str:
    lines = [f"Business name: {g['name']}"]
    lines += [f"  ! {issue}" for issue in g.get("name_issues", [])]
    lines.append(f"Primary category: {g.get('primary_category') or '(choose the closest category)'}")
    if g.get("additional_categories"):
        lines.append("Additional categories: " + ", ".join(g["additional_categories"]))
    lines += ["", "Description:", g["description"], "", f"Website: {g['website']}"]
    lines += ["", "Opening hours:"] + (g["hours"] or ["(add your opening hours)"])
    lines += ["", "Services:"] + [f"- {s['name']}: {s['description']}" for s in g["services"]]
    lines += ["", "First updates:"] + [f"- {p['text']} [button: {p['button']}]" for p in g["posts"]]
    return "\n".join(lines) + "\n"


README = """{name} - presence kit from GumaWeb

images/        Profile picture, covers, story and post images, sized for each platform.
social/        Bios (each within the platform's limit), hashtags and a first week of posts.
google-business/  Everything to paste into your Google Business Profile.
seo/           Your canonical name/address/phone, keyword targets and where to get listed.

Review every text before posting: you know your business best.
"""
