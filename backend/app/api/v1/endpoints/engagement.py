"""Phase 3 customer-portal API: CRM, booking and chatbot management (plan-gated)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import Response

from app.api.deps import AppSettings, CustomerUser, DbSession, Pagination, actor_for
from app.domains.billing.entitlements import Feature, has_feature
from app.domains.booking.enums import AppointmentStatus
from app.domains.crm.enums import ContactSource, ContactStage
from app.models import Appointment, ChatConversation, Contact, ContactActivity, Customer, KnowledgeEntry
from app.schemas.common import Page
from app.schemas.engagement import (
    ActivityCreate,
    ActivityRead,
    AppointmentRead,
    BookingSettingsRead,
    BookingSettingsUpdate,
    ChatbotSettingsRead,
    ChatbotSettingsUpdate,
    ContactCreate,
    ContactDetail,
    ContactRead,
    ContactUpdate,
    ConversationDetail,
    ConversationRead,
    FeatureAccess,
    KnowledgeRead,
    KnowledgeWrite,
    PipelineStage,
)
from app.services.booking_service import BookingService
from app.services.chatbot_service import ChatbotService
from app.services.crm_service import CrmService
from app.services.customer_service import CustomerService
from app.services.entitlements import plan_for_business, require_feature

router = APIRouter(prefix="/customer", tags=["Customer Portal: CRM, Booking, Chatbot"])


def _customer(user, db, settings, feature: Feature | None = None) -> Customer:
    customer = CustomerService(db, settings).for_user(user)
    if feature is not None:
        require_feature(db, customer.business_id, feature)
    return customer


@router.get("/features", response_model=FeatureAccess, summary="Which Phase 3 modules this plan includes")
def features(user: CustomerUser, db: DbSession, settings: AppSettings) -> FeatureAccess:
    customer = _customer(user, db, settings)
    plan_features, name = plan_for_business(db, customer.business_id)
    return FeatureAccess(plan=name, features={f.value: has_feature(plan_features, f) for f in Feature})


# --- CRM ---------------------------------------------------------------------------------------
@router.get("/crm/contacts", response_model=Page[ContactRead])
def list_contacts(user: CustomerUser, db: DbSession, settings: AppSettings, paging: Pagination,
                  q: str | None = Query(None, max_length=100), stage: ContactStage | None = None,
                  source: ContactSource | None = None) -> Page[ContactRead]:
    customer = _customer(user, db, settings, Feature.CRM)
    items, total = CrmService(db, settings).list(customer.business_id, q=q, stage=stage, source=source,
                                                 page=paging.page, page_size=paging.page_size)
    return Page(items=items, total=total, page=paging.page, page_size=paging.page_size)


@router.post("/crm/contacts", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
def create_contact(body: ContactCreate, user: CustomerUser, db: DbSession, settings: AppSettings) -> Contact:
    customer = _customer(user, db, settings, Feature.CRM)
    return CrmService(db, settings).create(customer.business_id, body.model_dump(), user.id)


@router.get("/crm/pipeline", response_model=list[PipelineStage])
def pipeline(user: CustomerUser, db: DbSession, settings: AppSettings) -> list[dict]:
    customer = _customer(user, db, settings, Feature.CRM)
    return CrmService(db, settings).pipeline(customer.business_id)


@router.get("/crm/export.csv", summary="Download contacts as CSV")
def export_contacts(user: CustomerUser, db: DbSession, settings: AppSettings) -> Response:
    customer = _customer(user, db, settings, Feature.CRM)
    return Response(CrmService(db, settings).export_csv(customer.business_id), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="contacts.csv"'})


@router.get("/crm/contacts/{contact_id}", response_model=ContactDetail)
def get_contact(contact_id: uuid.UUID, user: CustomerUser, db: DbSession, settings: AppSettings) -> Contact:
    customer = _customer(user, db, settings, Feature.CRM)
    return CrmService(db, settings).get(customer.business_id, contact_id)


@router.patch("/crm/contacts/{contact_id}", response_model=ContactRead)
def update_contact(contact_id: uuid.UUID, body: ContactUpdate, user: CustomerUser, db: DbSession,
                   settings: AppSettings) -> Contact:
    customer = _customer(user, db, settings, Feature.CRM)
    service = CrmService(db, settings)
    return service.update(service.get(customer.business_id, contact_id), body.model_dump(exclude_unset=True),
                          user.id)


@router.delete("/crm/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(contact_id: uuid.UUID, user: CustomerUser, db: DbSession, settings: AppSettings) -> None:
    customer = _customer(user, db, settings, Feature.CRM)
    service = CrmService(db, settings)
    service.delete(service.get(customer.business_id, contact_id))


@router.post("/crm/contacts/{contact_id}/activities", response_model=ActivityRead,
             status_code=status.HTTP_201_CREATED)
def add_activity(contact_id: uuid.UUID, body: ActivityCreate, user: CustomerUser, db: DbSession,
                 settings: AppSettings) -> ContactActivity:
    customer = _customer(user, db, settings, Feature.CRM)
    service = CrmService(db, settings)
    return service.add_activity(service.get(customer.business_id, contact_id), body.type, body.body, user.id)


# --- Booking -----------------------------------------------------------------------------------
@router.get("/booking/settings", response_model=BookingSettingsRead)
def booking_settings(user: CustomerUser, db: DbSession, settings: AppSettings):
    customer = _customer(user, db, settings, Feature.BOOKING)
    row = BookingService(db, settings).settings_for(customer.business_id)
    db.commit()
    return row


@router.put("/booking/settings", response_model=BookingSettingsRead,
            summary="Update availability/services; enabling adds the booking widget to the site")
def update_booking_settings(body: BookingSettingsUpdate, request: Request, user: CustomerUser, db: DbSession,
                            settings: AppSettings):
    customer = _customer(user, db, settings, Feature.BOOKING)
    changes = body.model_dump(exclude_unset=True)
    if "services" in changes:
        changes["services"] = [s.model_dump() for s in body.services or []]
    return BookingService(db, settings).update_settings(customer.business, changes, actor_for(request, user))


@router.get("/booking/appointments", response_model=list[AppointmentRead])
def appointments(user: CustomerUser, db: DbSession, settings: AppSettings, start: datetime | None = None,
                 end: datetime | None = None, status_filter: AppointmentStatus | None = None) -> list[Appointment]:
    customer = _customer(user, db, settings, Feature.BOOKING)
    return list(BookingService(db, settings).appointments(customer.business_id, start, end, status_filter))


@router.post("/booking/appointments/{appointment_id}/{action}", response_model=AppointmentRead,
             summary="confirm | cancel | complete | no_show")
def appointment_action(appointment_id: uuid.UUID, action: str, user: CustomerUser, db: DbSession,
                       settings: AppSettings) -> Appointment:
    customer = _customer(user, db, settings, Feature.BOOKING)
    return BookingService(db, settings).owner_action(customer.business_id, appointment_id, action)


# --- Chatbot -----------------------------------------------------------------------------------
@router.get("/chatbot/settings", response_model=ChatbotSettingsRead)
def chatbot_settings(user: CustomerUser, db: DbSession, settings: AppSettings):
    customer = _customer(user, db, settings, Feature.AI_CHATBOT)
    row = ChatbotService(db, settings).settings_for(customer.business_id)
    db.commit()
    return row


@router.put("/chatbot/settings", response_model=ChatbotSettingsRead,
            summary="Update the assistant; enabling adds the chat widget to the site")
def update_chatbot_settings(body: ChatbotSettingsUpdate, request: Request, user: CustomerUser, db: DbSession,
                            settings: AppSettings):
    customer = _customer(user, db, settings, Feature.AI_CHATBOT)
    return ChatbotService(db, settings).update_settings(customer.business, body.model_dump(exclude_unset=True),
                                                        actor_for(request, user))


@router.get("/chatbot/knowledge", response_model=list[KnowledgeRead])
def knowledge(user: CustomerUser, db: DbSession, settings: AppSettings) -> list[KnowledgeEntry]:
    customer = _customer(user, db, settings, Feature.AI_CHATBOT)
    return list(ChatbotService(db, settings).knowledge(customer.business_id))


@router.post("/chatbot/knowledge", response_model=KnowledgeRead, status_code=status.HTTP_201_CREATED)
def add_knowledge(body: KnowledgeWrite, user: CustomerUser, db: DbSession, settings: AppSettings) -> KnowledgeEntry:
    customer = _customer(user, db, settings, Feature.AI_CHATBOT)
    return ChatbotService(db, settings).add_entry(customer.business_id, body.title, body.content)


@router.put("/chatbot/knowledge/{entry_id}", response_model=KnowledgeRead)
def update_knowledge(entry_id: uuid.UUID, body: KnowledgeWrite, user: CustomerUser, db: DbSession,
                     settings: AppSettings) -> KnowledgeEntry:
    customer = _customer(user, db, settings, Feature.AI_CHATBOT)
    entry = ChatbotService(db, settings).entry(customer.business_id, entry_id)
    entry.title, entry.content = body.title, body.content
    entry.source = "custom"  # an edited website entry becomes owner-managed (kept on rebuild)
    db.commit()
    return entry


@router.delete("/chatbot/knowledge/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge(entry_id: uuid.UUID, user: CustomerUser, db: DbSession, settings: AppSettings) -> None:
    customer = _customer(user, db, settings, Feature.AI_CHATBOT)
    db.delete(ChatbotService(db, settings).entry(customer.business_id, entry_id))
    db.commit()


@router.post("/chatbot/knowledge/rebuild", response_model=list[KnowledgeRead],
             summary="Re-import knowledge from the website content (custom entries are kept)")
def rebuild_knowledge(user: CustomerUser, db: DbSession, settings: AppSettings) -> list[KnowledgeEntry]:
    customer = _customer(user, db, settings, Feature.AI_CHATBOT)
    service = ChatbotService(db, settings)
    service.rebuild_knowledge(customer.business)
    db.commit()
    return list(service.knowledge(customer.business_id))


@router.get("/chatbot/conversations", response_model=list[ConversationRead])
def conversations(user: CustomerUser, db: DbSession, settings: AppSettings) -> list[ChatConversation]:
    customer = _customer(user, db, settings, Feature.AI_CHATBOT)
    return list(ChatbotService(db, settings).conversations(customer.business_id))


@router.get("/chatbot/conversations/{conversation_id}", response_model=ConversationDetail)
def conversation(conversation_id: uuid.UUID, user: CustomerUser, db: DbSession,
                 settings: AppSettings) -> ChatConversation:
    customer = _customer(user, db, settings, Feature.AI_CHATBOT)
    return ChatbotService(db, settings).conversation(customer.business_id, conversation_id)
