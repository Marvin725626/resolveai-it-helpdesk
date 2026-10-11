import json
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.helpdesk.models import RunbookChunk
from app.helpdesk.retrieval import index_runbook
from app.helpdesk.tools import DATA_DIR
from app.models.tenant import Tenant
from app.models.user import User, UserRole


async def seed_demo():
    if settings.APP_ENV != "development" or not settings.IT_DEMO_ENABLED:
        return
    async with AsyncSessionLocal() as db:
        tenant = await db.scalar(select(Tenant).where(Tenant.slug == "resolveai-demo"))
        if not tenant:
            tenant = Tenant(name="ResolveAI 演示工作区", slug="resolveai-demo", plan="demo")
            db.add(tenant)
            await db.flush()
            db.add(User(tenant_id=tenant.id, email="demo@resolveai.example.com", full_name="演示支持工程师",
                        hashed_password=get_password_hash("ResolveAI123!"), role=UserRole.TENANT_OWNER))
        for item in json.loads((DATA_DIR / "runbooks.json").read_text(encoding="utf-8")):
            existing = await db.scalar(select(RunbookChunk.id).where(RunbookChunk.tenant_id == tenant.id, RunbookChunk.code == item["code"]))
            if not existing:
                await index_runbook(db, tenant.id, item)
        await db.commit()
