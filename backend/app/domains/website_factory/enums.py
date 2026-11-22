from enum import StrEnum


class WebsiteStatus(StrEnum):
    DRAFT = "draft"
    BLUEPRINT_READY = "blueprint_ready"
    BUILT = "built"
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"
    FAILED = "failed"


class ContentSource(StrEnum):
    """Who produced a content block. AI-generated content will use AI."""

    TEMPLATE = "template"
    AI = "ai"
    CUSTOMER = "customer"
    OPERATOR = "operator"
