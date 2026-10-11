import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint

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
