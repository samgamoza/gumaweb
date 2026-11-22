from pathlib import Path

import pytest

from app.core.config import REPO_ROOT
from app.core.exceptions import ValidationFailedError
from app.domains.business_profile.profiler import ProfileInput, build_profile
from app.domains.customers.content_policy import validate_section_update
from app.domains.publishing.renderer import RenderContext, SiteRenderer, theme_css_variables
from app.domains.publishing.storage import LocalSiteStorage
from app.domains.publishing.subdomain import is_valid_subdomain, subdomain_candidates
from app.domains.seo.generator import SeoInput, generate_seo
from app.domains.template_management.manifest import load_manifests
from app.domains.template_management.resolver import TemplateCandidate, select_template
from app.domains.website_factory.blueprint import BlueprintBusiness, BlueprintTemplate, build_blueprint, content_keys
from app.domains.website_factory.content import ContentContext, TemplateContentGenerator
from app.domains.website_factory.quality import validate_site

TEMPLATES = REPO_ROOT / "templates"


@pytest.mark.parametrize(
    ("name", "hint", "industry", "category"),
    [
        ("ABC Construction", None, "construction", "construction"),
        ("Bella Vista Dental Clinic", None, "dental", "medical"),
        ("Lola Nena's Kitchen", None, "restaurant", "restaurant"),
        ("Juan Dela Cruz", "plumbing", "plumbing", "construction"),
        ("Zeta Holdings", None, "general", "general"),
    ],
)
def test_profiler_classifies(name, hint, industry, category):
    profile = build_profile(ProfileInput(name=name, city="San Fernando", province="Pampanga", industry_hint=hint))
    assert (profile.industry, profile.category) == (industry, category)
    assert profile.services and profile.local_keywords


def test_template_resolution_priority():
    candidates = [
        TemplateCandidate("construction-v1", "construction", 1, True, ("construction",)),
        TemplateCandidate("plumbing-modern-v1", "construction", 1, False, ("plumbing",)),
        TemplateCandidate("general-v1", "general", 1, True, ("general",)),
    ]
    assert select_template(candidates, "plumbing", "construction").slug == "plumbing-modern-v1"
    assert select_template(candidates, "electrical", "construction").slug == "construction-v1"
    assert select_template(candidates, "dental", "medical").slug == "general-v1"
    assert select_template(candidates, "x", "y", requested_slug="nope") is None


def _site_for(manifest, industry: str):
    blueprint = build_blueprint(
        subdomain="demo",
        business=BlueprintBusiness("Demo Biz", industry, "Demo", "Angeles City", "Pampanga", None,
                                   "639171234567", "demo@gmail.com", None),
        template=BlueprintTemplate(manifest.slug, manifest.version, manifest.category, manifest.pages,
                                   manifest.theme),
        services=["Leak Repairs", "Drain Cleaning"], brand_tone="dependable", claimed=False,
    )
    ctx = ContentContext("Demo Biz", industry, "Angeles City", "Pampanga", None, "639171234567",
                         "demo@gmail.com", None, ["Leak Repairs", "Drain Cleaning"], None, None)
    content = TemplateContentGenerator().generate(ctx, content_keys(blueprint)).blocks
    seo = generate_seo(SeoInput("Demo Biz", industry, "Angeles City", "Pampanga", None, "639171234567",
                                "demo@gmail.com", None, ["Leak Repairs"], ["plumbing"], ["plumbing near me"],
                                "http://sites.test/demo/"))
    return blueprint, content, seo


@pytest.mark.parametrize("manifest", load_manifests(TEMPLATES), ids=lambda m: m.slug)
def test_every_template_renders_and_passes_quality(manifest):
    renderer = SiteRenderer(TEMPLATES)
    blueprint, content, seo = _site_for(manifest, (manifest.industries or ["general"])[0])
    report = validate_site(blueprint, content, seo, renderer.available_components())
    assert report.publishable, report.issues
    files = renderer.render(RenderContext("id", blueprint, content, seo, "http://sites.test/demo/",
                                          "http://api.test", "http://portal.test/claim/demo", 1))
    assert {"index.html", "about/index.html", "contact/index.html", "sitemap.xml", "robots.txt"} <= files.keys()
    home = files["index.html"].decode()
    assert "Claim this website" in home and "application/ld+json" in home
    assert 'href="../assets/site.css"' in files["about/index.html"].decode()


def test_faq_meets_minimum_entries():
    ctx = ContentContext("Demo", "plumbing", "Angeles", None, None, None, None, None, ["Leak Repairs"], None, None)
    faq = TemplateContentGenerator().generate(ctx, {"faq"}).blocks["faq"]["items"]
    assert len(faq) >= 9 and all(item["question"] and item["answer"] for item in faq)


def test_content_never_fabricates_testimonials():
    ctx = ContentContext("Demo", "dental", None, None, None, None, None, None, [], None, None)
    assert TemplateContentGenerator().generate(ctx, {"testimonials"}).blocks["testimonials"]["items"] == []


def test_html_is_escaped():
    manifest = load_manifests(TEMPLATES)[0]
    blueprint, content, seo = _site_for(manifest, "construction")
    content["hero"]["headline"] = "<script>alert(1)</script>"
    files = SiteRenderer(TEMPLATES).render(RenderContext("id", blueprint, content, seo, "http://s/", "http://a",
                                                         "http://c", 1))
    assert "<script>alert(1)</script>" not in files["index.html"].decode()


def test_theme_css_rejects_injection():
    css = theme_css_variables({"palette": {"primary": "red;}</style><script>", "accent": "#112233"},
                               "fonts": {"body": "x{}"}})
    assert "script" not in css and "--color-accent: #112233;" in css and "--font-body" not in css


def test_seo_lengths_within_limits():
    seo = generate_seo(SeoInput("A Very Long Business Name Construction And Supply Company", "construction",
                                "San Fernando", "Pampanga", None, "639171234567", None, None,
                                ["General Construction", "Roofing"], ["construction"], [], "http://s/"))
    assert len(seo["page_title"]) <= 60 and 50 <= len(seo["meta_description"]) <= 160
    assert seo["schema_markup"]["@type"] == "HomeAndConstructionBusiness"


def test_subdomains():
    assert not is_valid_subdomain("admin") and is_valid_subdomain("abc-plumbing")
    candidates = subdomain_candidates("admin", "Angeles")
    assert next(candidates) == "admin-site"


def test_local_storage_swaps_and_prunes(tmp_path: Path):
    storage = LocalSiteStorage(tmp_path)
    for version in range(1, 6):
        storage.publish("demo", version, {"index.html": f"v{version}".encode()})
    assert (tmp_path / "demo" / "index.html").read_text() == "v5"
    assert sorted(p.name for p in (tmp_path / "_releases" / "demo").iterdir()) == ["v3", "v4", "v5"]
    with pytest.raises(ValueError):
        storage.publish("demo", 6, {"../escape.html": b"x"})
    storage.unpublish("demo")
    assert not (tmp_path / "demo").exists()


def test_content_policy():
    assert validate_section_update("hero", {"headline": "  Hi  "}) == {"headline": "Hi"}
    with pytest.raises(ValidationFailedError):
        validate_section_update("hero", {"html": "<b>"})
    with pytest.raises(ValidationFailedError):
        validate_section_update("faq", {"items": [{"question": "q"}]})
