"""Add private ticket attachments."""
from alembic import op
from sqlalchemy import inspect

revision = "a38d24e5b791"
down_revision = "1f39c0a8e34b"
branch_labels = None
depends_on = None


def upgrade():
    from app.helpdesk.models import HelpdeskTicketAttachment
    bind = op.get_bind()
    if not inspect(bind).has_table(HelpdeskTicketAttachment.__tablename__):
        HelpdeskTicketAttachment.__table__.create(bind)


def downgrade():
    op.drop_table("resolveai_ticket_attachments")
