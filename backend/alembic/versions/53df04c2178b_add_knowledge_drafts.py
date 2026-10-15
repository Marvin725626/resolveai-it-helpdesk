"""Add unpublished knowledge drafts and admin review state."""
from alembic import op
from sqlalchemy import inspect

revision = "53df04c2178b"
down_revision = "b749c1e620af"
branch_labels = None
depends_on = None


def upgrade():
    from app.helpdesk.knowledge_draft_models import KnowledgeDraft
    bind = op.get_bind()
    if not inspect(bind).has_table(KnowledgeDraft.__tablename__):
        KnowledgeDraft.__table__.create(bind)


def downgrade():
    op.drop_table("resolveai_knowledge_drafts")
