import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.core.config import settings
from app.core.database import Base


class RunbookChunk(Base):
    __tablename__ = "resolveai_chunks"
    __table_args__ = (UniqueConstraint("tenant_id", "code", "chunk_index"),)
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    code = Column(String(50), nullable=False)
    chunk_index = Column(String(10), nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    keywords = Column(Text, nullable=False, default="")
    search_text = Column(Text, nullable=False)
    embedding = Column(Vector(settings.IT_EMBEDDING_DIMENSION).with_variant(JSON, "sqlite"), nullable=False)
    embedding_provider = Column(String(100), nullable=False)


class HelpdeskRun(Base):
    __tablename__ = "resolveai_runs"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    question = Column(Text, nullable=False)
    result = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class HelpdeskTicketEvent(Base):
    """Append-only through Helpdesk APIs; not a tamper-proof compliance log."""
    __tablename__ = "resolveai_ticket_events"
    sequence = Column(Integer, primary_key=True, autoincrement=True)
    id = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    ticket_id = Column(String(36), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_name = Column(String(100), nullable=False)
    event_type = Column(String(32), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class HelpdeskTicketReply(Base):
    __tablename__ = "resolveai_ticket_replies"
    __table_args__ = (UniqueConstraint("request_id", name="uq_resolveai_ticket_reply_request"),)
    sequence = Column(Integer, primary_key=True, autoincrement=True)
    id = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    request_id = Column(String(36), nullable=False)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    ticket_id = Column(String(36), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_name = Column(String(100), nullable=False)
    direction = Column(String(16), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class HelpdeskTicketAttachment(Base):
    __tablename__ = "resolveai_ticket_attachments"
    __table_args__ = (Index("ix_ticket_attachments_scope_sequence", "tenant_id", "ticket_id", "sequence"),)
    sequence = Column(Integer, primary_key=True, autoincrement=True)
    id = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    request_id = Column(String(36), nullable=False, unique=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    ticket_id = Column(String(36), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    uploader_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    uploader_name = Column(String(100), nullable=False)
    direction = Column(String(16), nullable=False)
    filename = Column(String(180), nullable=False)
    content_type = Column(String(40), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    storage_key = Column(String(80), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class HelpdeskNotification(Base):
    __tablename__ = "resolveai_notifications"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id", name="uq_notification_event_user"),
        Index("ix_resolveai_notifications_scope_sequence", "tenant_id", "user_id", "sequence"),
    )
    sequence = Column(Integer, primary_key=True, autoincrement=True)
    id = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    ticket_id = Column(String(36), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    event_id = Column(String(36), ForeignKey("resolveai_ticket_events.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(32), nullable=False)
    title = Column(String(100), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    read_at = Column(DateTime(timezone=True), nullable=True)


class KnowledgeRevision(Base):
    __tablename__ = "resolveai_knowledge_revisions"
    __table_args__ = (UniqueConstraint("tenant_id", "code", "version"),)
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    code = Column(String(50), nullable=False)
    version = Column(Integer, nullable=False)
    snapshot = Column(JSON, nullable=False)
    action = Column(String(32), nullable=False)
    author_name = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


Index("ix_resolveai_runs_scope_time", HelpdeskRun.tenant_id, HelpdeskRun.user_id, HelpdeskRun.created_at, HelpdeskRun.id)
from app.models.ticket import Ticket
Index("ix_resolveai_tickets_scope_time", Ticket.tenant_id, Ticket.created_at, Ticket.id)
