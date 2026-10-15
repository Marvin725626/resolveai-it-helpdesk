"""Authoring and workspace review for resolution-based knowledge drafts."""
from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.sanitizer import sanitize_text_input
from app.helpdesk.knowledge import documents, save_document
from app.helpdesk.knowledge_draft_models import KnowledgeDraft
from app.helpdesk.ticket_ops import utc
from app.helpdesk.workflow import redact
from app.models.ticket import Ticket, TicketStatus
from app.models.user import UserRole

router = APIRouter(prefix="/helpdesk/knowledge-drafts", tags=["Knowledge drafts"])
ADMIN_ROLES = (UserRole.TENANT_OWNER, UserRole.TENANT_ADMIN)
SUPPORT_ROLES = (*ADMIN_ROLES, UserRole.SUPPORT_AGENT)


class DraftCreate(BaseModel):
    request_id: UUID
    resolution_id: UUID
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=20, max_length=15000)
    keywords: str = Field(default="", max_length=500)


class DraftUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=20, max_length=15000)
    keywords: str = Field(default="", max_length=500)


class ReviewBody(BaseModel):
    expected_version: int = Field(ge=1)
    note: str = Field(default="", max_length=1000)


def admin(user):
    return user.role in ADMIN_ROLES


def safe_text(value, limit):
    return redact(sanitize_text_input(value.strip(), limit)).strip()


def draft_dict(row):
    return {"id": row.id, "request_id": row.request_id, "ticket_id": row.ticket_id,
        "resolution_id": row.resolution_id, "title": row.title, "content": row.content,
        "keywords": row.keywords, "status": row.status, "version": row.version,
        "author_id": row.author_id, "author_name": row.author_name,
        "reviewer_name": row.reviewer_name, "review_note": row.review_note,
        "published_code": row.published_code, "published_version": row.published_version,
        "created_at": _time(row.created_at), "updated_at": _time(row.updated_at),
        "reviewed_at": _time(row.reviewed_at)}


def _time(value):
    return utc(value).isoformat() if value else None


async def load_draft(db, user, draft_id):
    row = await db.scalar(select(KnowledgeDraft).where(KnowledgeDraft.id == str(draft_id),
        KnowledgeDraft.tenant_id == user.tenant_id))
    if row is None or (not admin(user) and row.author_id != user.id):
        raise HTTPException(404, "知识草稿不存在")
    return row


def check_draft_write(row, user):
    if not admin(user) and row.author_id != user.id:
        raise HTTPException(404, "知识草稿不存在")
    if row.status == "PUBLISHED":
        raise HTTPException(409, "已发布草稿不可再编辑")


async def resolution_for(db, user, ticket_id, resolution_id):
    from app.helpdesk.resolution_models import TicketResolution

    ticket = await db.scalar(select(Ticket).where(Ticket.id == str(ticket_id), Ticket.tenant_id == user.tenant_id))
    resolution = await db.scalar(select(TicketResolution).where(TicketResolution.id == str(resolution_id),
        TicketResolution.ticket_id == str(ticket_id), TicketResolution.tenant_id == user.tenant_id))
    if ticket is None or resolution is None:
        raise HTTPException(404, "解决快照不存在")
    if ticket.status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        raise HTTPException(409, "仅已解决的工单可以创建知识草稿")
    if user.role == UserRole.SUPPORT_AGENT and ticket.assigned_agent_id != user.id:
        raise HTTPException(403, "仅当前接手人或工作区管理员可创建草稿")
    if user.role not in SUPPORT_ROLES:
        raise HTTPException(403, "需要工作区支持权限")
    current_id = await db.scalar(select(TicketResolution.id).where(
        TicketResolution.tenant_id == user.tenant_id, TicketResolution.ticket_id == ticket.id)
        .order_by(TicketResolution.sequence.desc()).limit(1))
    if current_id != resolution.id:
        raise HTTPException(409, "解决快照已更新，请刷新后重试")
    locked = await db.execute(update(Ticket).where(Ticket.id == ticket.id,
        Ticket.tenant_id == user.tenant_id, Ticket.status.in_((TicketStatus.RESOLVED, TicketStatus.CLOSED)),
        Ticket.resolved_at == ticket.resolved_at).values(updated_at=Ticket.updated_at))
    if locked.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "工单状态已变化，请刷新后重试")
    return ticket, resolution


def can_edit(row, user):
    return row.status != "PUBLISHED" and (admin(user) or row.author_id == user.id)


def request_fingerprint(resolution_id, title, content, keywords):
    raw = json.dumps([str(resolution_id), title, content, keywords], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@router.get("")
async def list_drafts(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50),
        status: str | None = Query(None, pattern="^(DRAFT|PUBLISHED|REJECTED)$"),
        user=Depends(get_current_user), db=Depends(get_db)):
    conditions = [KnowledgeDraft.tenant_id == user.tenant_id]
    if not admin(user):
        conditions.append(KnowledgeDraft.author_id == user.id)
    if status:
        conditions.append(KnowledgeDraft.status == status)
    query = select(KnowledgeDraft).where(*conditions)
    rows = list((await db.scalars(query.order_by(KnowledgeDraft.sequence.desc())
        .offset((page - 1) * page_size).limit(page_size + 1))).all())
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    return {"items": [draft_dict(row) for row in rows], "page": page,
        "page_size": page_size, "has_more": has_more,
        "can_review": admin(user), "can_create": user.role in SUPPORT_ROLES}


@router.get("/{draft_id}")
async def get_draft(draft_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    row = await load_draft(db, user, draft_id)
    from app.helpdesk.resolution_models import TicketResolution
    resolution = await db.scalar(select(TicketResolution).where(TicketResolution.id == row.resolution_id,
        TicketResolution.ticket_id == row.ticket_id, TicketResolution.tenant_id == user.tenant_id))
    snapshot = None if resolution is None else {"id": resolution.id, "category": resolution.category,
        "summary": resolution.summary, "steps": resolution.steps,
        "author_name": resolution.author_name, "resolved_at": _time(resolution.resolved_at)}
    return {"draft": draft_dict(row), "resolution": snapshot,
        "can_edit": can_edit(row, user), "can_review": admin(user)}


@router.post("", status_code=201)
async def create_draft(data: DraftCreate, user=Depends(get_current_user), db=Depends(get_db)):
    tenant_id, author_id, author_name = user.tenant_id, user.id, user.full_name
    title = safe_text(data.title, 200)
    content = safe_text(data.content, 15000)
    keywords = safe_text(data.keywords, 500)
    if len(title) < 2 or len(content) < 20:
        raise HTTPException(422, "标题至少两个字符，正文至少二十个字符")
    fingerprint = request_fingerprint(data.resolution_id, title, content, keywords)
    existing = await db.scalar(select(KnowledgeDraft).where(KnowledgeDraft.tenant_id == tenant_id,
        KnowledgeDraft.request_id == str(data.request_id)))
    if existing:
        if existing.author_id != author_id or existing.request_fingerprint != fingerprint:
            raise HTTPException(409, "请求编号已用于另一份草稿")
        return {"draft": draft_dict(existing), "cached": True}
    from app.helpdesk.resolution_models import TicketResolution
    resolution = await db.scalar(select(TicketResolution).where(TicketResolution.id == str(data.resolution_id),
        TicketResolution.tenant_id == tenant_id))
    if resolution is None:
        raise HTTPException(404, "解决快照不存在")
    ticket, resolution = await resolution_for(db, user, resolution.ticket_id, data.resolution_id)
    row = KnowledgeDraft(request_id=str(data.request_id), tenant_id=tenant_id,
        request_fingerprint=fingerprint,
        ticket_id=ticket.id, resolution_id=resolution.id, author_id=author_id,
        author_name=author_name, title=title, content=content, keywords=keywords,
        status="DRAFT", version=1)
    db.add(row)
    try:
        await db.commit()
        await db.refresh(row)
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(select(KnowledgeDraft).where(KnowledgeDraft.tenant_id == tenant_id,
            KnowledgeDraft.request_id == str(data.request_id)))
        if existing and existing.author_id == author_id and existing.request_fingerprint == fingerprint:
            return {"draft": draft_dict(existing), "cached": True}
        raise HTTPException(409, "知识草稿请求冲突")
    return {"draft": draft_dict(row), "cached": False}


@router.put("/{draft_id}")
async def update_draft(draft_id: UUID, data: DraftUpdate,
        user=Depends(get_current_user), db=Depends(get_db)):
    row = await load_draft(db, user, draft_id)
    check_draft_write(row, user)
    title = safe_text(data.title, 200)
    content = safe_text(data.content, 15000)
    keywords = safe_text(data.keywords, 500)
    if len(title) < 2 or len(content) < 20:
        raise HTTPException(422, "标题至少两个字符，正文至少二十个字符")
    now = datetime.now(timezone.utc)
    status = "DRAFT" if row.status == "REJECTED" else row.status
    changed = await db.execute(update(KnowledgeDraft).where(KnowledgeDraft.id == row.id,
        KnowledgeDraft.tenant_id == user.tenant_id, KnowledgeDraft.version == data.expected_version,
        KnowledgeDraft.status.in_(("DRAFT", "REJECTED"))).values(title=title, content=content,
            keywords=keywords, status=status, version=KnowledgeDraft.version + 1,
            reviewer_id=None, reviewer_name=None, review_note=None, reviewed_at=None, updated_at=now))
    if changed.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "草稿已被更新，请刷新后重试")
    await db.commit()
    await db.refresh(row)
    return draft_dict(row)


def manager(user):
    if not admin(user):
        raise HTTPException(403, "仅工作区管理员可以审核知识草稿")


@router.post("/{draft_id}/reject")
async def reject_draft(draft_id: UUID, data: ReviewBody,
        user=Depends(get_current_user), db=Depends(get_db)):
    manager(user)
    row = await load_draft(db, user, draft_id)
    if row.status != "DRAFT":
        raise HTTPException(409, "只有待审核草稿可以驳回")
    note = safe_text(data.note, 1000)
    if len(note) < 1:
        raise HTTPException(422, "驳回时必须填写说明")
    changed = await db.execute(update(KnowledgeDraft).where(KnowledgeDraft.id == row.id,
        KnowledgeDraft.tenant_id == user.tenant_id, KnowledgeDraft.status == "DRAFT",
        KnowledgeDraft.version == data.expected_version).values(status="REJECTED",
            version=KnowledgeDraft.version + 1, reviewer_id=user.id, reviewer_name=user.full_name,
            review_note=note, reviewed_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
    if changed.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "草稿已被更新，请刷新后重试")
    await db.commit()
    await db.refresh(row)
    return draft_dict(row)


async def next_code(db, user, sequence):
    current = await documents(db, user.tenant_id)
    for offset in range(100000):
        code = f"KD-{(sequence + offset - 1) % 100000 + 1:05d}"
        if code not in current:
            return code
    raise HTTPException(409, "无法分配知识来源代码")


@router.post("/{draft_id}/publish")
async def publish_draft(draft_id: UUID, data: ReviewBody,
        user=Depends(get_current_user), db=Depends(get_db)):
    manager(user)
    row = await load_draft(db, user, draft_id)
    if row.status == "PUBLISHED":
        return {"draft": draft_dict(row), "source_code": row.published_code,
            "source_version": row.published_version, "cached": True}
    if row.status != "DRAFT":
        raise HTTPException(409, "只有待审核草稿可以发布")
    from app.helpdesk.resolution_models import TicketResolution
    resolution = await db.scalar(select(TicketResolution).where(
        TicketResolution.id == row.resolution_id, TicketResolution.ticket_id == row.ticket_id,
        TicketResolution.tenant_id == user.tenant_id))
    ticket, _ = await resolution_for(db, user, row.ticket_id, row.resolution_id)
    if resolution is None or utc(resolution.resolved_at) != utc(ticket.resolved_at):
        raise HTTPException(409, "原解决结果已过期，不能发布此草稿")
    code = await next_code(db, user, row.sequence)
    now = datetime.now(timezone.utc)
    changed = await db.execute(update(KnowledgeDraft).where(KnowledgeDraft.id == row.id,
        KnowledgeDraft.tenant_id == user.tenant_id, KnowledgeDraft.status == "DRAFT",
        KnowledgeDraft.version == data.expected_version).values(status="PUBLISHED",
            version=KnowledgeDraft.version + 1, reviewer_id=user.id, reviewer_name=user.full_name,
            review_note=safe_text(data.note, 1000), reviewed_at=now, updated_at=now,
            published_code=code))
    if changed.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "草稿已被更新，请刷新后重试")
    try:
        source = await save_document(db, user, code, {"title": row.title,
            "content": row.content, "keywords": row.keywords, "active": True},
            expected=None, action="draft_published", commit=False)
        await db.execute(update(KnowledgeDraft).where(KnowledgeDraft.id == row.id).values(
            published_version=source["version"]))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(row)
    return {"draft": draft_dict(row), "source_code": code,
        "source_version": source["version"], "cached": False}
