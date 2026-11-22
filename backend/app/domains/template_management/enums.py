from enum import StrEnum


class TemplateStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class ComponentType(StrEnum):
    HERO = "hero"
    ABOUT = "about"
    SERVICES = "services"
    GALLERY = "gallery"
    TESTIMONIALS = "testimonials"
    FAQ = "faq"
    CTA = "cta"
    CONTACT = "contact"
    MAP = "map"
    FOOTER = "footer"
