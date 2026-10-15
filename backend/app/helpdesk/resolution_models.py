"""Immutable public resolution rounds and requester feedback tied to one round."""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text
from app.core.database import Base


class TicketResolution(Base):
    __tablename__ = "resolveai_ticket_resolutions"
    __table_args__ = (Index("ix_resolution_scope_sequence", "tenant_id", "ticket_id", "sequence"),)
    sequence = Column(Integer, primary_key=True, autoincrement=True)
    id = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid4()))
    request_id = Column(String(36), nullable=False, unique=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    ticket_id = Column(String(36), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    category = Column(String(32), nullable=False)
    summary = Column(Text, nullable=False)
    steps = Column(Text, nullable=False, default="")
    author_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_name = Column(String(100), nullable=False)
    expected_updated_at = Column(DateTime(timezone=True), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class ResolutionSatisfaction(Base):
    __tablename__ = "resolveai_resolution_satisfaction"
    __table_args__ = (CheckConstraint("rating >= 1 AND rating <= 5", name="ck_resolution_rating"),)
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    request_id = Column(String(36), nullable=False, unique=True)
    resolution_id = Column(String(36), ForeignKey("resolveai_ticket_resolutions.id", ondelete="CASCADE"), nullable=False, unique=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    ticket_id = Column(String(36), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
