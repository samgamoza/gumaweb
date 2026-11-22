"""AI receptionist call flow (12-customer-portal AI Receptionist; 14 Voice AI tier).

A deterministic, turn-based dialog: the telephony gateway does speech-to-text
(local Whisper) and text-to-speech (local Piper); this engine decides what to say
next. Intents: book an appointment, ask a question (answered from the business's
knowledge), leave a message, talk to a person (transfer), goodbye. Being rule
driven keeps calls fast, predictable and cheap; the knowledge answers can still
use the local LLM through the `answer` port.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

MAX_MISUNDERSTOOD = 2
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
# Ordinal words win over number words: in "the second one", "one" is filler, not the first option.
ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "last": -1}
NUMBER_WORDS = {"one": 0, "two": 1, "three": 2}


class CallOutcome(StrEnum):
    BOOKED = "booked"
    MESSAGE = "message"
    ANSWERED = "answered"
    TRANSFERRED = "transferred"
    ABANDONED = "abandoned"


class Action(StrEnum):
    CONTINUE = "continue"
    HANGUP = "hangup"
    TRANSFER = "transfer"


class Ports(Protocol):
    """What the dialog needs from the platform (implemented by VoiceService)."""

    business_name: str
    forward_number: str | None
    booking_services: list[dict[str, Any]]  # [] when online booking is off
    today: date

    def slots(self, day: date, service: str) -> list[datetime]: ...

    def book(self, service: str, start: datetime, name: str) -> str | None:
        """Book; returns an error message or None on success."""
        ...

    def answer(self, question: str) -> tuple[str, bool]:
        """(answer, handed_off) from the business knowledge base."""
        ...


@dataclass
class Turn:
    say: str
    action: Action = Action.CONTINUE
    transfer_to: str | None = None
    outcome: CallOutcome | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9: ]", " ", text.lower())).strip()


def classify(text: str) -> str:
    t = _norm(text)
    words = set(t.split())
    if re.search(r"\b(bye|goodbye|that s all|thats all|nothing else|no thanks|wala na)\b", t):
        return "goodbye"
    if re.search(r"\b(book|booking|appointment|schedule|reserve|reservation|pa schedule|magpa schedule)\b", t):
        return "booking"
    if re.search(r"\b(person|human|someone|owner|manager|staff|representative|agent|talk to|speak to)\b", t):
        return "human"
    if re.search(r"\b(message|call me back|callback|call back)\b", t):
        return "message"
    if words & {"yes", "yeah", "yep", "sure", "correct", "ok", "okay", "oo", "opo", "right"}:
        return "yes"
    if words & {"no", "nope", "hindi", "wrong"}:
        return "no"
    return "question" if len(words) >= 2 else "unknown"


def parse_day(text: str, today: date) -> date | None:
    t = _norm(text)
    if re.search(r"\b(today|ngayon)\b", t):
        return today
    if re.search(r"\b(tomorrow|bukas)\b", t):
        return today + timedelta(days=1)
    for i, name in enumerate(WEEKDAYS):
        if re.search(rf"\b{name}\b", t):
            ahead = (i - today.weekday()) % 7 or 7  # "monday" means the next Monday
            return today + timedelta(days=ahead)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    return None


def say_time(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")


def say_day(day: date, today: date) -> str:
    if day == today:
        return "today"
    if day == today + timedelta(days=1):
        return "tomorrow"
    return day.strftime("%A, %B %d").replace(" 0", " ")


def pick_slot(text: str, offered: list[datetime]) -> datetime | None:
    t = _norm(text)
    for table in (ORDINALS, NUMBER_WORDS):
        for word, index in table.items():
            if re.search(rf"\b{word}\b", t) and offered:
                return offered[index] if index < len(offered) else None
    requested = requested_time(text)
    if requested:
        hours, minute = requested
        return next((slot for slot in offered if slot.hour in hours and slot.minute == minute), None)
    return None


def requested_time(text: str) -> tuple[set[int], int] | None:
    """A clock time in the utterance as (possible 24 h hours, minute): "2 pm" -> ({14}, 0); bare "2" -> ({2, 14}, 0)."""
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", _norm(text).replace(" p m", " pm").replace(" a m", " am"))
    if not m or int(m[1]) > 23 or int(m[2] or 0) > 59:
        return None
    hour, minute, meridiem = int(m[1]), int(m[2] or 0), m[3]
    if meridiem == "pm":
        return {hour % 12 + 12}, minute
    if meridiem == "am":
        return {hour % 12}, minute
    return ({hour} if hour > 12 else {hour % 12, hour % 12 + 12}), minute


def _match_service(text: str, services: list[dict[str, Any]], *, ordinals: bool = False) -> dict[str, Any] | None:
    t = _norm(text)
    if ordinals:  # "the second one" while the services are being listed
        for table in (ORDINALS, NUMBER_WORDS):
            for word, index in table.items():
                if re.search(rf"\b{word}\b", t) and index < len(services):
                    return services[index]
    words = set(t.split())
    best, best_overlap = None, 0
    for service in services:
        overlap = len(words & set(_norm(service["name"]).split()))
        if overlap > best_overlap:
            best, best_overlap = service, overlap
    return best


def _clean_name(text: str) -> str:
    # Raw speech-to-text keeps apostrophes: "It's Gloria", "I'm Ben".
    name = re.sub(r"(?i)^\s*(my name is|this is|it['’]?s|it is|i am|i['’]?m|ako si|name is|name)\s+", "",
                  text.strip())
    name = re.sub(r"[^A-Za-z .'-]", "", name).strip(" .")
    return " ".join(w.capitalize() for w in name.split()[:4])[:60]


def _looks_like_name(text: str) -> bool:
    """A reply to "what's your name?" that is really a question or a sentence is not a name."""
    t = _norm(text)
    asks = "?" in text or re.match(r"(what|do|does|did|how|when|where|why|can|could|is|are|will|magkano|ano|may)\b", t)
    return bool(_clean_name(text)) and not asks and classify(text) not in ("booking", "human", "message") \
        and len(t.split()) <= 6


def greeting(ports: Ports) -> str:
    can_book = " book an appointment," if ports.booking_services else ""
    return (f"Thank you for calling {ports.business_name}. I'm the automated assistant. I can{can_book} "
            "answer questions, or take a message. How can I help you?")


def step(state: dict[str, Any], text: str, ports: Ports) -> Turn:
    """Advance the call by one caller utterance. Mutates `state`."""
    s = state.setdefault("step", "intent")
    intent = classify(text)
    handlers: dict[str, Callable[[dict[str, Any], str, str, Ports], Turn]] = {
        "intent": _intent, "booking_service": _booking_service, "booking_day": _booking_day,
        "booking_pick": _booking_pick, "booking_name": _booking_name, "booking_confirm": _booking_confirm,
        "message": _message, "message_name": _message_name,
    }
    if intent == "goodbye" and s in ("intent", "booking_day", "booking_pick"):
        return Turn(f"Thank you for calling {ports.business_name}. Goodbye!", Action.HANGUP)
    return handlers.get(s, _intent)(state, text, intent, ports)


def _misunderstood(state: dict[str, Any], prompt: str) -> Turn:
    state["misunderstood"] = state.get("misunderstood", 0) + 1
    if state["misunderstood"] > MAX_MISUNDERSTOOD:
        state["step"] = "message"
        return Turn("Sorry, I'm having trouble understanding. Please tell me your message and someone will "
                    "call you back.")
    return Turn(prompt)


def _intent(state: dict[str, Any], text: str, intent: str, ports: Ports) -> Turn:
    if intent == "booking":
        if not ports.booking_services:
            state["step"] = "message"
            return Turn("I can't book appointments over the phone for this business, but I can take a message. "
                        "What would you like to say?")
        services = ports.booking_services
        service = services[0] if len(services) == 1 else _match_service(text, services)
        if service:  # "I'd like to book a teeth cleaning"
            state["service"] = service["name"]
            state["step"] = "booking_day"
            if (day := parse_day(text, ports.today)) is not None:
                return _booking_day(state, day.isoformat(), intent, ports)
            return Turn(f"Sure, let's book a {state['service']}. Which day works for you? For example, tomorrow "
                        "or Monday.")
        state["step"] = "booking_service"
        names = [s["name"] for s in ports.booking_services]
        listed = ", ".join(names[:-1]) + f" or {names[-1]}"
        return Turn(f"Sure. Which service would you like: {listed}?")
    if intent == "human":
        if ports.forward_number:
            return Turn("Okay, connecting you now. Please hold.", Action.TRANSFER, ports.forward_number,
                        CallOutcome.TRANSFERRED)
        state["step"] = "message"
        return Turn("No one is available to take your call right now. Please tell me your message and we'll "
                    "call you back.")
    if intent == "message":
        state["step"] = "message"
        return Turn("Of course. Please tell me your message.")
    if intent in ("question", "unknown", "yes", "no"):
        if intent != "question" and len(text.split()) < 2:
            return _misunderstood(state, "Sorry, I didn't catch that. You can ask a question, book an appointment, "
                                         "or leave a message.")
        answer, handed_off = ports.answer(text)
        if handed_off:
            return _misunderstood(state, "I'm not sure about that one. Would you like to leave a message so the "
                                         "team can call you back?")
        state["answered"] = True
        return Turn(f"{answer} Is there anything else I can help with?")
    return _misunderstood(state, "How can I help you today?")


def _booking_service(state, text, intent, ports) -> Turn:
    service = _match_service(text, ports.booking_services, ordinals=True)
    day = parse_day(text, ports.today)
    if day is not None:
        state["pending_day"] = day.isoformat()  # remember "Wednesday" said before the service
    if service is None:
        names = ", ".join(s["name"] for s in ports.booking_services)
        return _misunderstood(state, f"Sorry, which service? We offer {names}.")
    state["service"] = service["name"]
    state["step"] = "booking_day"
    if state.get("pending_day"):
        return _booking_day(state, state.pop("pending_day"), intent, ports)
    return Turn(f"Great, a {service['name']}. Which day works for you?")


def _booking_day(state, text, intent, ports) -> Turn:
    day = parse_day(text, ports.today)
    if day is None:
        return _misunderstood(state, "Which day would you like? You can say today, tomorrow, or a day like Monday.")
    slots = ports.slots(day, state["service"])
    if not slots:
        return Turn(f"Sorry, there are no openings {say_day(day, ports.today)}. Would another day work?")
    offered = slots[:3]
    state.update(step="booking_pick", day=day.isoformat(), offered=[s.isoformat() for s in offered])
    options = [say_time(s) for s in offered]
    listed = options[0] if len(options) == 1 else ", ".join(options[:-1]) + f" or {options[-1]}"
    return Turn(f"For {say_day(day, ports.today)} I have {listed}. Which time would you like?")


def _booking_pick(state, text, intent, ports) -> Turn:
    offered = [datetime.fromisoformat(s) for s in state.get("offered", [])]
    if intent == "no":
        state["step"] = "booking_day"
        return Turn("No problem. Which other day would you like?")
    chosen = pick_slot(text, offered)
    if chosen is None:
        day = parse_day(text, ports.today)
        if day is not None:  # caller switched days
            return _booking_day(state, text, intent, ports)
        if (requested := requested_time(text)) is not None:  # a time we didn't offer: any open slot that day
            hours, minute = requested
            all_slots = ports.slots(date.fromisoformat(state["day"]), state["service"])
            chosen = next((s for s in all_slots if s.hour in hours and s.minute == minute), None)
            if chosen is None:
                if not all_slots:
                    state["step"] = "booking_day"
                    return Turn("Sorry, that day just filled up. Would another day work?")
                target = min(hours, key=lambda h: min(abs(s.hour - h) for s in all_slots)) * 60 + minute
                nearest = sorted(sorted(all_slots, key=lambda s: abs(s.hour * 60 + s.minute - target))[:3])
                state["offered"] = [s.isoformat() for s in nearest]
                options = [say_time(s) for s in nearest]
                listed = options[0] if len(options) == 1 else ", ".join(options[:-1]) + f" or {options[-1]}"
                return Turn(f"Sorry, that time isn't available. The closest I have are {listed}. Which would you "
                            "like?")
    if chosen is None:
        return _misunderstood(state, "Sorry, which of those times? You can say the first one, or a time like 10 AM.")
    state.update(step="booking_name", chosen=chosen.isoformat())
    return Turn(f"{say_time(chosen)} it is. May I have your name, please?")


def _booking_name(state, text, intent, ports) -> Turn:
    if not _looks_like_name(text):
        return _misunderstood(state, "Sorry, what name should I put the booking under?")
    name = _clean_name(text)
    chosen = datetime.fromisoformat(state["chosen"])
    state.update(step="booking_confirm", name=name)
    return Turn(f"Thanks, {name}. To confirm: a {state['service']} {say_day(chosen.date(), ports.today)} at "
                f"{say_time(chosen)}. Shall I book it?")


def _booking_confirm(state, text, intent, ports) -> Turn:
    if intent == "no":
        state["step"] = "booking_day"
        return Turn("Okay, let's find another time. Which day would you like?")
    if intent != "yes":
        return _misunderstood(state, "Please say yes to confirm the booking, or no to choose another time.")
    chosen = datetime.fromisoformat(state["chosen"])
    error = ports.book(state["service"], chosen, state["name"])
    if error:
        state["step"] = "booking_day"
        return Turn(f"I'm sorry, that time was just taken. {error} Which day would you like instead?")
    state.update(step="intent", booked=True)
    return Turn(f"You're all set, {state['name']}: {state['service']} {say_day(chosen.date(), ports.today)} at "
                f"{say_time(chosen)}. Is there anything else I can help with?", outcome=CallOutcome.BOOKED,
                events=[{"type": "booked", "service": state["service"], "start": state["chosen"]}])


def _message(state, text, intent, ports) -> Turn:
    if intent in ("yes", "no") and len(text.split()) <= 3 and not state.get("prompted_message"):
        state["prompted_message"] = True  # "yes please" is consent, not the message itself
        return Turn("Go ahead, I'm listening.")
    if len(text.split()) < 2:
        return _misunderstood(state, "Please tell me your message after the beep.")
    state["message"] = text.strip()[:1000]
    if state.get("name"):
        return _finish_message(state, ports)
    state["step"] = "message_name"
    return Turn("Got it. And what's your name?")


def _message_name(state, text, intent, ports) -> Turn:
    if not _looks_like_name(text) and not state.get("asked_name_again"):
        state["asked_name_again"] = True
        return Turn("Sorry, what name should I give the team?")
    state["name"] = _clean_name(text) if _looks_like_name(text) else "Caller"
    return _finish_message(state, ports)


def _finish_message(state, ports) -> Turn:
    state["step"] = "done"
    return Turn(f"Thanks, {state['name']}. I'll pass your message to the team and someone will call you back. "
                "Goodbye!", Action.HANGUP, outcome=CallOutcome.MESSAGE,
                events=[{"type": "message", "name": state["name"], "text": state["message"]}])
