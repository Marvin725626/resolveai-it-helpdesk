"""Add employee requester role and invitation role selection."""
from alembic import op
from sqlalchemy import Column, String, inspect, text

revision = "e20a71d4c903"
down_revision = "d1a4f8c29b73"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if bind.dialect.name == "postgresql":
        # PostgreSQL requires ADD VALUE outside the migration transaction if the
        # new enum label is to be usable immediately by later statements.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'REQUESTER'")
    if inspector.has_table("invitations") and "role" not in {c["name"] for c in inspector.get_columns("invitations")}:
        op.add_column("invitations", Column("role", String(32), nullable=False,
                                            server_default=text("'SUPPORT_AGENT'")))


def downgrade():
    bind = op.get_bind()
    if inspect(bind).has_table("users"):
        role_sql = "role::text" if bind.dialect.name == "postgresql" else "role"
        exists = bind.execute(text(f"SELECT 1 FROM users WHERE {role_sql} = 'REQUESTER' LIMIT 1")).first()
        if exists:
            raise RuntimeError("Cannot downgrade while REQUESTER users exist; reassign or remove them first.")
    inspector = inspect(bind)
    if inspector.has_table("invitations") and "role" in {c["name"] for c in inspector.get_columns("invitations")}:
        if bind.execute(text("SELECT 1 FROM invitations WHERE role = 'REQUESTER' LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade while REQUESTER invitations exist; reassign or revoke them first.")
        op.drop_column("invitations", "role")
