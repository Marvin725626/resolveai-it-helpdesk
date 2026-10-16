"""Versioned, tenant-scoped service catalog and immutable revision snapshots."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint

from app.core.database import Base


class ServiceCatalogItem(Base):
    __tablename__ = "resolveai_service_catalog_items"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_service_catalog_tenant_code"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(40), nullable=False)
    title = Column(String(120), nullable=False)
    summary = Column(Text, nullable=False, default="")
    category = Column(String(20), nullable=False)
    fields = Column(JSON, nullable=False, default=list)
    status = Column(String(20), nullable=False, default="draft")
    version = Column(Integer, nullable=False, default=1)
    creation_request_id = Column(String(36), nullable=False, unique=True)
    creation_fingerprint = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class CatalogRevision(Base):
    __tablename__ = "resolveai_service_catalog_revisions"
    __table_args__ = (UniqueConstraint("item_id", "version", name="uq_service_catalog_revision_version"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    item_id = Column(String(36), ForeignKey("resolveai_service_catalog_items.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    snapshot = Column(JSON, nullable=False)
    actor_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
