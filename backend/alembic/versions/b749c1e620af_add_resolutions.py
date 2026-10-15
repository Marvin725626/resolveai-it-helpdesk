"""Add immutable public resolution rounds and per-round requester satisfaction."""
from alembic import op
from sqlalchemy import inspect

revision = "b749c1e620af"
down_revision = "a38d24e5b791"
branch_labels = None
depends_on = None


def upgrade():
    from app.helpdesk.resolution_models import TicketResolution, ResolutionSatisfaction
    bind = op.get_bind()
    for model in (TicketResolution, ResolutionSatisfaction):
        if not inspect(bind).has_table(model.__tablename__):
            model.__table__.create(bind)


def downgrade():
    op.drop_table("resolveai_resolution_satisfaction")
    op.drop_table("resolveai_ticket_resolutions")
