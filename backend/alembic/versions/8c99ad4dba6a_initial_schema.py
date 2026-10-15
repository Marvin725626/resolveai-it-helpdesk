"""Initial complete multi-tenant schema migration.

Revision ID: 8c99ad4dba6a
Revises: None
Create Date: 2026-10-03 04:01:14
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from app.core.database import Base
import app.models.tenant  # noqa
import app.models.user  # noqa
import app.models.customer  # noqa
import app.models.conversation  # noqa
import app.models.document  # noqa
import app.models.ticket  # noqa
import app.models.analytics  # noqa
import app.models.audit_log  # noqa

# revision identifiers, used by Alembic.
revision: str = '8c99ad4dba6a'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all initial application tables if they do not exist."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # pgvector's type must exist before any Vector columns are created.
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("CREATE INDEX IF NOT EXISTS resolveai_embedding_hnsw ON resolveai_chunks USING hnsw (embedding vector_cosine_ops)"))
        bind.execute(sa.text("CREATE INDEX IF NOT EXISTS resolveai_search_gin ON resolveai_chunks USING gin (to_tsvector('simple', search_text))"))


def downgrade() -> None:
    """Drop all initial application tables."""
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
