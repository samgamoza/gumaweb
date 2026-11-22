from datetime import UTC, date, datetime, timedelta

import pytest
from jinja2.exceptions import SecurityError

from app.core.exceptions import ValidationFailedError
from app.domains.automation.rules import PRESETS, Trigger, matches, render, validate_rule
from app.domains.crm.enums import ActivityType, ContactSource, ContactStage
from app.domains.crm.scoring import Touch, score_lead
from app.domains.integrations.webhooks import (
    API_KEY_PREFIX,
    endpoint_secret,
    generate_api_key,
    hash_api_key,
    sign,
    validate_webhook_url,
    verify,
)
from app.domains.voice.dialog import Action, CallOutcome, classify, greeting, parse_day, pick_slot, step

NOW = datetime(2026, 11, 23, 2, 0, tzinfo=UTC)


def _score(**kw):
    base = dict(source=ContactSource.CONTACT_FORM, stage=ContactStage.NEW, has_email=True, has_phone=False,
                touches=[], value_cents=None, now=NOW)
    return score_lead(**{**base, **kw})


def test_lead_scoring_rewards_intent_engagement_and_recency():
    cold = _score(touches=[Touch(ActivityType.FORM_SUBMISSION, "hello", NOW - timedelta(days=40))])
    assert cold.temperature == "cold" and any("over 30 days" in r for r in cold.reasons)
    hot = _score(source=ContactSource.BOOKING, has_phone=True, touches=[
        Touch(ActivityType.BOOKING, "Booked check-up", NOW - timedelta(hours=2)),
        Touch(ActivityType.CHAT, "magkano po ang braces? urgent", NOW - timedelta(hours=1)),
    ])
    assert hot.temperature == "hot" and hot.score >= 70
    assert any("buying intent" in r for r in hot.reasons) and any("last 2 days" in r for r in hot.reasons)


def test_closed_stages_short_circuit():
    assert _score(stage=ContactStage.WON).temperature == "customer"
    assert _score(stage=ContactStage.LOST).score == 0


def test_rule_validation_and_matching():
    validate_rule(Trigger.LEAD_CAPTURED, {}, {"sources": ["chatbot"]},
                  [{"type": "notify_owner", "subject": "Hi {{ contact.name }}", "body": "x"}])
    with pytest.raises(ValidationFailedError):
        validate_rule(Trigger.APPOINTMENT_REMINDER, {}, {}, [{"type": "notify_owner", "subject": "s", "body": "b"}])
    with pytest.raises(ValidationFailedError):
        validate_rule(Trigger.LEAD_CAPTURED, {}, {}, [{"type": "launch_rockets"}])
    with pytest.raises(ValidationFailedError):
        validate_rule(Trigger.LEAD_CAPTURED, {}, {}, [{"type": "email_contact", "subject": "{{ oops", "body": "b"}])
    with pytest.raises(ValidationFailedError):
        validate_rule(Trigger.LEAD_CAPTURED, {"x": 1}, {"weather": "sunny"}, [{"type": "add_tag", "tag": "t"}])
    for preset in PRESETS:
        validate_rule(preset["trigger"], preset["config"], preset["conditions"], preset["actions"])

    ctx = {"contact": {"source": "chatbot", "stage": "new", "lead_score": 80}}
    assert matches({"sources": ["chatbot"], "min_score": 70}, ctx)
    assert not matches({"sources": ["booking"]}, ctx) and not matches({"min_score": 90}, ctx)


def test_templates_render_in_a_sandbox():
    assert render("Hi {{ contact.first_name }}!", {"contact": {"first_name": "Ana"}}) == "Hi Ana!"
    with pytest.raises(SecurityError):
        render("{{ ''.__class__.__mro__[1].__subclasses__() }}", {})


def test_webhook_signatures_and_secrets():
    secret = endpoint_secret("server-key", "endpoint-1", 1)
    assert secret.startswith("whsec_") and secret != endpoint_secret("server-key", "endpoint-1", 2)
    body = b'{"type":"lead.captured"}'
    header = sign(secret, body, timestamp=1_700_000_000)
    assert verify(secret, body, header, now=1_700_000_100)
    assert not verify(secret, body + b" ", header, now=1_700_000_100)  # tampered
    assert not verify(secret, body, header, now=1_700_009_999)  # replayed too late
    key = generate_api_key()
    assert key.startswith(API_KEY_PREFIX) and len(hash_api_key(key)) == 64


def test_webhook_urls_block_internal_targets():
    for url in ("http://127.0.0.1:8000/x", "http://169.254.169.254/latest/meta-data", "http://10.0.0.5/hook",
                "http://localhost/hook", "ftp://example.com", "https://user:pw@example.com/h"):
        with pytest.raises(ValidationFailedError):
            validate_webhook_url(url, allow_private=False, require_https=False)
    with pytest.raises(ValidationFailedError):
        validate_webhook_url("http://example.com/hook", allow_private=True, require_https=True)
    assert validate_webhook_url("http://localhost:9000/h", allow_private=True, require_https=False)


class FakePorts:
    business_name = "Bella Vista Dental"
    forward_number = "639170000000"
    today = date(2026, 11, 23)  # Monday

    def __init__(self, services=None):
        self.booking_services = services if services is not None else [{"name": "Check-up", "duration_minutes": 30}]
        self.booked = []

    def slots(self, day, service):
        base = datetime(day.year, day.month, day.day, 9, 0)
        return [base + timedelta(minutes=30 * i) for i in range(6)]

    def book(self, service, start, name):
        self.booked.append((service, start, name))
        return None

    def answer(self, question):
        if "hours" in question:
            return "We're open weekdays 9 to 5.", False
        return "", True


def test_intent_classification_and_parsing():
    assert classify("I'd like to book an appointment") == "booking"
    assert classify("can I talk to a person") == "human"
    assert classify("please take a message") == "message"
    assert classify("okay bye") == "goodbye"
    assert parse_day("tomorrow please", date(2026, 11, 23)) == date(2026, 11, 24)
    assert parse_day("next friday", date(2026, 11, 23)) == date(2026, 11, 27)
    assert parse_day("monday", date(2026, 11, 23)) == date(2026, 11, 30)  # "monday" on a Monday = next week
    offered = [datetime(2026, 11, 24, 9), datetime(2026, 11, 24, 9, 30), datetime(2026, 11, 24, 14)]
    assert pick_slot("the second one", offered) == offered[1]
    assert pick_slot("2 pm works", offered) == offered[2]
    assert pick_slot("9:30", offered) == offered[1]
    assert pick_slot("whenever", offered) is None


def test_full_phone_booking_conversation():
    ports, state = FakePorts(), {}
    assert "book an appointment" in greeting(ports)
    assert "Which day" in step(state, "Hi, I want to book an appointment", ports).say
    assert "9 AM, 9:30 AM or 10 AM" in step(state, "tomorrow", ports).say
    assert "May I have your name" in step(state, "the first one", ports).say
    assert "Shall I book it?" in step(state, "My name is Ana Reyes", ports).say
    done = step(state, "yes please", ports)
    assert done.outcome == CallOutcome.BOOKED and ports.booked[0][2] == "Ana Reyes"
    assert step(state, "no that's all, bye", ports).action == Action.HANGUP


def test_questions_messages_and_transfer():
    ports = FakePorts()
    answered = step({}, "what are your hours", ports)
    assert "weekdays 9 to 5" in answered.say and answered.action == Action.CONTINUE
    transfer = step({}, "let me talk to a person", ports)
    assert transfer.action == Action.TRANSFER and transfer.transfer_to == "639170000000"

    state = {}
    step(state, "please take a message", ports)
    step(state, "Please call me back about my crown", ports)
    finished = step(state, "Ramon", ports)
    assert finished.action == Action.HANGUP and finished.outcome == CallOutcome.MESSAGE
    assert finished.events[0] == {"type": "message", "name": "Ramon", "text": "Please call me back about my crown"}


def test_no_booking_offers_a_message_and_confusion_escalates():
    ports = FakePorts(services=[])
    state = {}
    assert "take a message" in step(state, "book me in", ports).say and state["step"] == "message"
    state = {}
    for _ in range(3):
        turn = step(state, "hmm", ports)
    assert state["step"] == "message" and "trouble understanding" in turn.say


def test_caller_names_are_cleaned_from_natural_phrases():
    """Regression: "It's Gloria Santos" kept the "It's" prefix as part of the name."""
    from app.domains.voice.dialog import _clean_name

    assert _clean_name("It's Gloria Santos") == "Gloria Santos"
    assert _clean_name("I'm ben") == "Ben"
    assert _clean_name("my name is maria clara") == "Maria Clara"


def test_metadata_endpoints_stay_blocked_even_when_private_targets_are_allowed():
    """Regression: WEBHOOK_ALLOW_PRIVATE (local dev) also let 169.254.169.254 through."""
    for url in ("http://169.254.169.254/latest/meta-data", "http://[fd00:ec2::254]/", "http://0.0.0.0:8000/"):
        with pytest.raises(ValidationFailedError):
            validate_webhook_url(url, allow_private=True, require_https=False)
    assert validate_webhook_url("http://10.0.0.5/hook", allow_private=True, require_https=False)


def test_natural_caller_phrasing_from_live_run():
    """Regressions from the live gateway run: service named up front, ordinal service choice, a day said
    before the service, a question given as a name, and "yes please" mistaken for the message."""
    ports = FakePorts(services=[{"name": "Dental Check-up", "duration_minutes": 30},
                                {"name": "Teeth Cleaning", "duration_minutes": 60}])
    state = {}
    assert "Teeth Cleaning" in step(state, "Hi, I'd like to book a teeth cleaning", ports).say
    assert state["step"] == "booking_day"

    state = {}
    step(state, "I want to book an appointment", ports)
    step(state, "Wednesday", ports)  # day before service: remembered
    offer = step(state, "the second one", ports)
    assert state["service"] == "Teeth Cleaning" and "Which time" in offer.say

    step(state, "the first one", ports)
    assert "what name" in step(state, "do you accept HMO?", ports).say
    assert "Shall I book it" in step(state, "Gloria Santos", ports).say

    state = {"step": "message"}
    assert "listening" in step(state, "yes please", ports).say
    step(state, "My crown fell off please call me", ports)
    assert "what name" in step(state, "do you accept HMO?", ports).say
    assert step(state, "Ramon", ports).events[0]["name"] == "Ramon"


def test_ungrounded_answers_are_detected():
    """Regression from the live receptionist run: qwen2.5:1.5b claimed HMO acceptance from a knowledge base
    that only said "contact us to confirm the payment options"."""
    from app.domains.chatbot.guardrails import ungrounded_terms

    knowledge = "What payment methods do you accept? Contact us to confirm the payment options currently available."
    invented = ("We accept most health maintenance organizations. Please contact our office for a complete list "
                "of covered providers and any specific requirements.")
    assert "maintenance" in ungrounded_terms(invented, knowledge, "do you accept HMO?")
    faithful = "Please contact us to confirm which payment options are currently available."
    assert ungrounded_terms(faithful, knowledge, "do you accept HMO?") == []


def test_callers_can_ask_for_any_open_time():
    """Regression from the portal simulator: "2 pm" was open but not among the 3 offered times."""
    from app.domains.voice.dialog import requested_time

    assert requested_time("2 pm") == ({14}, 0) and requested_time("2") == ({2, 14}, 0)
    assert requested_time("9:30 am please") == ({9}, 30) and requested_time("whenever") is None

    class AllDay(FakePorts):
        def slots(self, day, service):  # 9:00-16:30, except 12:00 (lunch)
            base = datetime(day.year, day.month, day.day, 9)
            return [s for s in (base + timedelta(minutes=30 * i) for i in range(16)) if s.hour != 12]

    ports, state = AllDay(), {}
    step(state, "book an appointment", ports)
    step(state, "tomorrow", ports)
    assert "2 PM it is" in step(state, "2 pm", ports).say

    state = {}
    step(state, "book an appointment", ports)
    step(state, "tomorrow", ports)
    alt = step(state, "12 noon? 12", ports)
    assert "isn't available" in alt.say and "11:30 AM" in alt.say and "1 PM" in alt.say
    assert "1 PM it is" in step(state, "1 pm", ports).say
