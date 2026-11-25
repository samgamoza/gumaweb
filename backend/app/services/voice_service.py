"""AI receptionist application service: call lifecycle, side effects, summaries.

Telephony integration contract (provider-agnostic): a gateway (e.g. Asterisk ARI
with local faster-whisper ASR and Piper TTS) calls
  POST /voice/inbound          {to, from}        -> {call_id, say, action}
  POST /voice/calls/{id}/turn  {text}            -> {say, action, transfer_to}
  POST /voice/calls/{id}/end   {}                -> {outcome, summary}
authenticated with X-Voice-Gateway-Token. The portal simulator uses the same engine.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import registry
from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.domains.automation.rules import Trigger
from app.domains.billing.entitlements import Feature, has_feature
from app.domains.business_discovery.normalization import normalize_phone
from app.domains.chatbot.guardrails import unsupported_claims
from app.domains.chatbot.knowledge import KnowledgeItem
from app.domains.crm.enums import ActivityType, ContactSource
from app.domains.integrations.webhooks import WebhookEvent
from app.domains.voice.dialog import Action, CallOutcome, Turn, greeting, say_time, step
from app.domains.website_factory.jobs import JobKind
from app.models import Business, Call, Contact, VoiceSettings
from app.services.booking_service import BookingService
from app.services.business_events import contact_context, emit
from app.services.chatbot_service import ChatbotService
from app.services.crm_service import CrmService
from app.services.entitlements import plan_for_business
from app.services.job_queue import JobQueue
from app.services.notifications import EmailMessage
from app.services.providers import providers

logger = logging.getLogger("gumaweb.voice")


class _Ports:
    """Implements dialog.Ports on top of booking, knowledge and CRM services."""

    def __init__(self, service: VoiceService, business: Business, call: Call, settings_row: VoiceSettings) -> None:
        self.svc, self.business, self.call = service, business, call
        self.business_name = business.name
        self.forward_number = settings_row.forward_number
        self.booking = BookingService(service.db, service.settings)
        self.booking_services = self.booking.booking_services(business.id)
        tz = self.booking.rules(self.booking.settings_for(business.id)).tz
        self.today: date = datetime.now(tz).date()

    def slots(self, day: date, service: str) -> list[datetime]:
        return self.booking.slots_for_business(self.business.id, day, service)

    def book(self, service: str, start: datetime, name: str) -> str | None:
        try:
            appt, _ = self.booking.book_for_business(self.business.id, {
                "service": service, "start": start, "name": name, "phone": self.call.caller_number,
                "notes": "Booked by phone (AI receptionist)",
            })
        except ConflictError as exc:
            return exc.message
        self.call.appointment_id = appt.id
        self.call.contact_id = appt.contact_id
        return None

    def answer(self, question: str) -> tuple[str, bool]:
        chatbot = ChatbotService(self.svc.db, self.svc.settings)
        if not chatbot._has_website_knowledge(self.business.id):
            chatbot.rebuild_knowledge(self.business)
        items = [KnowledgeItem(str(e.id), e.title, e.content, e.section) for e in chatbot.knowledge(self.business.id)]
        result = registry.get_chat_agent(self.svc.settings).answer(
            business=self.business.name, question=question, history=[], knowledge=items, greeting="", handoff="")
        return result.text, result.strategy in ("handoff", "greeting")


class VoiceService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # --- Settings ----------------------------------------------------------------------------
    def settings_for(self, business_id: uuid.UUID) -> VoiceSettings:
        row = self.db.get(VoiceSettings, business_id)
        if row is None:
            row = VoiceSettings(business_id=business_id)
            self.db.add(row)
            self.db.flush()
        return row

    def update_settings(self, business_id: uuid.UUID, changes: dict[str, Any]) -> VoiceSettings:
        row = self.settings_for(business_id)
        for field in ("phone_number", "forward_number"):
            if field in changes and changes[field]:
                normalized = normalize_phone(changes[field], self.settings.default_country_code)
                if not normalized:
                    raise ValidationFailedError(f"Invalid {field.replace('_', ' ')}")
                changes[field] = normalized
        if changes.get("phone_number"):
            other = self.db.scalar(select(VoiceSettings).where(VoiceSettings.phone_number == changes["phone_number"],
                                                               VoiceSettings.business_id != business_id))
            if other:
                raise ConflictError("That phone number is already assigned to another business")
        for field, value in changes.items():
            setattr(row, field, value)
        self.db.commit()
        return row

    # --- Call lifecycle ----------------------------------------------------------------------
    def _entitled(self, business_id: uuid.UUID) -> bool:
        features, _ = plan_for_business(self.db, business_id)
        return has_feature(features, Feature.VOICE_RECEPTIONIST)

    def inbound(self, to_number: str, caller: str | None) -> tuple[Call, Turn]:
        number = normalize_phone(to_number, self.settings.default_country_code)
        row = self.db.scalar(select(VoiceSettings).where(VoiceSettings.phone_number == number))
        if row is None or not row.enabled or not self._entitled(row.business_id):
            raise NotFoundError("No receptionist is configured for this number")
        return self._start(row.business_id, caller, is_test=False)

    def start_test(self, business_id: uuid.UUID, caller: str | None) -> tuple[Call, Turn]:
        return self._start(business_id, caller, is_test=True)

    def _start(self, business_id: uuid.UUID, caller: str | None, is_test: bool) -> tuple[Call, Turn]:
        business = self.db.get(Business, business_id)
        row = self.settings_for(business_id)
        call = Call(business_id=business_id, is_test=is_test,
                    caller_number=normalize_phone(caller, self.settings.default_country_code) if caller else None,
                    state={"step": "intent"}, transcript=[])
        self.db.add(call)
        self.db.flush()
        turn = Turn(greeting(_Ports(self, business, call, row)))
        call.transcript = [{"speaker": "assistant", "text": turn.say}]
        self.db.commit()
        return call, turn

    def get_call(self, call_id: uuid.UUID, business_id: uuid.UUID | None = None) -> Call:
        call = self.db.get(Call, call_id)
        if call is None or (business_id is not None and call.business_id != business_id):
            raise NotFoundError("Call not found")
        return call

    def turn(self, call: Call, text: str) -> Turn:
        if call.status != "in_progress":
            raise ConflictError("This call has ended")
        text = text.strip()[:500]
        business = self.db.get(Business, call.business_id)
        row = self.settings_for(call.business_id)
        state = dict(call.state or {})
        turn = step(state, text, _Ports(self, business, call, row))
        call.state = state
        call.transcript = [*call.transcript, {"speaker": "caller", "text": text},
                           {"speaker": "assistant", "text": turn.say}]
        if turn.outcome:
            state["outcome"] = turn.outcome.value
            call.state = state
        for event in turn.events:
            if event["type"] == "message":
                self._take_message(call, business, event["name"], event["text"])
        if turn.action in (Action.HANGUP, Action.TRANSFER):
            self._finish(call, business)
        self.db.commit()
        return turn

    def end(self, call: Call) -> Call:
        """Gateway hang-up (caller left). Idempotent."""
        if call.status == "in_progress":
            self._finish(call, self.db.get(Business, call.business_id))
            self.db.commit()
        return call

    # --- Side effects ------------------------------------------------------------------------
    def _take_message(self, call: Call, business: Business, name: str, text: str) -> None:
        if call.caller_number:
            contact = CrmService(self.db, self.settings).capture(
                business.id, name=name, email=None, phone=call.caller_number, source=ContactSource.PHONE,
                activity=ActivityType.CALL, body=f"Voicemail via AI receptionist: {text}")
            call.contact_id = contact.id
        to = business.email
        if to:
            providers.email.send(EmailMessage(
                to=to, subject=f"New phone message from {name}",
                text=f"{name} ({'+' + call.caller_number if call.caller_number else 'number withheld'}) "
                     f"left a message with your AI receptionist:\n\n\"{text}\"",
            ))

    def _finish(self, call: Call, business: Business) -> None:
        now = datetime.now(UTC)
        state = call.state or {}
        started = call.started_at.replace(tzinfo=call.started_at.tzinfo or UTC) if call.started_at else now
        outcome = state.get("outcome") or (CallOutcome.ANSWERED.value if state.get("answered")
                                           else CallOutcome.ABANDONED.value)
        call.status, call.ended_at, call.outcome = "completed", now, outcome
        call.duration_seconds = max(0, int((now - started).total_seconds()))
        if call.caller_number and outcome == CallOutcome.ANSWERED.value and not call.contact_id:
            asked = next((t["text"] for t in call.transcript if t["speaker"] == "caller"), "")
            contact = CrmService(self.db, self.settings).capture(
                business.id, name="Caller", email=None, phone=call.caller_number, source=ContactSource.PHONE,
                activity=ActivityType.CALL, body=f"Called the AI receptionist and asked: {asked[:300]}")
            call.contact_id = contact.id
        call.summary = self.summarize(call, business)
        if len(call.transcript) >= 4 and self.settings.ai_enabled:
            JobQueue(self.db).enqueue(JobKind.SUMMARIZE_CALL, {"call_id": str(call.id)}, priority=60, max_attempts=2)
        if not call.is_test:
            context: dict[str, Any] = {"call": {"id": str(call.id), "outcome": outcome, "summary": call.summary,
                                                "caller": call.caller_number,
                                                "duration_seconds": call.duration_seconds}}
            if call.contact_id:
                contact = self.db.get(Contact, call.contact_id)
                if contact:
                    context["contact"] = contact_context(contact)
            emit(self.db, business.id, trigger=Trigger.CALL_COMPLETED, webhook=WebhookEvent.CALL_COMPLETED,
                 subject_type="call", subject_id=call.id, context=context)

    def summarize(self, call: Call, business: Business) -> str:
        """Deterministic call summary (14 Voice AI: call_summaries); available the moment the call ends."""
        state = call.state or {}
        caller = state.get("name") or ("+" + call.caller_number if call.caller_number else "A caller")
        if call.outcome == CallOutcome.BOOKED.value and state.get("chosen"):
            chosen = datetime.fromisoformat(state["chosen"])
            baseline = f"{caller} booked a {state.get('service')} on {chosen:%A %d %B} at {say_time(chosen)}."
        else:
            baseline = {
                CallOutcome.MESSAGE.value: f"{caller} left a message: \"{state.get('message', '')[:200]}\"",
                CallOutcome.TRANSFERRED.value: f"{caller} asked for a person and was transferred.",
                CallOutcome.ANSWERED.value: f"{caller} asked questions that were answered from your information.",
                CallOutcome.ABANDONED.value: f"{caller} hung up before anything was arranged.",
            }.get(call.outcome or "", "Call completed.")
        return baseline

    def polish_summary(self, call_id: uuid.UUID) -> dict[str, Any]:
        """Worker job: replace the baseline summary with a model-written one when it is fully grounded.
        Runs after the call so the caller never waits on the model."""
        call = self.db.get(Call, call_id)
        llm = registry.get_background_llm(self.settings)
        if call is None or llm is None or len(call.transcript) < 4:
            return {"skipped": True}
        transcript = "\n".join(f"{t['speaker']}: {t['text']}" for t in call.transcript)[-6000:]
        response = llm.complete(  # failures propagate: the job queue retries with backoff
            f"Summarize this phone call for the business owner in at most 2 sentences. Mention what the caller "
            f"wanted and the outcome. Use only facts from the transcript.\n\n{transcript}",
            model=self.settings.llm_primary_model, temperature=0.1, max_tokens=150)
        text = response.text.strip()
        if not text or len(text) > 600 or unsupported_claims(text, json.dumps(call.transcript)):
            return {"kept": "baseline"}
        call.summary = text
        self.db.commit()
        return {"polished": True}

    def close_stale(self, max_age: timedelta = timedelta(hours=1)) -> int:
        """Finish calls whose hang-up never arrived (gateway crash, closed simulator tab)."""
        cutoff = datetime.now(UTC) - max_age
        stale = self.db.scalars(select(Call).where(Call.status == "in_progress", Call.started_at < cutoff)
                                .limit(200)).all()
        for call in stale:
            self._finish(call, self.db.get(Business, call.business_id))
        self.db.commit()
        return len(stale)

    def calls(self, business_id: uuid.UUID, limit: int = 100) -> Sequence[Call]:
        return self.db.scalars(select(Call).where(Call.business_id == business_id)
                               .order_by(Call.started_at.desc()).limit(limit)).all()
