"""Add tenant-scoped one-time invitations.

Revision ID: 2d842c6f9b3a
Revises: 8c99ad4dba6a
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "2d842c6f9b3a"
down_revision: Union[str, Sequence[str], None] = "8c99ad4dba6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text("SELECT lower(email) FROM users GROUP BY lower(email) HAVING count(*) > 1 LIMIT 1")
    ).first()
    if duplicates:
        raise RuntimeError("Cannot enforce case-insensitive user email uniqueness while duplicate emails exist.")
    # A fresh database's initial migration imports current metadata and may
    # already create this index. Existing v1.4 databases need this migration
    # to add it. SQLite does not reflect expression indexes reliably, so use
    # each supported dialect's catalog instead of Inspector.get_indexes().
    if bind.dialect.name == "sqlite":
        index_exists = bind.execute(sa.text(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='uq_users_email_lower'"
        )).scalar()
    elif bind.dialect.name == "postgresql":
        index_exists = bind.execute(sa.text(
            "SELECT 1 FROM pg_indexes WHERE schemaname=current_schema() AND indexname='uq_users_email_lower'"
        )).scalar()
    else:
        raise RuntimeError(f"Unsupported database dialect for ResolveAI migrations: {bind.dialect.name}")
    if not index_exists:
        op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)
    # The historical initial revision calls Base.metadata.create_all(). Since
    # Alembic's env imports current models, a fresh database may already have
    # this table before this revision runs. Existing v1.4 databases will not.
    if not inspect(bind).has_table("invitations"):
        op.create_table(
            "invitations",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("invited_by_user_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index("ix_invitations_tenant_id", "invitations", ["tenant_id"], unique=False)
        op.create_index("ix_invitations_token_hash", "invitations", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_invitations_token_hash", table_name="invitations")
    op.drop_index("ix_invitations_tenant_id", table_name="invitations")
    op.drop_table("invitations")
    op.drop_index("uq_users_email_lower", table_name="users")
