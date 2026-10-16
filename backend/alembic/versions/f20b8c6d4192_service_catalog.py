"""Add versioned tenant service catalog."""
from alembic import op
from sqlalchemy import inspect

revision = "f20b8c6d4192"
down_revision = "e20a71d4c903"
branch_labels = None
depends_on = None


def upgrade():
    from app.helpdesk.catalog_models import ServiceCatalogItem, CatalogRevision
    bind = op.get_bind()
    for model in (ServiceCatalogItem, CatalogRevision):
        if not inspect(bind).has_table(model.__tablename__):
            model.__table__.create(bind)


def downgrade():
    op.drop_table("resolveai_service_catalog_revisions")
    op.drop_table("resolveai_service_catalog_items")
