import io

import pytest
from PIL import Image

from app.domains.business_discovery.normalization import normalize_phone
from app.domains.presence.brand import build_brand, contrast, initials
from app.domains.presence.facts import PresenceFacts, fit, format_hours, phone_display, with_utm
from app.domains.presence.google_business import description_issues, google_business_pack, name_issues
from app.domains.presence.render import ASSETS, render
from app.domains.presence.seo_profile import seo_profile
from app.domains.presence.social import BIO_LIMITS, bios, hashtags, social_kit, starter_posts


def _facts(**kw) -> PresenceFacts:
    base = dict(
        name="Bella Vista Dental Clinic", industry="dental", industry_label="Dental Clinic", city="Malolos",
        province="Bulacan", address="123 Paseo del Congreso", postal_code="3000", phone="639171234567",
        email="hello@bellavista.ph", website_url="https://bella-vista.gumaweb.io/",
        tagline="Gentle care for the whole family",
        about="We have cared for families in Malolos with gentle, modern dentistry. Call 0917 123 4567 or visit "
              "www.bellavista.ph for the best promo!",
        services=[("Dental Check-ups", "Routine examinations and cleaning."), ("Orthodontics", "Braces."),
                  ("Tooth Extraction", "Safe and comfortable extractions."), ("Cosmetic Dentistry", "Whitening.")],
        faq=[("Do you accept walk-ins?", "Yes, but appointments are prioritized.")],
        booking_enabled=True, weekly_hours={"mon": [["09:00", "17:00"]], "sat": [["09:00", "12:00"]]},
        palette={"primary": "#0e7490", "accent": "#164e63", "surface": "#ecfeff"},
    )
    return PresenceFacts(**{**base, **kw})


def test_brand_monogram_and_readable_text():
    assert initials("Bella Vista Dental Clinic") == "BV"
    assert initials("The Santos & Sons Co.") == "SS"
    assert initials("Glow") == "GL"
    pale = build_brand("Sunny Bakery", {"primary": "#fde68a", "accent": "#fef3c7"})
    assert pale.text_on_primary == "#111827"  # dark text on a pale brand colour
    assert contrast(pale.primary, pale.accent) >= 1.3  # flat palettes get a darker accent
    fallback = build_brand("X", {"primary": "not-a-colour"})
    assert fallback.primary == "#1d4ed8"


def test_bios_respect_every_platform_limit():
    f = _facts(services=[("A very long service name for testing limits", "x")] * 5)
    for platform, text in bios(f).items():
        assert 0 < len(text) <= BIO_LIMITS[platform], (platform, text)
    assert "Book online" in bios(_facts())["facebook"]
    assert "Message us" in bios(_facts(booking_enabled=False))["x"]


def test_hashtags_are_local_unique_and_capped():
    tags = hashtags(_facts())
    assert tags[:2] == ["#Malolos", "#MalolosDentist"] and "#Bulacan" in tags
    assert len(tags) == len({t.lower() for t in tags}) <= 8


def test_posts_use_only_known_facts():
    posts = {p.key: p for p in starter_posts(_facts())}
    assert {"welcome", "faq", "contact", "booking"} <= posts.keys()
    assert "utm_source=social" in posts["welcome"].caption
    no_contact = {p.key for p in starter_posts(_facts(phone=None, email=None, address=None, city=None))}
    assert "contact" not in no_contact
    assert "booking" not in {p.key for p in starter_posts(_facts(booking_enabled=False))}
    assert all(len(p.caption) <= 2200 for p in posts.values())


def test_google_pack_follows_listing_guidelines():
    pack = google_business_pack(_facts())
    assert pack["primary_category"] == "Dentist" and pack["additional_categories"] == ["Dental clinic"]
    assert len(pack["description"]) <= 750
    assert description_issues(pack["description"]) == []  # the URL, phone and "best promo" were removed
    assert "0917" not in pack["description"] and "www." not in pack["description"]
    assert pack["hours"][0] == "Monday: 9:00 AM – 5:00 PM" and "Sunday: Closed" in pack["hours"]
    assert "utm_source=google" in pack["website"]
    assert not any("0917" in p["text"] for p in pack["posts"])  # Google rejects phone numbers in posts
    assert google_business_pack(_facts(weekly_hours=None))["hours_missing"] is True
    assert google_business_pack(_facts(industry="general"))["primary_category"] is None


def test_name_policy_warnings():
    assert name_issues("Bella Vista Dental Clinic", "Malolos", ["Orthodontics"]) == []
    assert name_issues("Best Dentist Malolos - Braces", "Malolos", ["Braces"])  # stuffed name
    assert description_issues("Visit https://x.ph or call 0917 123 4567, 50% off!") == [
        "Contains a link (not allowed in the description)",
        "Contains a phone number (not allowed in the description)",
        "Promotional wording (\"% off\") is not allowed in the description"]


def test_seo_profile_flags_inconsistent_records():
    profile = seo_profile(_facts(schema_markup={"telephone": "+63 917 999 0000"}),
                          site_contact={"phone": "0917 123 4567", "address": "456 Other St"},
                          audit={"score": 72, "content_gaps": [{"key": "photos"}]},
                          normalize_phone=lambda p: normalize_phone(p))
    assert profile["nap"]["phone_local"] == "0917 123 4567"
    assert profile["nap"]["phone_international"] == "+639171234567"
    assert "address on your website differs" in " ".join(profile["consistency_issues"])
    assert "search-engine markup differs" in " ".join(profile["consistency_issues"])
    assert profile["keywords"][0] == {"phrase": "dentist malolos", "page": "Home"}
    assert {c["key"]: c["status"] for c in profile["citations"]}["google"] == "missing"
    assert profile["site_score"] == 72


def test_helpers():
    assert phone_display("639171234567") == "0917 123 4567" and phone_display("6528001234") == "+6528001234"
    assert with_utm("https://a.io/?x=1", "s", "m", "c") == "https://a.io/?x=1&utm_source=s&utm_medium=m&utm_campaign=c"
    assert fit(["way too long text here", "short"], 10) == "short"
    assert format_hours(None) == []


@pytest.mark.parametrize("name", list(ASSETS) + ["post-welcome"])
def test_images_have_platform_dimensions(name):
    brand = build_brand("Bella Vista Dental Clinic", {"primary": "#0e7490", "accent": "#164e63"})
    data = render(name, brand, headline="We're online!", subline="Bella Vista Dental Clinic")
    image = Image.open(io.BytesIO(data))
    spec = ASSETS.get(name)
    assert image.format == "PNG" and image.size == ((spec.width, spec.height) if spec else (1080, 1080))
    if name == "logo":
        assert image.mode == "RGBA" and image.getpixel((0, 0))[3] == 0  # transparent corners


def test_kit_bundle_shape():
    kit = social_kit(_facts())
    assert set(kit) == {"bios", "hashtags", "posts", "services_line"}
    assert kit["services_line"] == "Dental Check-ups, Orthodontics & Tooth Extraction"


def test_copy_quality_regressions():
    """Removing banned words left "Call or visit for the !"; truncation flattened caption line breaks."""
    description = google_business_pack(_facts())["description"]
    assert "Call or visit" not in description and "!" not in description
    assert description.endswith("Book an appointment online through our website.")
    caption = starter_posts(_facts())[1].caption
    assert "\n\nQuestions?" in caption


def test_description_does_not_repeat_the_introduction():
    """Live data: the generated about story restates the opener, so the description said it twice."""
    about = ("Bella Vista Dental Clinic is a dental clinic business in Malolos serving patients and families. We "
             "focus on dental check-ups, orthodontics, and tooth extraction, delivered with care.")
    description = google_business_pack(_facts(about=about))["description"]
    assert description.count("is a dental clinic") == 1
    assert description.startswith("Bella Vista Dental Clinic is a dental clinic business in Malolos")
    assert "We offer" not in description  # the about story already lists the services
    sparse = google_business_pack(_facts(about=None))["description"]
    assert sparse.startswith("Bella Vista Dental Clinic is a dental clinic in Malolos. We offer dental check-ups")
