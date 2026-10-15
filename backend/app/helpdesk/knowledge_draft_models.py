"""Reviewable, unpublished knowledge drafts sourced from public resolutions."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from app.core.database import Base


class KnowledgeDraft(Base):
    __tablename__ = "resolveai_knowledge_drafts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "request_id", name="uq_knowledge_draft_tenant_request"),
        Index("ix_knowledge_drafts_scope_state_sequence", "tenant_id", "status", "sequence"),
    )
    sequence = Column(Integer, primary_key=True, autoincrement=True)
    id = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    request_id = Column(String(36), nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    ticket_id = Column(String(36), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    resolution_id = Column(String(36), ForeignKey("resolveai_ticket_resolutions.id", ondelete="CASCADE"), nullable=False)
    author_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_name = Column(String(100), nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    keywords = Column(String(500), nullable=False, default="")
    status = Column(String(16), nullable=False, default="DRAFT")
    version = Column(Integer, nullable=False, default=1)
    reviewer_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewer_name = Column(String(100), nullable=True)
    review_note = Column(String(1000), nullable=True)
    published_code = Column(String(50), nullable=True)
    published_version = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
