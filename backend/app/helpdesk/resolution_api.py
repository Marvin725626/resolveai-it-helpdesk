"""Public, immutable resolution rounds; optional feedback belongs to the confirmed round."""
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.sanitizer import sanitize_text_input
from app.helpdesk.api import operator
from app.helpdesk.models import HelpdeskTicketEvent
from app.helpdesk.requester_api import iso_time, requester_ticket
from app.helpdesk.resolution_models import ResolutionSatisfaction, TicketResolution
from app.helpdesk.ticket_ops import atomic_change, check_revision, find_ticket, notify_event, record_event, utc
from app.helpdesk.workflow import redact
from app.models.ticket import TicketStatus
from app.models.user import UserRole

router = APIRouter(prefix="/helpdesk", tags=["Resolution and satisfaction"])
MANAGERS = (UserRole.TENANT_OWNER, UserRole.TENANT_ADMIN)
Category = Literal["configuration", "account_access", "software", "service", "guidance", "other"]


class ResolveInput(BaseModel):
    request_id: UUID
    expected_updated_at: datetime
    category: Category
    summary: str = Field(min_length=2, max_length=2000)
    steps: str = Field(default="", max_length=5000)


class SatisfactionInput(BaseModel):
    request_id: UUID
    resolution_id: UUID
    rating: int = Field(ge=1, le=5, strict=True)
    comment: str = Field(default="", max_length=1000)


def public_text(value, limit):
    return redact(sanitize_text_input(value.strip(), limit)).strip()


def identity(user):
    return SimpleNamespace(id=user.id, tenant_id=user.tenant_id, full_name=user.full_name, role=user.role)


def public_resolution(row):
    return {"id": row.id, "ticket_id": row.ticket_id, "category": row.category, "summary": row.summary,
        "steps": row.steps, "author_name": row.author_name, "resolved_at": iso_time(row.resolved_at),
        "created_at": iso_time(row.created_at)}


def public_satisfaction(row):
    return {"id": row.id, "resolution_id": row.resolution_id, "rating": row.rating,
        "comment": row.comment, "created_at": iso_time(row.created_at)} if row else None


def is_current(ticket, row):
    return bool(row and ticket.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED)
        and ticket.resolved_at and utc(ticket.resolved_at) == utc(row.resolved_at))


def can_resolve(ticket, user):
    return ticket.status in (TicketStatus.IN_PROGRESS, TicketStatus.WAITING_FOR_CUSTOMER) and (
        user.role in MANAGERS or (user.role == UserRole.SUPPORT_AGENT and ticket.assigned_agent_id == user.id))


async def resolution_view(db, user, ticket):
    row = await db.scalar(select(TicketResolution).where(TicketResolution.tenant_id == user.tenant_id,
        TicketResolution.ticket_id == ticket.id).order_by(TicketResolution.sequence.desc()).limit(1))
    feedback = await db.scalar(select(ResolutionSatisfaction).where(ResolutionSatisfaction.tenant_id == user.tenant_id,
        ResolutionSatisfaction.ticket_id == ticket.id, ResolutionSatisfaction.resolution_id == row.id)) if row else None
    return {"resolution": public_resolution(row) if row else None, "current": is_current(ticket, row),
        "can_resolve": can_resolve(ticket, user), "updated_at": iso_time(ticket.updated_at),
        "satisfaction": public_satisfaction(feedback)}


@router.get("/tickets/{ticket_id}/resolution")
async def support_resolution(ticket_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    operator(user)
    return await resolution_view(db, user, await find_ticket(db, user, ticket_id))


@router.get("/my-tickets/{ticket_id}/resolution")
async def my_resolution(ticket_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    return await resolution_view(db, user, await requester_ticket(db, user, ticket_id))


async def replay_resolution(db, user, ticket_id, data, summary, steps):
    row = await db.scalar(select(TicketResolution).where(TicketResolution.request_id == str(data.request_id)))
    if row is None:
        return None
    if row.tenant_id != user.tenant_id or row.ticket_id != ticket_id or row.author_id != user.id:
        raise HTTPException(404, "Resolution request not found")
    if row.category != data.category or row.summary != summary or row.steps != steps or utc(row.expected_updated_at) != utc(data.expected_updated_at):
        raise HTTPException(409, "该请求编号已用于另一项解决操作")
    return row


@router.post("/tickets/{ticket_id}/resolve", status_code=201)
async def resolve_ticket(ticket_id: UUID, data: ResolveInput, user=Depends(get_current_user), db=Depends(get_db)):
    operator(user); user = identity(user)
    ticket_identity = str(ticket_id)
    ticket = await find_ticket(db, user, ticket_identity)
    summary, steps = public_text(data.summary, 2000), public_text(data.steps, 5000)
    if len(summary) < 2:
        raise HTTPException(422, "请填写至少两个字符的公开解决摘要")
    cached = await replay_resolution(db, user, ticket_identity, data, summary, steps)
    if cached:
        return {"resolution": public_resolution(cached), "cached": True, "updated_at": iso_time(ticket.updated_at)}
    check_revision(ticket, data.expected_updated_at)
    if not can_resolve(ticket, user):
        if ticket.status not in (TicketStatus.IN_PROGRESS, TicketStatus.WAITING_FOR_CUSTOMER):
            raise HTTPException(409, "请先接手或继续处理，再填写解决记录")
        raise HTTPException(403, "只有当前接手人或工作区管理员可提交解决记录")
    try:
        previous = ticket.status
        resolved_at = datetime.now(timezone.utc)
        await atomic_change(db, ticket, {"status": TicketStatus.RESOLVED, "resolved_at": resolved_at})
        row = TicketResolution(id=str(uuid4()), request_id=str(data.request_id), tenant_id=user.tenant_id,
            ticket_id=ticket_identity, category=data.category, summary=summary, steps=steps,
            author_id=user.id, author_name=user.full_name, expected_updated_at=utc(data.expected_updated_at), resolved_at=resolved_at)
        db.add(row)
        event = record_event(db, ticket, user, "status_changed", {"from": previous.value, "to": "RESOLVED", "resolution_id": row.id}, str(data.request_id))
        await db.flush()
        await notify_event(db, ticket, user, event)
        await db.commit()
        return {"resolution": public_resolution(row), "cached": False, "updated_at": iso_time(ticket.updated_at)}
    except (IntegrityError, HTTPException) as error:
        await db.rollback()
        ticket = await find_ticket(db, user, ticket_identity)
        cached = await replay_resolution(db, user, ticket_identity, data, summary, steps)
        if cached:
            return {"resolution": public_resolution(cached), "cached": True, "updated_at": iso_time(ticket.updated_at)}
        if isinstance(error, HTTPException):
            raise error
        raise HTTPException(409, "解决记录冲突，请刷新后重试")
    except Exception:
        await db.rollback()
        raise


async def replay_satisfaction(db, user, ticket_id, data, comment):
    row = await db.scalar(select(ResolutionSatisfaction).where(ResolutionSatisfaction.request_id == str(data.request_id)))
    if row is None:
        return None
    if row.tenant_id != user.tenant_id or row.ticket_id != ticket_id or row.user_id != user.id:
        raise HTTPException(404, "Feedback request not found")
    if row.resolution_id != str(data.resolution_id) or row.rating != data.rating or row.comment != comment:
        raise HTTPException(409, "该请求编号已用于另一份评分")
    return row


@router.post("/my-tickets/{ticket_id}/satisfaction", status_code=201)
async def satisfaction(ticket_id: UUID, data: SatisfactionInput, user=Depends(get_current_user), db=Depends(get_db)):
    user = identity(user); ticket_identity = str(ticket_id)
    ticket = await requester_ticket(db, user, ticket_identity)
    comment = public_text(data.comment, 1000)
    cached = await replay_satisfaction(db, user, ticket_identity, data, comment)
    if cached:
        return {"satisfaction": public_satisfaction(cached), "cached": True, "updated_at": iso_time(ticket.updated_at)}
    row = await db.scalar(select(TicketResolution).where(TicketResolution.id == str(data.resolution_id),
        TicketResolution.tenant_id == user.tenant_id, TicketResolution.ticket_id == ticket_identity))
    if row is None:
        raise HTTPException(404, "Resolution not found")
    if ticket.status != TicketStatus.CLOSED or not is_current(ticket, row):
        raise HTTPException(409, "请先确认当前轮次解决并关闭，再评价该轮次")
    existing = await db.scalar(select(ResolutionSatisfaction.id).where(ResolutionSatisfaction.resolution_id == row.id,
        ResolutionSatisfaction.tenant_id == user.tenant_id, ResolutionSatisfaction.ticket_id == ticket_identity))
    if existing:
        raise HTTPException(409, "当前解决轮次已经评价，评分不能重复修改")
    try:
        await atomic_change(db, ticket, {})
        feedback = ResolutionSatisfaction(request_id=str(data.request_id), resolution_id=row.id,
            tenant_id=user.tenant_id, ticket_id=ticket_identity, user_id=user.id, rating=data.rating, comment=comment)
        db.add(feedback)
        record_event(db, ticket, user, "satisfaction_submitted", {"resolution_id": row.id, "rating": data.rating}, str(data.request_id))
        await db.flush(); await db.commit()
        return {"satisfaction": public_satisfaction(feedback), "cached": False, "updated_at": iso_time(ticket.updated_at)}
    except (IntegrityError, HTTPException) as error:
        await db.rollback()
        ticket = await requester_ticket(db, user, ticket_identity)
        cached = await replay_satisfaction(db, user, ticket_identity, data, comment)
        if cached:
            return {"satisfaction": public_satisfaction(cached), "cached": True, "updated_at": iso_time(ticket.updated_at)}
        if isinstance(error, HTTPException):
            raise error
        raise HTTPException(409, "评分提交冲突，请刷新后重试")
    except Exception:
        await db.rollback(); raise
