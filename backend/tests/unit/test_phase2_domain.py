import copy

from app.agents.content_agent import LLMContentGenerator, extract_json
from app.domains.seo.audit import audit_site
from app.domains.seo.generator import faq_schema, generate_page_meta
from app.domains.template_management.resolver import TemplateCandidate, select_template
from app.domains.website_factory.content import ContentContext
from app.domains.website_factory.content_quality import evaluate_section, fabricated_claims, spam_score
from app.domains.website_factory.enums import ContentSource
from app.domains.website_factory.images import ImageRequest, procedural_svg, sniff_image
from app.domains.website_factory.jobs import retry_delay
from tests.fakes import GOOD_COPY, FakeLLM, MemoryStore, make_png

CTX = ContentContext("Santos Plumbing", "plumbing", "Angeles City", "Pampanga", None, "639171234567", None, None,
                     ["Leak Repairs", "Pipe Installation", "Drain Cleaning"], "homes and businesses", "dependable")
KEYS = {"hero", "about", "services", "faq", "cta", "contact"}


def _generator(llm, store=None, reviewer="deepseek"):
    return LLMContentGenerator(llm, primary_model="qwen", reviewer_model=reviewer, store=store)


def test_quality_rules_flag_spam_and_fabrications():
    assert spam_score("BEST IN THE WORLD!!! Guaranteed results!") > 10
    assert spam_score("We fix leaks and clear drains.") == 0
    assert set(fabricated_claims("Award-winning team with 20 years of experience, 5-star rated")) >= {
        "awards", "years_in_business", "ratings"}
    assert fabricated_claims("Request a free consultation today.") == []
    block = {"heading": "x", "company_story": "Serving Angeles since 2009."}
    assert not evaluate_section("about", block, min_readability=0, max_spam=10).accepted
    # a "claim" present in the source facts is a fact, not a fabrication
    assert evaluate_section("about", block, min_readability=0, max_spam=10, known_facts="since 2009").accepted


def test_extract_json_tolerates_fences_and_reasoning():
    assert extract_json('<think>hmm {"a": 0}</think>Sure: ```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json("no json here") is None


def test_llm_generator_accepts_vetted_sections_and_filters_invented_services():
    llm = FakeLLM()
    result = _generator(llm).generate(CTX, KEYS)
    assert result.sources["hero"] == ContentSource.AI
    assert result.blocks["hero"]["headline"] == GOOD_COPY["hero"]["headline"]
    assert result.blocks["hero"]["cta_target"] == "contact"  # structural fields kept from the template
    names = [i["name"] for i in result.blocks["services"]["items"]]
    assert "Gold Plating" not in names and names[:2] == ["Leak Repairs", "Drain Cleaning"]
    assert "Pipe Installation" in names  # missing service keeps its template description
    assert result.sources["contact"] == ContentSource.TEMPLATE  # never sent to the model
    # one focused prompt per section, each reviewed after passing the gates
    assert [task for task, _ in llm.calls] == ["content", "review"] * 5


def test_fabricated_section_falls_back_to_template_copy():
    bad = copy.deepcopy(GOOD_COPY)
    bad["about"]["company_story"] += " With 20 years of experience, we are award-winning."
    result = _generator(FakeLLM(bad), reviewer=None).generate(CTX, KEYS)
    assert result.sources["about"] == ContentSource.TEMPLATE
    assert result.sources["hero"] == ContentSource.AI
    assert any(n.startswith("about: quality gate") for n in result.notes)


def test_model_outage_or_garbage_degrades_gracefully():
    down = _generator(FakeLLM(fail=True)).generate(CTX, KEYS)
    assert set(down.sources.values()) == {ContentSource.TEMPLATE}
    assert any("model unavailable" in n for n in down.notes)
    garbage = _generator(FakeLLM(raw="I cannot help with that")).generate(CTX, KEYS)
    assert set(garbage.sources.values()) == {ContentSource.TEMPLATE}


def test_generation_cache_avoids_repeat_calls():
    store, llm = MemoryStore(), FakeLLM()
    _generator(llm, store).generate(CTX, KEYS)
    _generator(llm, store).generate(CTX, KEYS)
    assert len(llm.calls) == 10  # second run served entirely from cache
    assert {r["task"] for r in store.rows.values()} == {"content", "review"}


def test_procedural_images_are_deterministic_and_palette_driven():
    req = ImageRequest("plumbing", "hero", {"primary": "#0369a1", "accent": "#0c2a3d"}, seed=42)
    first, second = procedural_svg(req), procedural_svg(req)
    assert first.data == second.data and b"#0369a1" in first.data and first.mime_type == "image/svg+xml"
    assert procedural_svg(ImageRequest("plumbing", "hero", {}, seed=43)).data != first.data


def test_upload_sniffing_rejects_svg_and_html():
    assert sniff_image(make_png()) == "image/png"
    assert sniff_image(b"<svg onload=alert(1)>") is None
    assert sniff_image(b"<html>") is None


def test_template_variety_is_deterministic():
    pool = [TemplateCandidate("medical-v1", "medical", 1, True, ("dental", "medical_clinic")),
            TemplateCandidate("dental-smile-v1", "medical", 1, False, ("dental",))]
    picks = {select_template(pool, "dental", "medical", variety_seed=s).slug for s in range(10)}
    assert picks == {"medical-v1", "dental-smile-v1"}
    assert select_template(pool, "dental", "medical", variety_seed=7) == select_template(
        pool, "dental", "medical", variety_seed=7)


def test_retry_backoff_grows_and_caps():
    assert retry_delay(1).total_seconds() == 30 and retry_delay(2).total_seconds() == 60
    assert retry_delay(20).total_seconds() == 3600


def test_page_meta_is_unique_per_page_and_faq_schema():
    pages = [{"slug": s, "title": t} for s, t in [("home", "Home"), ("about", "About"), ("faq", "FAQ")]]
    meta = generate_page_meta(pages, {"about": {"company_story": "We fix pipes. More text."}}, "Santos", "plumbing",
                              "Angeles", "Santos | Plumbing in Angeles", "x" * 120)
    assert len({m["title"] for m in meta.values()}) == 3 and meta["about"]["title"] == "About | Santos"
    schema = faq_schema([{"question": "Q?", "answer": "A."}])
    assert schema["@type"] == "FAQPage" and schema["mainEntity"][0]["acceptedAnswer"]["text"] == "A."


def test_seo_audit_lists_actionable_gaps_only_for_sections_the_template_has():
    blueprint = {"pages": [{"slug": "home", "sections": [{"component": "hero"}, {"component": "services"}]}]}
    audit = audit_site(blueprint=blueprint, content={"services": {"items": [{"name": "a"}]}},
                       seo={"page_title": "Short", "meta_description": "", "local_keywords": [],
                            "schema_markup": {}, "pages": {}},
                       business={"address": None, "email": None})
    keys = {g["key"] for g in audit["content_gaps"]}
    assert {"address", "services_depth", "title_length"} <= keys
    assert "photos" not in keys  # template has no gallery section
    assert audit["content_gaps"][0]["impact"] == "high" and 0 <= audit["score"] < 50


def test_readability_ignores_headlines_and_short_copy():
    """Regression (live Qwen run): title-case hero copy was scored as one run-on sentence."""
    hero = {"headline": "Masagana Bakery", "subheadline": "Warm Treats for Local Diners and Families in San Fernando",
            "cta_label": "Order Now"}
    assert evaluate_section("hero", hero, min_readability=45, max_spam=10).accepted


def test_model_answer_without_wrapper_key_is_still_used():
    """Regression: small models often return the section body without the {"hero": ...} wrapper."""
    unwrapped = FakeLLM(raw=__import__("json").dumps(GOOD_COPY["hero"]))
    result = _generator(unwrapped, reviewer=None).generate(CTX, {"hero"})
    assert result.sources["hero"] == ContentSource.AI


def test_fabricated_years_from_live_run_are_rejected():
    """Regression: qwen2.5:1.5b invented "Since 2015" for a business with no such fact."""
    bad = copy.deepcopy(GOOD_COPY)
    bad["about"]["company_story"] = ("Since 2015, Masagana Bakery has been delighting diners with homemade treats. "
                                     "We care about quality and our community in San Fernando every single day.")
    result = _generator(FakeLLM(bad), reviewer=None).generate(CTX, {"about"})
    assert result.sources["about"] == ContentSource.TEMPLATE
    assert any("unsupported claim: years_in_business" in n for n in result.notes)


def test_readability_gate_is_relative_to_template_baseline():
    """Regression: a fixed threshold rejected AI copy that read better than the template it would replace."""
    plain = copy.deepcopy(GOOD_COPY)
    plain["about"]["company_story"] = ("Santos Plumbing serves homes and businesses in Angeles City with "
                                       "professional installation, maintenance, and repair solutions delivered "
                                       "with dedication and attention to detail for every customer.")
    result = _generator(FakeLLM(plain), reviewer=None).generate(CTX, {"about"})
    assert result.sources["about"] == ContentSource.AI  # as readable as the (dense) template baseline


def test_hero_without_the_city_is_rejected_for_local_seo():
    nameless = copy.deepcopy(GOOD_COPY)
    nameless["hero"] = {"headline": "Santos Plumbing Services", "subheadline": "Friendly plumbing for every home.",
                        "cta_label": "Call Us"}
    result = _generator(FakeLLM(nameless), reviewer=None).generate(CTX, {"hero"})
    assert result.sources["hero"] == ContentSource.TEMPLATE
    assert any("local SEO" in n for n in result.notes)
