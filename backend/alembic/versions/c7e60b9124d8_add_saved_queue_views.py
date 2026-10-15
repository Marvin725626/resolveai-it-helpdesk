"""Add persistent personal queue views."""
from alembic import op
from sqlalchemy import inspect

revision = "c7e60b9124d8"
down_revision = "53df04c2178b"
branch_labels = None
depends_on = None


def upgrade():
    from app.helpdesk.view_models import SavedQueueView
    bind = op.get_bind()
    if not inspect(bind).has_table(SavedQueueView.__tablename__):
        SavedQueueView.__table__.create(bind)


def downgrade():
    op.drop_table("resolveai_saved_queue_views")
