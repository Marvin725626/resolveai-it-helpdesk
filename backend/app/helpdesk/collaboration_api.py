"""Workspace-scoped assignment and cursor-based ticket history."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_current_user
from app.core.database import get_db
from app.helpdesk.api import operator, utc_time
from app.helpdesk.models import HelpdeskTicketEvent
from app.helpdesk.ticket_ops import FINISHED, atomic_change, check_revision, find_ticket, record_event
from app.helpdesk.workflow import redact
from app.models.user import User, UserRole

router = APIRouter(prefix="/helpdesk", tags=["Ticket collaboration"])
MANAGERS = (UserRole.TENANT_OWNER, UserRole.TENANT_ADMIN)
SUPPORT_ROLES = (*MANAGERS, UserRole.SUPPORT_AGENT)


def manager(user):
    if user.role not in MANAGERS:
        raise HTTPException(403, "只有工作区管理员可以分派或转交工单")


class AssignmentRequest(BaseModel):
    request_id: UUID
    agent_id: UUID | None
    reason: str = Field(min_length=2, max_length=1000)
    expected_updated_at: datetime


@router.get("/assignees")
async def assignees(q: str = Query(default="", max_length=100),
                    user=Depends(get_current_user), db=Depends(get_db)):
    manager(user)
    conditions = [User.tenant_id == user.tenant_id, User.is_active.is_(True), User.role.in_(SUPPORT_ROLES)]
    if q.strip():
        conditions.append(User.full_name.icontains(q.strip(), autoescape=True))
    total = await db.scalar(select(func.count()).select_from(User).where(*conditions))
    rows = (await db.execute(select(User.id, User.full_name, User.role).where(*conditions)
                            .order_by(User.full_name, User.id).limit(50))).all()
    return {"items": [{"id": row.id, "name": row.full_name, "role": row.role.value} for row in rows],
            "total": total, "truncated": total > 50, "scope": "current_workspace"}


@router.post("/tickets/{ticket_id}/assignment")
async def assign(ticket_id: UUID, data: AssignmentRequest,
                 user=Depends(get_current_user), db=Depends(get_db)):
    manager(user)
    ticket = await find_ticket(db, user, ticket_id)
    reason = redact(data.reason.strip())
    if len(reason) < 2:
        raise HTTPException(422, "请填写至少两个字符的交接原因")
    target = str(data.agent_id) if data.agent_id else None
    request = {"agent_id": target, "reason": reason, "expected_updated_at": utc_time(data.expected_updated_at).isoformat()}
    existing = await db.scalar(select(HelpdeskTicketEvent).where(HelpdeskTicketEvent.id == str(data.request_id)))
    if existing:
        if existing.tenant_id != user.tenant_id or existing.ticket_id != ticket.id or existing.author_id != user.id:
            raise HTTPException(404, "Assignment request not found")
        if existing.event_type != "assignment_changed" or existing.payload.get("request") != request:
            raise HTTPException(409, "该请求编号已用于另一项操作")
        return {"id": ticket.id, "event_id": existing.id, "cached": True}
    check_revision(ticket, data.expected_updated_at)
    if ticket.status in FINISHED:
        raise HTTPException(409, "请先重新处理工单，再变更接手人")
    person = None
    if target:
        person = await db.scalar(select(User).where(User.id == target, User.tenant_id == user.tenant_id,
                              User.is_active.is_(True), User.role.in_(SUPPORT_ROLES)))
        if person is None:
            raise HTTPException(404, "未找到可分派的工作区成员")
    if target == ticket.assigned_agent_id:
        raise HTTPException(409, "接手人没有变化，请选择其他成员或释放工单")
    previous_id = ticket.assigned_agent_id
    previous_name = await db.scalar(select(User.full_name).where(User.id == previous_id, User.tenant_id == user.tenant_id)) if previous_id else None
    await atomic_change(db, ticket, {"assigned_agent_id": target})
    event = record_event(db, ticket, user, "assignment_changed", {
        "from_agent_id": previous_id, "from_agent_name": previous_name,
        "agent_id": target, "agent_name": person.full_name if person else None,
        "reason": reason, "request": request}, str(data.request_id))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "交接请求正在处理，请稍后使用原请求重试")
    return {"id": ticket.id, "event_id": event.id, "cached": False}


@router.get("/tickets/{ticket_id}/events")
async def ticket_events(ticket_id: UUID,
                        before: int | None = Query(default=None, ge=1, le=9223372036854775807),
                        page_size: int = Query(default=50, ge=1, le=100),
                        user=Depends(get_current_user), db=Depends(get_db)):
    operator(user)
    ticket = await find_ticket(db, user, ticket_id)
    conditions = [HelpdeskTicketEvent.tenant_id == user.tenant_id, HelpdeskTicketEvent.ticket_id == ticket.id]
    if before is not None:
        conditions.append(HelpdeskTicketEvent.sequence < before)
    rows = list((await db.scalars(select(HelpdeskTicketEvent).where(*conditions)
                                 .order_by(HelpdeskTicketEvent.sequence.desc()).limit(page_size + 1))).all())
    more = len(rows) > page_size
    rows = rows[:page_size]
    return {"events": [{"id": event.id, "type": event.event_type, "author": event.author_name,
                        "payload": event.payload, "created_at": utc_time(event.created_at)} for event in reversed(rows)],
            "has_more": more, "next_before": rows[-1].sequence if more else None}
