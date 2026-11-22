from enum import StrEnum


class SiteEventType(StrEnum):
    PAGE_VIEW = "page_view"
    CLAIM_BANNER_CLICK = "claim_banner_click"
    CONTACT_SUBMIT = "contact_submit"
    PHONE_CLICK = "phone_click"
