from uuid import UUID
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.api.deps import get_current_user
from app.core.database import get_db
from app.helpdesk.knowledge import documents, save_document
from app.helpdesk.models import KnowledgeRevision, HelpdeskRun
from app.helpdesk.retrieval import retrieve
from app.helpdesk.workflow import redact
from app.models.user import UserRole

router = APIRouter(prefix="/helpdesk", tags=["Knowledge lifecycle and run recovery"])

def admin(user):
    if user.role not in (UserRole.TENANT_OWNER, UserRole.TENANT_ADMIN):
        raise HTTPException(403, "仅工作区管理员可以维护知识")

class SourceBody(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=20, max_length=15000)
    keywords: str = Field(default="", max_length=500)
    active: bool = Field(default=True, strict=True)

class SourceCreate(SourceBody):
    code: str = Field(pattern=r"^[A-Z]{2,10}-\d{3,5}$")

class SourceUpdate(SourceBody):
    expected_version: int = Field(ge=0)

class SearchBody(BaseModel):
    query: str = Field(min_length=4, max_length=2000)

class RestoreBody(BaseModel):
    expected_version: int = Field(ge=0)
    version: int = Field(ge=0)

@router.get("/knowledge")
async def list_sources(user=Depends(get_current_user), db=Depends(get_db)):
    return sorted((await documents(db, user.tenant_id)).values(), key=lambda item: item["code"])

@router.get("/knowledge/export")
async def export_sources(user=Depends(get_current_user), db=Depends(get_db)):
    admin(user)
    return {"format": "resolveai-knowledge-v1", "exported_at": datetime.now(timezone.utc),
            "sources": list((await documents(db, user.tenant_id)).values())}

@router.post("/knowledge/search")
async def preview_search(data: SearchBody, user=Depends(get_current_user), db=Depends(get_db)):
    query = redact(data.query.strip())
    if len(query) < 4:
        raise HTTPException(422, "检索问题至少四个字符")
    return {"query": query, "results": await retrieve(db, user.tenant_id, query), "creates_run": False}

@router.post("/knowledge", status_code=201)
async def create_source(data: SourceCreate, user=Depends(get_current_user), db=Depends(get_db)):
    admin(user)
    return await save_document(db, user, data.code, data.model_dump(), action="created")

@router.put("/knowledge/{code}")
async def edit_source(code: str, data: SourceUpdate, user=Depends(get_current_user), db=Depends(get_db)):
    admin(user)
    return await save_document(db, user, code, data.model_dump(), data.expected_version,
                               "updated" if data.active else "archived")

@router.get("/knowledge/{code}/revisions")
async def source_revisions(code: str, user=Depends(get_current_user), db=Depends(get_db)):
    if code not in await documents(db, user.tenant_id):
        raise HTTPException(404, "知识来源不存在")
    rows = (await db.scalars(select(KnowledgeRevision).where(KnowledgeRevision.tenant_id == user.tenant_id,
                KnowledgeRevision.code == code).order_by(KnowledgeRevision.version.desc()).limit(30))).all()
    return [{"version": row.version, "action": row.action, "author": row.author_name,
             "created_at": row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at,
             "snapshot": row.snapshot} for row in rows]

@router.post("/knowledge/{code}/restore")
async def restore_source(code: str, data: RestoreBody, user=Depends(get_current_user), db=Depends(get_db)):
    admin(user)
    revision = await db.scalar(select(KnowledgeRevision).where(KnowledgeRevision.tenant_id == user.tenant_id,
                KnowledgeRevision.code == code, KnowledgeRevision.version == data.version))
    if not revision:
        raise HTTPException(404, "版本不存在")
    return await save_document(db, user, code, revision.snapshot, data.expected_version, "restored")

@router.post("/runs/{run_id}/recover")
async def recover_run(run_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=180)
    run = await db.scalar(select(HelpdeskRun).where(HelpdeskRun.id == str(run_id),
                 HelpdeskRun.tenant_id == user.tenant_id, HelpdeskRun.user_id == user.id))
    if not run:
        raise HTTPException(404, "Run not found")
    if run.result.get("status") != "running":
        raise HTTPException(409, "只有未完成的运行可以标记中断")
    created = run.created_at if run.created_at.tzinfo else run.created_at.replace(tzinfo=timezone.utc)
    if created > cutoff:
        raise HTTPException(409, "运行尚未超过三分钟，请等待诊断完成")
    result = {"run_id": run.id, "status": "interrupted", "trace": [],
              "error": "运行超时，已由用户标记中断。可使用新请求重新诊断。",
              "recovered_at": datetime.now(timezone.utc).isoformat()}
    changed = await db.execute(update(HelpdeskRun).where(HelpdeskRun.id == run.id,
        HelpdeskRun.result["status"].as_string() == "running").values(result=result))
    if changed.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "运行状态已改变，请刷新")
    await db.commit()
    return result


@router.get("/runs/{run_id}")
async def read_run(run_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    run = await db.scalar(select(HelpdeskRun).where(HelpdeskRun.id == str(run_id),
                 HelpdeskRun.tenant_id == user.tenant_id, HelpdeskRun.user_id == user.id))
    if not run:
        raise HTTPException(404, "Run not found")
    return {"id": run.id, "question": run.question, "result": run.result}
