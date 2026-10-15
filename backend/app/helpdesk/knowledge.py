"""Versioned knowledge lifecycle; old diagnosis evidence remains a snapshot."""
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.helpdesk.models import KnowledgeRevision, RunbookChunk
from app.helpdesk.retrieval import index_runbook
from app.helpdesk.workflow import redact


async def documents(db, tenant_id):
    chunks = (await db.scalars(select(RunbookChunk).where(RunbookChunk.tenant_id == tenant_id))).all()
    grouped = {}
    for chunk in chunks:
        grouped.setdefault(chunk.code, []).append(chunk)
    result = {}
    for code, rows in grouped.items():
        rows.sort(key=lambda row: int(row.chunk_index))
        result[code] = {"code": code, "title": rows[0].title, "keywords": rows[0].keywords,
                       "content": "\n\n".join(row.content for row in rows), "active": True,
                       "version": 0, "author": None, "updated_at": None}
    revisions = (await db.scalars(select(KnowledgeRevision).where(KnowledgeRevision.tenant_id == tenant_id)
                                .order_by(KnowledgeRevision.version))).all()
    for revision in revisions:
        result[revision.code] = {**revision.snapshot, "version": revision.version,
                                "author": revision.author_name, "updated_at": revision.created_at.isoformat() + ("+00:00" if revision.created_at.tzinfo is None else "")}
    return result


async def save_document(db, user, code, data, expected=None, action="updated", commit=True):
    current = (await documents(db, user.tenant_id)).get(code)
    if expected is None and current:
        raise HTTPException(409, "来源代码已存在，包括已停用的来源")
    if expected is not None and not current:
        raise HTTPException(404, "知识来源不存在")
    if current and current["version"] != expected:
        raise HTTPException(409, "知识已被更新，请刷新后重试")
    item = {"code": code, "title": redact(data["title"].strip()), "content": redact(data["content"].replace("\r\n", "\n").replace("\r", "\n").strip()),
            "keywords": redact(data.get("keywords", "").strip()), "active": data.get("active", True)}
    if len(item["title"]) < 2 or len(item["content"]) < 20:
        raise HTTPException(422, "标题至少两个字符，正文至少二十个字符")
    version = (current["version"] + 1) if current else 1
    try:
        if current and current["version"] == 0:
            baseline = {key: current[key] for key in ("code", "title", "content", "keywords", "active")}
            db.add(KnowledgeRevision(tenant_id=user.tenant_id, code=code, version=0, snapshot=baseline,
                                    action="legacy_snapshot", author_name=user.full_name))
        db.add(KnowledgeRevision(tenant_id=user.tenant_id, code=code, version=version, snapshot=item,
                                action=action if current else "created", author_name=user.full_name))
        await db.flush()  # Unique version prevents concurrent edits from overwriting each other.
        await db.execute(delete(RunbookChunk).where(RunbookChunk.tenant_id == user.tenant_id, RunbookChunk.code == code))
        chunks = await index_runbook(db, user.tenant_id, item) if item["active"] else 0
        if commit:
            await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "知识已被更新，请刷新后重试")
    except Exception:
        await db.rollback()
        raise
    return {**item, "version": version, "chunks": chunks}
