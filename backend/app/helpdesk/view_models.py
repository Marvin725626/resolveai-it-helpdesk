"""Persistent personal queue views; initial request fingerprint remains immutable."""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from app.core.database import Base


class SavedQueueView(Base):
    __tablename__ = "resolveai_saved_queue_views"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "name_key", name="uq_queue_view_active_name"),)
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    request_id = Column(String(36), nullable=False, unique=True)
    creation_fingerprint = Column(String(64), nullable=False)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(50), nullable=False)
    name_key = Column(String(200), nullable=True)
    filters = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime(timezone=True), nullable=True)
