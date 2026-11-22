import json
from datetime import UTC, date, datetime, timedelta

import pytest

from app.agents.chat_agent import ChatAgent
from app.core.exceptions import ValidationFailedError
from app.domains.billing.entitlements import Feature, PlanUpgradeRequired, has_feature, require
from app.domains.billing.plans import PLAN_CATALOG
from app.domains.booking.availability import BookingRules, available_slots, is_bookable, validate_rules
from app.domains.chatbot.guardrails import clean_message, extract_contact, unsupported_claims
from app.domains.chatbot.knowledge import KnowledgeItem, bm25_rank, entries_from_content
from app.services.crm_service import _csv_safe
from tests.fakes import FakeLLM

RULES = BookingRules()  # Asia/Manila, Mon-Fri 09-17, Sat 09-12, Sun closed, 30 min slots, 2 h lead time
NOW = datetime(2026, 11, 23, 0, 0, tzinfo=UTC)  # Monday 08:00 in Manila
MONDAY = date(2026, 11, 23)


def test_slots_respect_hours_lead_time_and_duration():
    slots = available_slots(RULES, MONDAY, 60, [], NOW)
    local = [s.strftime("%H:%M") for s in slots]
    assert local[0] == "10:00"  # 08:00 now + 2 h lead time
    assert local[-1] == "16:00"  # a 60-minute service must end by 17:00
    assert all(s.tzinfo is not None for s in slots)


def test_busy_times_and_buffer_block_overlapping_slots():
    tue = MONDAY + timedelta(days=1)
    busy_start = datetime(2026, 11, 24, 2, 0, tzinfo=UTC)  # 10:00 Manila
    busy = [(busy_start, busy_start + timedelta(minutes=30))]
    plain = {s.strftime("%H:%M") for s in available_slots(RULES, tue, 30, busy, NOW)}
    assert "10:00" not in plain and "09:30" in plain and "10:30" in plain
    buffered = BookingRules(buffer_minutes=15)
    with_buffer = {s.strftime("%H:%M") for s in available_slots(buffered, tue, 30, busy, NOW)}
    assert "09:30" not in with_buffer and "10:30" not in with_buffer and "11:00" in with_buffer


def test_closed_days_past_days_and_window():
    assert available_slots(RULES, date(2026, 11, 29), 30, [], NOW) == []  # Sunday
    assert available_slots(RULES, MONDAY - timedelta(days=1), 30, [], NOW) == []
    assert available_slots(RULES, MONDAY + timedelta(days=60), 30, [], NOW) == []
    sat = [s.strftime("%H:%M") for s in available_slots(RULES, date(2026, 11, 28), 30, [], NOW)]
    assert sat[0] == "09:00" and sat[-1] == "11:30"


def test_is_bookable_requires_an_exact_free_slot():
    tue10 = datetime(2026, 11, 24, 10, 0, tzinfo=RULES.tz)
    assert is_bookable(RULES, tue10, 30, [], NOW)
    assert not is_bookable(RULES, tue10 + timedelta(minutes=7), 30, [], NOW)  # off-grid
    assert not is_bookable(RULES, tue10.replace(tzinfo=None), 30, [], NOW)  # naive


def test_rule_validation():
    with pytest.raises(ValidationFailedError):
        validate_rules(BookingRules(timezone="Mars/Olympus"))
    with pytest.raises(ValidationFailedError):
        validate_rules(BookingRules(weekly_hours={"mon": [["17:00", "09:00"]]}))
    with pytest.raises(ValidationFailedError):
        validate_rules(BookingRules(weekly_hours={"funday": []}))


KB = [
    KnowledgeItem("1", "What are your business hours?", "We are open Monday to Friday, 9 AM to 5 PM."),
    KnowledgeItem("2", "Do you offer emergency repairs?",
                  "Call us directly and we will advise on the fastest schedule."),
    KnowledgeItem("3", "Leak Repairs", "Fast detection and repair of leaking pipes and fixtures."),
]


def test_bm25_finds_the_relevant_entry():
    assert bm25_rank("when are you open? business hours", KB)[0][1].id == "1"
    assert bm25_rank("my pipe is leaking", KB)[0][1].id == "3"
    assert bm25_rank("zebra quantum", KB) == []


def test_knowledge_built_from_website_content():
    entries = entries_from_content("Santos Plumbing", {
        "faq": {"items": [{"question": "Q?", "answer": "A."}]},
        "services": {"items": [{"name": "Leak Repairs", "description": "Fix leaks."}]},
    }, {"phone": "639171234567", "city": "Angeles City"})
    titles = [e["title"] for e in entries]
    assert "Q?" in titles and "Leak Repairs" in titles
    assert any("+639171234567" in e["content"] for e in entries if e["section"] == "contact")


def test_lead_extraction_and_input_cleaning():
    found = extract_contact("Hi, my name is Maria Santos, call me at 0917 123 4567 or maria@example.ph")
    assert found == {"email": "maria@example.ph", "phone": "0917 123 4567", "name": "Maria Santos"}
    assert extract_contact("do you fix toilets?") == {}
    assert len(clean_message("x" * 5000)) == 1000 and clean_message("a\x00b") == "ab"


def test_unsupported_claims_detection():
    assert unsupported_claims("It costs ₱500 and we're award-winning.", "We fix leaks.") == ["awards", "prices"]
    assert unsupported_claims("Free consultation available.", "free consultation") == []


def _agent(llm=None):
    return ChatAgent(llm, "qwen" if llm else None)


def _ask(agent, question):
    return agent.answer(business="Santos", question=question, history=[], knowledge=KB, greeting="Hello!",
                        handoff="Leave your details.")


def test_chat_greeting_handoff_and_retrieval_without_ai():
    agent = _agent()
    assert _ask(agent, "Hi!").strategy == "greeting"
    assert _ask(agent, "Do you sell bicycles in Antarctica?").strategy == "handoff"
    answer = _ask(agent, "what are your business hours")
    assert answer.strategy == "retrieval" and "Monday to Friday" in answer.text


def test_chat_llm_answer_is_grounded_and_guarded():
    good = FakeLLM(raw=json.dumps({"answer": "We're open weekdays from 9 to 5.", "used": [1], "unknown": False}))
    answer = _ask(_agent(good), "what are your hours")
    assert answer.strategy == "llm" and answer.sources == ["1"] and answer.prompt_tokens == 500
    system_prompt_mentions_rules = good.calls[0][0] == "content"
    assert system_prompt_mentions_rules

    unknown = FakeLLM(raw=json.dumps({"unknown": True}))
    assert _ask(_agent(unknown), "what are your hours").strategy == "handoff"

    invented = FakeLLM(raw=json.dumps({"answer": "We are open 24/7 and a check-up costs ₱300.", "used": [1]}))
    guarded = _ask(_agent(invented), "what are your hours")
    assert guarded.strategy == "retrieval" and "₱" not in guarded.text

    down = FakeLLM(fail=True)
    assert _ask(_agent(down), "what are your hours").strategy == "retrieval"


def test_entitlements_follow_the_plan_ladder():
    features = {p["code"].value: p["features"] for p in PLAN_CATALOG}
    assert not has_feature(features["free"], Feature.CRM) and not has_feature(features["professional"], Feature.BOOKING)
    assert has_feature(features["business"], Feature.CRM) and has_feature(features["business"], Feature.BOOKING)
    assert not has_feature(features["business"], Feature.AI_CHATBOT)
    assert has_feature(features["ai"], Feature.AI_CHATBOT) and has_feature(features["ai"], Feature.CRM)
    with pytest.raises(PlanUpgradeRequired):
        require(features["free"], Feature.CRM, "Free")


def test_csv_export_neutralizes_formulas():
    assert _csv_safe("=HYPERLINK(\"http://evil\")").startswith("'=")
    assert _csv_safe("+639171234567") == "'+639171234567"
    assert _csv_safe("Maria") == "Maria"


def test_name_capture_is_case_insensitive_on_the_trigger_phrase():
    """Regression: "My name is ..." at the start of a sentence was not captured."""
    assert extract_contact("My name is Lito Cruz, 0917 222 3333")["name"] == "Lito Cruz"
