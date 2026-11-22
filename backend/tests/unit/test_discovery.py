from app.domains.business_discovery.normalization import (
    build_dedupe_key,
    is_free_email,
    is_real_website,
    normalize_email,
    normalize_name_key,
    normalize_phone,
    normalize_url,
    slugify,
)
from app.domains.business_discovery.scoring import ScoringInput, score_business
from app.domains.business_discovery.sources import CsvSource, InvalidRecord


def test_name_key_strips_legal_suffixes_and_punctuation():
    assert normalize_name_key("ABC Construction, Inc.") == "abc construction"
    assert normalize_name_key("The Reyes & Co.") == "reyes"


def test_phone_normalization_ph_formats():
    assert normalize_phone("0917 123 4567") == "639171234567"
    assert normalize_phone("+63 917-123-4567") == "639171234567"
    assert normalize_phone("9171234567") == "639171234567"
    assert normalize_phone("abc") is None


def test_email_and_url_normalization():
    assert normalize_email(" Info@Example.COM ") == "info@example.com"
    assert normalize_email("not-an-email") is None
    assert normalize_url("example.com/") == "https://example.com"
    assert is_free_email("x@gmail.com") and not is_free_email("x@acme.ph")
    assert not is_real_website("https://www.facebook.com/acme")
    assert is_real_website("https://acme.ph")


def test_slugify_is_dns_safe():
    slug = slugify("Lola Nena's Kitchen & Café!!")
    assert slug == "lola-nena-s-kitchen-cafe"
    assert len(slugify("x" * 200)) <= 63


def test_dedupe_key_matches_variants():
    assert build_dedupe_key("ABC Construction Inc.", "San Fernando", None) == build_dedupe_key(
        "abc construction", "SAN FERNANDO", None
    )


def test_score_ideal_candidate():
    result = score_business(ScoringInput(website=None, email="a@gmail.com", phone="639171234567",
                                         facebook="https://facebook.com/a", industry_value=90))
    assert result.score == 98
    assert result.generate_candidate
    assert result.breakdown["website_missing"] == 35


def test_business_with_website_is_never_a_candidate():
    result = score_business(ScoringInput(website="https://acme.ph", email="info@acme.ph", phone="63917",
                                         facebook=None, industry_value=100))
    assert not result.generate_candidate
    assert "website_missing" not in result.breakdown and "domain_missing" not in result.breakdown


def test_unreachable_business_is_not_a_candidate():
    result = score_business(ScoringInput(website=None, email=None, phone=None,
                                         facebook="https://facebook.com/a", industry_value=100))
    assert not result.generate_candidate
    assert "No reachable contact information" in result.reasons


def test_csv_source_maps_aliases():
    records = list(CsvSource("business_name,city,phone\nABC Construction,San Fernando,0917\n,X,\n").fetch())
    assert records[0].name == "ABC Construction" and records[0].city == "San Fernando"
    assert isinstance(records[1], InvalidRecord)
