"""Add public ticket reply thread."""
from alembic import op
from sqlalchemy import inspect

revision = "1f39c0a8e34b"
down_revision = "541b92e07c31"
branch_labels = None
depends_on = None


def upgrade():
    from app.helpdesk.models import HelpdeskTicketReply
    bind = op.get_bind()
    if not inspect(bind).has_table(HelpdeskTicketReply.__tablename__):
        HelpdeskTicketReply.__table__.create(bind)


def downgrade():
    op.drop_table("resolveai_ticket_replies")
