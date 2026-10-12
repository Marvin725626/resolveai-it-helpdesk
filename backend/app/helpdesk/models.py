import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint

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
