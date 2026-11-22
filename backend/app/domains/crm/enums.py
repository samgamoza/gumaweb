from enum import StrEnum


class ContactStage(StrEnum):
    """Sales pipeline (12-customer-portal CRM: sales_pipeline)."""

    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    WON = "won"
    LOST = "lost"


PIPELINE = list(ContactStage)
OPEN_STAGES = (ContactStage.NEW, ContactStage.CONTACTED, ContactStage.QUALIFIED)


class ContactSource(StrEnum):
    CONTACT_FORM = "contact_form"
    BOOKING = "booking"
    CHATBOT = "chatbot"
    MANUAL = "manual"
    PHONE = "phone"


class ActivityType(StrEnum):
    NOTE = "note"
    CALL = "call"
    EMAIL = "email"
    MEETING = "meeting"
    STAGE_CHANGE = "stage_change"
    FORM_SUBMISSION = "form_submission"
    BOOKING = "booking"
    CHAT = "chat"
