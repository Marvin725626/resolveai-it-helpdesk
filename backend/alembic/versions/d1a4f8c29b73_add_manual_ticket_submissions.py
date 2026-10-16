from alembic import op
from sqlalchemy import inspect

revision = "d1a4f8c29b73"
down_revision = "c7e60b9124d8"
branch_labels = None
depends_on = None


def upgrade():
    from app.helpdesk.models import ManualTicketSubmission
    bind = op.get_bind()
    if not inspect(bind).has_table(ManualTicketSubmission.__tablename__):
        ManualTicketSubmission.__table__.create(bind)


def downgrade():
    op.drop_table("resolveai_manual_ticket_submissions")
