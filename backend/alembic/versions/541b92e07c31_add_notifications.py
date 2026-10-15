"""Add personal ticket notifications without backfilling historical events."""
from alembic import op
from sqlalchemy import inspect

revision = "541b92e07c31"
down_revision = "2d842c6f9b3a"
branch_labels = None
depends_on = None


def upgrade():
    # The original initial revision creates current metadata on fresh installs.
    from app.helpdesk.models import HelpdeskNotification
    bind = op.get_bind()
    if not inspect(bind).has_table(HelpdeskNotification.__tablename__):
        HelpdeskNotification.__table__.create(bind)


def downgrade():
    op.drop_table("resolveai_notifications")
