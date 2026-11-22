from enum import StrEnum


class BusinessStatus(StrEnum):
    """Lifecycle of a business record through the factory pipeline."""

    DISCOVERED = "discovered"
    SCORED = "scored"
    PROFILED = "profiled"
    GENERATED = "generated"
    PUBLISHED = "published"
    CLAIMED = "claimed"
    ARCHIVED = "archived"


class DiscoveryRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DiscoverySource(StrEnum):
    MANUAL = "manual"
    CSV_IMPORT = "csv_import"
    DTI = "dti"
    CHAMBER = "chamber"
    YELLOW_PAGES = "yellow_pages"
    GOOGLE_BUSINESS = "google_business"
    FACEBOOK = "facebook"
    SEC = "sec"
