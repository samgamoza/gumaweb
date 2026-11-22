"""platform expansion: crm, booking, chatbot

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-22 08:51:58.598455+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_COMPONENT_TYPES = ("hero", "about", "services", "gallery", "testimonials", "faq", "cta", "contact", "map", "footer")
NEW_COMPONENT_TYPES = OLD_COMPONENT_TYPES + ("booking",)


def _set_component_types(values: tuple[str, ...]) -> None:
    """Enums are VARCHAR + named CHECK (ADR-4); autogenerate cannot see value changes, so update it here."""
    condition = "component_type IN (" + ", ".join(f"'{v}'" for v in values) + ")"
    recreate = "always" if op.get_bind().dialect.name == "sqlite" else "auto"  # SQLite: copy-and-move
    with op.batch_alter_table("template_components", recreate=recreate) as batch:
        batch.drop_constraint(op.f("ck_template_components_componenttype"), type_="check")
        batch.create_check_constraint("componenttype", condition)


def upgrade() -> None:
    op.create_table('booking_settings',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('slot_minutes', sa.Integer(), nullable=False),
    sa.Column('buffer_minutes', sa.Integer(), nullable=False),
    sa.Column('lead_time_hours', sa.Integer(), nullable=False),
    sa.Column('max_days_ahead', sa.Integer(), nullable=False),
    sa.Column('auto_confirm', sa.Boolean(), nullable=False),
    sa.Column('weekly_hours', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('services', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_booking_settings_business_id_businesses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('business_id', name=op.f('pk_booking_settings'))
    )
    op.create_table('chatbot_settings',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('greeting', sa.String(length=300), nullable=False),
    sa.Column('handoff_message', sa.String(length=300), nullable=False),
    sa.Column('collect_leads', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_chatbot_settings_business_id_businesses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('business_id', name=op.f('pk_chatbot_settings'))
    )
    op.create_table('contacts',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('source', sa.Enum('contact_form', 'booking', 'chatbot', 'manual', 'phone', name='contactsource', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('stage', sa.Enum('new', 'contacted', 'qualified', 'won', 'lost', name='contactstage', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('value_cents', sa.Integer(), nullable=True),
    sa.Column('tags', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_contacts_business_id_businesses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contacts'))
    )
    op.create_index('ix_contacts_business_stage', 'contacts', ['business_id', 'stage'], unique=False)
    op.create_index(op.f('ix_contacts_last_activity_at'), 'contacts', ['last_activity_at'], unique=False)
    op.create_index('uq_contacts_business_email', 'contacts', ['business_id', 'email'], unique=True, postgresql_where=sa.text('email IS NOT NULL'), sqlite_where=sa.text('email IS NOT NULL'))
    op.create_index('uq_contacts_business_phone', 'contacts', ['business_id', 'phone'], unique=True, postgresql_where=sa.text('phone IS NOT NULL'), sqlite_where=sa.text('phone IS NOT NULL'))
    op.create_table('knowledge_entries',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('section', sa.String(length=64), nullable=True),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_knowledge_entries_business_id_businesses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_entries'))
    )
    op.create_index(op.f('ix_knowledge_entries_business_id'), 'knowledge_entries', ['business_id'], unique=False)
    op.create_table('appointments',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('contact_id', sa.Uuid(), nullable=True),
    sa.Column('service_name', sa.String(length=120), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.Enum('pending', 'confirmed', 'cancelled', 'completed', 'no_show', name='appointmentstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('customer_name', sa.String(length=200), nullable=False),
    sa.Column('customer_email', sa.String(length=320), nullable=True),
    sa.Column('customer_phone', sa.String(length=32), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('manage_token_hash', sa.String(length=64), nullable=False),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_appointments_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_appointments_contact_id_contacts'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_appointments')),
    sa.UniqueConstraint('manage_token_hash', name=op.f('uq_appointments_manage_token_hash'))
    )
    op.create_index('ix_appointments_business_start', 'appointments', ['business_id', 'starts_at'], unique=False)
    op.create_index('uq_appointments_business_start_active', 'appointments', ['business_id', 'starts_at'], unique=True, postgresql_where=sa.text("status IN ('pending', 'confirmed')"), sqlite_where=sa.text("status IN ('pending', 'confirmed')"))
    op.create_table('chat_conversations',
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.Column('session_token_hash', sa.String(length=64), nullable=False),
    sa.Column('contact_id', sa.Uuid(), nullable=True),
    sa.Column('message_count', sa.Integer(), nullable=False),
    sa.Column('lead_captured', sa.Boolean(), nullable=False),
    sa.Column('visitor_hash', sa.String(length=64), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('last_message_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], name=op.f('fk_chat_conversations_business_id_businesses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_chat_conversations_contact_id_contacts'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_chat_conversations')),
    sa.UniqueConstraint('session_token_hash', name=op.f('uq_chat_conversations_session_token_hash'))
    )
    op.create_index(op.f('ix_chat_conversations_business_id'), 'chat_conversations', ['business_id'], unique=False)
    op.create_index(op.f('ix_chat_conversations_last_message_at'), 'chat_conversations', ['last_message_at'], unique=False)
    op.create_table('contact_activities',
    sa.Column('contact_id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.Enum('note', 'call', 'email', 'meeting', 'stage_change', 'form_submission', 'booking', 'chat', name='activitytype', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_contact_activities_contact_id_contacts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_contact_activities_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contact_activities'))
    )
    op.create_index(op.f('ix_contact_activities_contact_id'), 'contact_activities', ['contact_id'], unique=False)
    op.create_table('chat_messages',
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('strategy', sa.String(length=16), nullable=True),
    sa.Column('sources', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=True),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['chat_conversations.id'], name=op.f('fk_chat_messages_conversation_id_chat_conversations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_chat_messages'))
    )
    op.create_index(op.f('ix_chat_messages_conversation_id'), 'chat_messages', ['conversation_id'], unique=False)
    with op.batch_alter_table('leads') as batch:  # batch: SQLite cannot ALTER constraints in place
        batch.add_column(sa.Column('contact_id', sa.Uuid(), nullable=True))
        batch.create_foreign_key(op.f('fk_leads_contact_id_contacts'), 'contacts', ['contact_id'], ['id'],
                                 ondelete='SET NULL')

    _set_component_types(NEW_COMPONENT_TYPES)


def downgrade() -> None:
    op.execute("DELETE FROM template_components WHERE component_type = 'booking'")
    _set_component_types(OLD_COMPONENT_TYPES)
    with op.batch_alter_table('leads') as batch:
        batch.drop_constraint(op.f('fk_leads_contact_id_contacts'), type_='foreignkey')
        batch.drop_column('contact_id')
    op.drop_index(op.f('ix_chat_messages_conversation_id'), table_name='chat_messages')
    op.drop_table('chat_messages')
    op.drop_index(op.f('ix_contact_activities_contact_id'), table_name='contact_activities')
    op.drop_table('contact_activities')
    op.drop_index(op.f('ix_chat_conversations_last_message_at'), table_name='chat_conversations')
    op.drop_index(op.f('ix_chat_conversations_business_id'), table_name='chat_conversations')
    op.drop_table('chat_conversations')
    op.drop_index('uq_appointments_business_start_active', table_name='appointments', postgresql_where=sa.text("status IN ('pending', 'confirmed')"), sqlite_where=sa.text("status IN ('pending', 'confirmed')"))
    op.drop_index('ix_appointments_business_start', table_name='appointments')
    op.drop_table('appointments')
    op.drop_index(op.f('ix_knowledge_entries_business_id'), table_name='knowledge_entries')
    op.drop_table('knowledge_entries')
    op.drop_index('uq_contacts_business_phone', table_name='contacts', postgresql_where=sa.text('phone IS NOT NULL'), sqlite_where=sa.text('phone IS NOT NULL'))
    op.drop_index('uq_contacts_business_email', table_name='contacts', postgresql_where=sa.text('email IS NOT NULL'), sqlite_where=sa.text('email IS NOT NULL'))
    op.drop_index(op.f('ix_contacts_last_activity_at'), table_name='contacts')
    op.drop_index('ix_contacts_business_stage', table_name='contacts')
    op.drop_table('contacts')
    op.drop_table('chatbot_settings')
    op.drop_table('booking_settings')
