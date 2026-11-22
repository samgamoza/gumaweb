"""AI chatbot application service: settings, knowledge base, conversations, lead capture."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agents import registry
from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.core.security import generate_url_token, hash_token
from app.domains.billing.entitlements import Feature, has_feature
from app.domains.chatbot.guardrails import MAX_TURNS_PER_CONVERSATION, clean_message, extract_contact
from app.domains.chatbot.knowledge import KnowledgeItem, entries_from_content
from app.domains.crm.enums import ActivityType, ContactSource
from app.domains.website_factory.enums import WebsiteStatus
from app.models import Business, ChatbotSettings, ChatConversation, ChatMessage, KnowledgeEntry
from app.repositories.repositories import WebsiteRepository
from app.services.crm_service import CrmService
from app.services.entitlements import plan_for_business, refresh_site
from app.services.support import Actor, EventType, record_event


@dataclass(frozen=True)
class ChatReply:
    session_token: str
    reply: str
    strategy: str


class ChatbotService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # --- Settings ----------------------------------------------------------------------------
    def settings_for(self, business_id: uuid.UUID) -> ChatbotSettings:
        row = self.db.get(ChatbotSettings, business_id)
        if row is None:
            row = ChatbotSettings(business_id=business_id)
            self.db.add(row)
            self.db.flush()
        return row

    def update_settings(self, business: Business, changes: dict[str, Any], actor: Actor) -> ChatbotSettings:
        row = self.settings_for(business.id)
        before = (row.enabled, row.greeting)
        for field, value in changes.items():
            setattr(row, field, value)
        if row.enabled and not self._has_website_knowledge(business.id):
            self.rebuild_knowledge(business)
        if (row.enabled, row.greeting) != before:
            refresh_site(self.db, self.settings, business.id, actor)
        self.db.commit()
        return row

    # --- Knowledge base ----------------------------------------------------------------------
    def _has_website_knowledge(self, business_id: uuid.UUID) -> bool:
        return self.db.scalar(select(KnowledgeEntry.id).where(KnowledgeEntry.business_id == business_id,
                                                              KnowledgeEntry.source == "website").limit(1)) is not None

    def refresh_if_enabled(self, business: Business) -> None:
        """Keep website-derived knowledge in sync after the owner edits site content."""
        row = self.db.get(ChatbotSettings, business.id)
        if row is not None and row.enabled:
            self.rebuild_knowledge(business)

    def rebuild_knowledge(self, business: Business) -> int:
        """Regenerate the website-derived entries (custom entries are kept)."""
        website = WebsiteRepository(self.db).by_business(business.id)
        repo = WebsiteRepository(self.db)
        content = {k: r.content for k, r in repo.content_map(website.id).items()} if website else {}
        self.db.execute(delete(KnowledgeEntry).where(KnowledgeEntry.business_id == business.id,
                                                     KnowledgeEntry.source == "website"))
        entries = entries_from_content(business.name, content, {
            "phone": business.phone, "email": business.email, "address": business.address,
            "city": business.city, "province": business.province,
        })
        for entry in entries:
            self.db.add(KnowledgeEntry(business_id=business.id, source="website", section=entry["section"],
                                       title=entry["title"][:300], content=entry["content"]))
        self.db.flush()
        return len(entries)

    def knowledge(self, business_id: uuid.UUID) -> Sequence[KnowledgeEntry]:
        return self.db.scalars(select(KnowledgeEntry).where(KnowledgeEntry.business_id == business_id)
                               .order_by(KnowledgeEntry.source, KnowledgeEntry.created_at)).all()

    def add_entry(self, business_id: uuid.UUID, title: str, content: str) -> KnowledgeEntry:
        entry = KnowledgeEntry(business_id=business_id, source="custom", title=title, content=content)
        self.db.add(entry)
        self.db.commit()
        return entry

    def entry(self, business_id: uuid.UUID, entry_id: uuid.UUID) -> KnowledgeEntry:
        entry = self.db.get(KnowledgeEntry, entry_id)
        if entry is None or entry.business_id != business_id:
            raise NotFoundError("Knowledge entry not found")
        return entry

    # --- Public chat -------------------------------------------------------------------------
    def _chat_site(self, subdomain: str) -> tuple[uuid.UUID, Business, ChatbotSettings]:
        website = WebsiteRepository(self.db).by_subdomain(subdomain)
        if website is None or website.status != WebsiteStatus.PUBLISHED:
            raise NotFoundError("Site not found")
        row = self.db.get(ChatbotSettings, website.business_id)
        features, _ = plan_for_business(self.db, website.business_id)
        if row is None or not row.enabled or not has_feature(features, Feature.AI_CHATBOT):
            raise NotFoundError("Chat is not available for this site")
        return website.id, website.business, row

    def chat(self, subdomain: str, session_token: str | None, message: str, ip: str | None) -> ChatReply:
        _, business, row = self._chat_site(subdomain)
        text = clean_message(message)
        conversation = None
        if session_token:
            conversation = self.db.scalar(select(ChatConversation).where(
                ChatConversation.session_token_hash == hash_token(session_token),
                ChatConversation.business_id == business.id))
        if conversation is None:
            session_token = generate_url_token()
            visitor = hashlib.sha256(f"{self.settings.jwt_secret_key}|{date.today()}|{ip}".encode()).hexdigest()
            conversation = ChatConversation(business_id=business.id, session_token_hash=hash_token(session_token),
                                            visitor_hash=visitor)
            self.db.add(conversation)
            self.db.flush()
        if conversation.message_count >= MAX_TURNS_PER_CONVERSATION:
            return ChatReply(session_token, row.handoff_message, "handoff")

        history = [(m.role, m.content) for m in conversation.messages][-6:]
        self.db.add(ChatMessage(conversation=conversation, role="user", content=text))

        lead_note = ""
        details = extract_contact(text) if row.collect_leads else {}
        if details.get("email") or details.get("phone"):
            contact = CrmService(self.db, self.settings).capture(
                business.id, name=details.get("name") or "Chat visitor", email=details.get("email"),
                phone=details.get("phone"), source=ContactSource.CHATBOT, activity=ActivityType.CHAT,
                body=text, data={"conversation_id": str(conversation.id)},
            )
            if not conversation.lead_captured:
                record_event(self.db, EventType.CHAT_LEAD_CAPTURED, "chat_conversation", conversation.id,
                             {"business_id": str(business.id)})
            conversation.contact_id = contact.id
            conversation.lead_captured = True
            lead_note = "Thanks! We've passed your details to the team and they'll get back to you soon."

        if not self._has_website_knowledge(business.id):
            self.rebuild_knowledge(business)
        items = [KnowledgeItem(str(e.id), e.title, e.content, e.section) for e in self.knowledge(business.id)]
        answer = registry.get_chat_agent(self.settings).answer(
            business=business.name, question=text, history=history, knowledge=items,
            greeting=row.greeting, handoff=row.handoff_message,
        )
        reply = answer.text
        if lead_note:
            # A visitor who just left details shouldn't be asked for them again.
            reply = lead_note if answer.strategy in ("handoff", "greeting") else f"{answer.text}\n\n{lead_note}"

        self.db.add(ChatMessage(conversation=conversation, role="assistant", content=reply, strategy=answer.strategy,
                                sources=answer.sources, model=answer.model, prompt_tokens=answer.prompt_tokens,
                                completion_tokens=answer.completion_tokens, latency_ms=answer.latency_ms))
        conversation.message_count += 2
        conversation.last_message_at = datetime.now(UTC)
        self.db.commit()
        return ChatReply(session_token, reply, answer.strategy)

    # --- Owner -------------------------------------------------------------------------------
    def conversations(self, business_id: uuid.UUID, limit: int = 100) -> Sequence[ChatConversation]:
        return self.db.scalars(select(ChatConversation).where(ChatConversation.business_id == business_id)
                               .order_by(ChatConversation.last_message_at.desc()).limit(limit)).all()

    def conversation(self, business_id: uuid.UUID, conversation_id: uuid.UUID) -> ChatConversation:
        conv = self.db.get(ChatConversation, conversation_id)
        if conv is None or conv.business_id != business_id:
            raise NotFoundError("Conversation not found")
        return conv
