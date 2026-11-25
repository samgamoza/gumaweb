"""prospect outbound priority (channels, reachable, scored_at) and the draft_ready activity (outbound engine A1)

Existing prospects get no channels and reachable=false until rescored: run `python -m app.cli rescore-prospects`.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-26 01:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = '0012'
down_revision: str | None = '0011'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TYPES = ("site_published", "email_sent", "email_opened", "link_clicked", "unsubscribed", "claim_started",
             "claim_approved", "claim_rejected", "subscribed", "churned", "suppressed", "call", "note",
             "stage_changed", "assigned", "task_done")
NEW_TYPES = ("draft_ready",) + OLD_TYPES

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql')


def _set_activity_types(values: tuple[str, ...]) -> None:
    """Enum values live in a named CHECK constraint (ADR-4): rewrite it by hand."""
    condition = "type IN (" + ", ".join(f"'{v}'" for v in values) + ")"
    recreate = "always" if op.get_bind().dialect.name == "sqlite" else "auto"
    with op.batch_alter_table('prospect_activities', recreate=recreate) as batch:
        batch.drop_constraint(op.f('ck_prospect_activities_activitytype'), type_='check')
        batch.create_check_constraint('activitytype', condition)


def upgrade() -> None:
    with op.batch_alter_table('prospects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('channels', JSON, server_default=sa.text("'[]'"), nullable=False))
        batch_op.add_column(sa.Column('reachable', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('scored_at', sa.DateTime(timezone=True), nullable=True))
    _set_activity_types(NEW_TYPES)


def downgrade() -> None:
    op.execute("DELETE FROM prospect_activities WHERE type = 'draft_ready'")
    _set_activity_types(OLD_TYPES)
    with op.batch_alter_table('prospects', schema=None) as batch_op:
        batch_op.drop_column('scored_at')
        batch_op.drop_column('reachable')
        batch_op.drop_column('channels')
