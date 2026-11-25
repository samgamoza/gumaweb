"""Sales CRM rules: Guma OS's own prospect pipeline (docs/SALES_CRM_PLAN.md).

Not the customer CRM (`domains/crm`), which business owners use for their own leads.
Pure rules only: which stage an activity moves a prospect to, and when a move is allowed.
"""

from __future__ import annotations

from enum import StrEnum

from app.domains.outreach.suppression import SuppressionReason


class ProspectStage(StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    ENGAGED = "engaged"
    CONVERSATION = "conversation"
    CLAIMED = "claimed"
    WON = "won"  # paying
    LOST = "lost"
    DO_NOT_CONTACT = "do_not_contact"


# The forward path; LOST and DO_NOT_CONTACT sit outside it.
PIPELINE = (ProspectStage.NEW, ProspectStage.CONTACTED, ProspectStage.ENGAGED, ProspectStage.CONVERSATION,
            ProspectStage.CLAIMED, ProspectStage.WON)
CLOSED_STAGES = (ProspectStage.LOST, ProspectStage.DO_NOT_CONTACT)
CONVERTED_STAGES = (ProspectStage.CLAIMED, ProspectStage.WON)


class ActivityType(StrEnum):
    DRAFT_READY = "draft_ready"  # a private, quality-checked draft site exists: the prospect enters the pipeline
    SITE_PUBLISHED = "site_published"
    EMAIL_SENT = "email_sent"
    EMAIL_OPENED = "email_opened"
    LINK_CLICKED = "link_clicked"
    UNSUBSCRIBED = "unsubscribed"
    CLAIM_STARTED = "claim_started"
    CLAIM_APPROVED = "claim_approved"
    CLAIM_REJECTED = "claim_rejected"
    SUBSCRIBED = "subscribed"  # moved to a paid plan
    CHURNED = "churned"  # moved from a paid plan back to free
    SUPPRESSED = "suppressed"  # a do-not-contact entry matches this business
    CALL = "call"  # logged by hand now; reported by a dialer later (source=dialer)
    NOTE = "note"
    STAGE_CHANGED = "stage_changed"  # a person moved it
    ASSIGNED = "assigned"
    TASK_DONE = "task_done"


class ActivitySource(StrEnum):
    SYSTEM = "system"
    MANUAL = "manual"
    DIALER = "dialer"


# The stage an activity moves a prospect to automatically (None: no stage effect).
AUTO_STAGE: dict[ActivityType, ProspectStage] = {
    ActivityType.DRAFT_READY: ProspectStage.NEW,
    ActivityType.SITE_PUBLISHED: ProspectStage.NEW,
    ActivityType.EMAIL_SENT: ProspectStage.CONTACTED,
    ActivityType.EMAIL_OPENED: ProspectStage.ENGAGED,
    ActivityType.LINK_CLICKED: ProspectStage.ENGAGED,
    ActivityType.CLAIM_STARTED: ProspectStage.CONVERSATION,
    ActivityType.CLAIM_APPROVED: ProspectStage.CLAIMED,
    ActivityType.SUBSCRIBED: ProspectStage.WON,
}

# Activities that mean the business reacted to us (they update `last_touch_at`). Connected calls join in C3.
ENGAGEMENT = frozenset({ActivityType.EMAIL_OPENED, ActivityType.LINK_CLICKED, ActivityType.CLAIM_STARTED,
                        ActivityType.CLAIM_APPROVED, ActivityType.SUBSCRIBED})

# Suppression reasons that block every channel. `unsubscribed`/`bounced` block email only (plan, decision R4).
BLOCKS_ALL_CHANNELS = frozenset({SuppressionReason.REQUESTED, SuppressionReason.COMPLAINT, SuppressionReason.LEGAL})


def auto_advance(current: ProspectStage, target: ProspectStage) -> ProspectStage:
    """Where an automatic event leaves a prospect.

    * Forward only along the pipeline: an old email open never undoes a claim.
    * Conversions (claimed, won) are facts and apply from anywhere, even lost or do-not-contact.
    * Otherwise a closed prospect (lost, do-not-contact) stays closed; only a person reopens it.
    * Do-not-contact applies to anyone not yet converted; customers keep their stage.
    """
    if target is ProspectStage.DO_NOT_CONTACT:
        return current if current in CONVERTED_STAGES else target
    if target in CONVERTED_STAGES and current in CLOSED_STAGES:
        return target
    if current in CLOSED_STAGES or target in CLOSED_STAGES:
        return current
    return target if PIPELINE.index(target) > PIPELINE.index(current) else current
