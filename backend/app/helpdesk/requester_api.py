"""Authenticated requester view of AI escalations and their public reply thread."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import exists, func, select, or_
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.sanitizer import sanitize_text_input
from app.helpdesk.models import HelpdeskRun, HelpdeskTicketEvent, HelpdeskTicketReply, ManualTicketSubmission
from app.helpdesk.ticket_ops import atomic_change, check_revision, find_ticket, notify_event, record_event, utc
from app.helpdesk.workflow import redact
from app.models.ticket import Ticket, TicketStatus, TicketCategory, TicketPriority
from app.models.customer import Customer
from app.models.user import UserRole

router = APIRouter(prefix="/helpdesk", tags=["Requester tickets"])


def iso_time(value):
    return utc(value).isoformat() if value else None


class ReplyInput(BaseModel):
    request_id: UUID
    expected_updated_at: datetime
    body: str = Field(min_length=2, max_length=3000)


class ActionInput(BaseModel):
    request_id: UUID
    expected_updated_at: datetime
    explanation: str | None = Field(default=None, min_length=2, max_length=1000)


class ManualTicketInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    subject: str = Field(strict=True, max_length=1000)
    description: str = Field(strict=True, max_length=10000)
    category: str = Field(default="other", pattern=r"^(network|account|software|hardware|other)$", strict=True)


def requester_ownership(user):
    return or_(
        exists(select(HelpdeskRun.id).where(HelpdeskRun.tenant_id == Ticket.tenant_id,
            HelpdeskRun.user_id == user.id, HelpdeskRun.result["ticket_id"].as_string() == Ticket.id)),
        exists(select(ManualTicketSubmission.request_id).where(ManualTicketSubmission.tenant_id == Ticket.tenant_id,
            ManualTicketSubmission.user_id == user.id, ManualTicketSubmission.ticket_id == Ticket.id)))


async def requester_ticket(db, user, ticket_id):
    ticket = await db.scalar(select(Ticket).where(Ticket.id == str(ticket_id), Ticket.tenant_id == user.tenant_id,
        requester_ownership(user)))
    if ticket is None:
        raise HTTPException(404, "Ticket not found")
    return ticket


def public_ticket(ticket, assignee=None, source="AI 转人工"):
    return {"id": ticket.id, "subject": ticket.subject, "status": ticket.status.value,
        "priority": ticket.priority.value, "assignee": assignee,
        "created_at": iso_time(ticket.created_at), "updated_at": iso_time(ticket.updated_at),
        "resolved_at": iso_time(ticket.resolved_at), "source": source}


@router.post("/my-tickets", status_code=201)
async def create_manual_ticket(data: ManualTicketInput, user=Depends(get_current_user), db=Depends(get_db)):
    tenant_id, user_id = user.tenant_id, user.id
    subject = redact(sanitize_text_input(data.subject.strip(), 500)).strip()
    description = redact(sanitize_text_input(data.description.strip(), 10000)).strip()
    if not 4 <= len(subject) <= 200:
        raise HTTPException(422, "报障标题清理后需为4至200个字符")
    if not 10 <= len(description) <= 4000:
        raise HTTPException(422, "问题描述清理后需为10至4000个字符")
    payload = {"subject": subject, "description": description, "category": data.category}
    identity = str(data.request_id)
    prior = await db.get(ManualTicketSubmission, identity)
    if prior:
        if prior.tenant_id != tenant_id or prior.user_id != user_id:
            raise HTTPException(404, "Request not found")
        if prior.payload != payload:
            raise HTTPException(409, "Request ID already belongs to another ticket")
        return {"ticket_id": prior.ticket_id, "cached": True}
    customer = await db.scalar(select(Customer).where(Customer.tenant_id == tenant_id,
        Customer.email == user.email).order_by(Customer.created_at).limit(1))
    if customer is None:
        customer = Customer(tenant_id=tenant_id, name=user.full_name, email=user.email)
        db.add(customer)
        await db.flush()
    category = {"network": TicketCategory.TECHNICAL, "account": TicketCategory.TECHNICAL,
        "software": TicketCategory.TECHNICAL, "hardware": TicketCategory.TECHNICAL,
        "other": TicketCategory.GENERAL}[data.category]
    ticket = Ticket(tenant_id=tenant_id, customer_id=customer.id, subject=subject,
        description=description, category=category, priority=TicketPriority.MEDIUM, status=TicketStatus.OPEN)
    db.add(ticket)
    await db.flush()
    submission = ManualTicketSubmission(request_id=identity, tenant_id=tenant_id, user_id=user_id,
        ticket_id=ticket.id, payload=payload)
    db.add(submission)
    # Keep only scalar identity values across rollback; ORM user attributes may expire.
    event = record_event(db, ticket, user, "created", {"source": "manual", "category": data.category}, identity)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        prior = await db.get(ManualTicketSubmission, identity)
        if prior and prior.tenant_id == tenant_id and prior.user_id == user_id:
            if prior.payload == payload:
                return {"ticket_id": prior.ticket_id, "cached": True}
            raise HTTPException(409, "Request ID already belongs to another ticket")
        raise HTTPException(409, "Request conflict; retry with the same request ID")
    return {"ticket_id": ticket.id, "cached": False}


def public_reply(row):
    return {"id": row.id, "author_name": row.author_name, "direction": row.direction,
        "body": row.body, "created_at": iso_time(row.created_at)}


async def assignee_name(db, ticket):
    if not ticket.assigned_agent_id:
        return None
    from app.models.user import User
    return await db.scalar(select(User.full_name).where(User.id == ticket.assigned_agent_id,
        User.tenant_id == ticket.tenant_id, User.is_active.is_(True)))


@router.get("/my-tickets")
async def my_tickets(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50),
        status: TicketStatus | None = None, user=Depends(get_current_user), db=Depends(get_db)):
    manual_exists = exists(select(ManualTicketSubmission.request_id).where(
        ManualTicketSubmission.tenant_id == Ticket.tenant_id, ManualTicketSubmission.ticket_id == Ticket.id))
    query = select(Ticket, manual_exists.label("is_manual")).where(Ticket.tenant_id == user.tenant_id, requester_ownership(user))
    if status:
        query = query.where(Ticket.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = list((await db.execute(query.order_by(Ticket.created_at.desc(), Ticket.id).offset((page-1)*page_size).limit(page_size))).all())
    return {"items": [{**public_ticket(ticket, await assignee_name(db, ticket), "手动报障" if is_manual else "AI 转人工")} for ticket, is_manual in rows],
        "page": page, "page_size": page_size, "total": total}


@router.get("/my-tickets/{ticket_id}")
async def my_ticket_detail(ticket_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    ticket = await requester_ticket(db, user, ticket_id)
    submission = await db.scalar(select(ManualTicketSubmission).where(
        ManualTicketSubmission.ticket_id == ticket.id, ManualTicketSubmission.user_id == user.id,
        ManualTicketSubmission.tenant_id == user.tenant_id))
    events = list((await db.scalars(select(HelpdeskTicketEvent).where(
        HelpdeskTicketEvent.tenant_id == user.tenant_id, HelpdeskTicketEvent.ticket_id == ticket.id,
        HelpdeskTicketEvent.event_type.in_(("created", "status_changed", "assigned", "assignment_changed")))
        .order_by(HelpdeskTicketEvent.sequence.asc()).limit(100))).all())
    ticket_view = public_ticket(ticket, await assignee_name(db, ticket), "手动报障" if submission else "AI 转人工")
    if submission:
        ticket_view["request"] = {"description": submission.payload["description"], "category": submission.payload["category"]}
    return {"ticket": ticket_view,
        "timeline": [{"type": row.event_type, "created_at": iso_time(row.created_at),
            "status": row.payload.get("to") if row.event_type == "status_changed" else None,
            "author": row.author_name if row.event_type == "status_changed" else None} for row in events]}


async def reply_page(ticket, user, db, before, page_size):
    conditions = [HelpdeskTicketReply.tenant_id == user.tenant_id, HelpdeskTicketReply.ticket_id == ticket.id]
    if before is not None:
        conditions.append(HelpdeskTicketReply.sequence < before)
    rows = list((await db.scalars(select(HelpdeskTicketReply).where(*conditions)
        .order_by(HelpdeskTicketReply.sequence.desc()).limit(page_size + 1))).all())
    more = len(rows) > page_size
    rows = rows[:page_size]
    return {"items": [public_reply(row) for row in reversed(rows)], "updated_at": iso_time(ticket.updated_at),
        "has_more": more, "next_before": rows[-1].sequence if more else None}


@router.get("/tickets/{ticket_id}/replies")
async def list_replies(ticket_id: UUID, before: int | None = Query(None, ge=1),
        page_size: int = Query(20, ge=1, le=50), user=Depends(get_current_user), db=Depends(get_db)):
    if user.role in (UserRole.TENANT_OWNER, UserRole.TENANT_ADMIN, UserRole.SUPPORT_AGENT):
        ticket = await find_ticket(db, user, ticket_id)
    else:
        ticket = await requester_ticket(db, user, ticket_id)
    return await reply_page(ticket, user, db, before, page_size)


@router.get("/my-tickets/{ticket_id}/replies")
async def list_my_replies(ticket_id: UUID, before: int | None = Query(None, ge=1),
        page_size: int = Query(20, ge=1, le=50), user=Depends(get_current_user), db=Depends(get_db)):
    ticket = await requester_ticket(db, user, ticket_id)
    return await reply_page(ticket, user, db, before, page_size)


async def replay_event(db, user, ticket, data, event_type, text, direction):
    existing = await db.scalar(select(HelpdeskTicketEvent).where(HelpdeskTicketEvent.id == str(data.request_id)))
    if not existing:
        return None
    expected = data.expected_updated_at
    payload = {"body": text, "direction": direction, "expected_updated_at": expected.isoformat()}
    if existing.tenant_id != user.tenant_id or existing.ticket_id != ticket.id or existing.author_id != user.id:
        raise HTTPException(404, "Request not found")
    if existing.event_type != event_type or existing.payload != payload:
        raise HTTPException(409, "Request ID already belongs to another operation")
    reply = await db.scalar(select(HelpdeskTicketReply).where(
        HelpdeskTicketReply.request_id == str(data.request_id),
        HelpdeskTicketReply.tenant_id == user.tenant_id,
        HelpdeskTicketReply.ticket_id == ticket.id, HelpdeskTicketReply.author_id == user.id))
    if reply is None:
        raise HTTPException(409, "Reply resource is missing for this request")
    return {"id": reply.id, "cached": True, "updated_at": iso_time(ticket.updated_at)}


async def add_reply(ticket_id, data, user, db, direction):
    if direction == "support":
        if user.role not in (UserRole.TENANT_OWNER, UserRole.TENANT_ADMIN, UserRole.SUPPORT_AGENT):
            raise HTTPException(403, "Workspace support role is required")
        ticket = await find_ticket(db, user, ticket_id)
    else:
        ticket = await requester_ticket(db, user, ticket_id)
    text = redact(sanitize_text_input(data.body.strip(), 3000)).strip()
    if len(text) < 2:
        raise HTTPException(422, "回复至少需要两个字符")
    event_type = "support_reply" if direction == "support" else "requester_reply"
    replay = await replay_event(db, user, ticket, data, event_type, text, direction)
    if replay:
        return replay
    if ticket.status == TicketStatus.CLOSED:
        raise HTTPException(409, "已关闭工单不能再发送公开回复")
    if direction == "support" and user.role == UserRole.SUPPORT_AGENT and ticket.assigned_agent_id != user.id:
        raise HTTPException(403, "只有当前接手人或工作区管理员可回复")
    check_revision(ticket, data.expected_updated_at)
    resumed = direction == "requester" and ticket.status == TicketStatus.WAITING_FOR_CUSTOMER
    if resumed:
        previous = ticket.status
        await atomic_change(db, ticket, {"status": TicketStatus.IN_PROGRESS})
        record_event(db, ticket, user, "status_changed", {"from": previous.value, "to": TicketStatus.IN_PROGRESS.value})
    else:
        await atomic_change(db, ticket, {})
    reply = HelpdeskTicketReply(request_id=str(data.request_id), tenant_id=ticket.tenant_id,
        ticket_id=ticket.id, author_id=user.id, author_name=user.full_name, direction=direction, body=text)
    db.add(reply)
    event = record_event(db, ticket, user, event_type,
        {"body": text, "direction": direction, "expected_updated_at": data.expected_updated_at.isoformat()}, str(data.request_id))
    ticket_identity = ticket.id
    try:
        await db.flush()
        await notify_event(db, ticket, user, event)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        ticket = await find_ticket(db, user, ticket_identity) if direction == "support" else await requester_ticket(db, user, ticket_identity)
        existing = await db.scalar(select(HelpdeskTicketEvent).where(HelpdeskTicketEvent.id == str(data.request_id)))
        if existing:
            replay = await replay_event(db, user, ticket, data, event_type, text, direction)
            if replay:
                return replay
        raise HTTPException(409, "回复冲突，请刷新后重试")
    return {"id": reply.id, "cached": False, "updated_at": iso_time(ticket.updated_at)}


@router.post("/tickets/{ticket_id}/replies", status_code=201)
async def support_reply(ticket_id: UUID, data: ReplyInput, user=Depends(get_current_user), db=Depends(get_db)):
    return await add_reply(ticket_id, data, user, db, "support")


@router.post("/my-tickets/{ticket_id}/replies", status_code=201)
async def requester_reply(ticket_id: UUID, data: ReplyInput, user=Depends(get_current_user), db=Depends(get_db)):
    return await add_reply(ticket_id, data, user, db, "requester")


async def requester_action(ticket_id, data, user, db, kind):
    ticket = await requester_ticket(db, user, ticket_id)
    ticket_identity = ticket.id
    event_type = "requester_confirmed" if kind == "confirm" else "requester_reopened"
    explanation = redact((data.explanation or "").strip())
    payload = {"expected_updated_at": data.expected_updated_at.isoformat(), "explanation": explanation}
    existing = await db.scalar(select(HelpdeskTicketEvent).where(HelpdeskTicketEvent.id == str(data.request_id)))
    if existing:
        if existing.tenant_id != user.tenant_id or existing.ticket_id != ticket.id or existing.author_id != user.id:
            raise HTTPException(404, "Request not found")
        if existing.event_type != event_type or existing.payload != payload:
            raise HTTPException(409, "Request ID already belongs to another operation")
        return {"id": ticket.id, "status": ticket.status.value, "updated_at": iso_time(ticket.updated_at), "cached": True}
    check_revision(ticket, data.expected_updated_at)
    if kind == "confirm":
        if ticket.status != TicketStatus.RESOLVED:
            raise HTTPException(409, "只有已解决的工单可以确认关闭")
        await atomic_change(db, ticket, {"status": TicketStatus.CLOSED})
        status_event = record_event(db, ticket, user, "status_changed", {"from": TicketStatus.RESOLVED.value, "to": TicketStatus.CLOSED.value})
    else:
        if ticket.status != TicketStatus.RESOLVED or len(explanation) < 2:
            raise HTTPException(409, "只有已解决的工单可以重开，并请说明仍未解决的原因")
        await atomic_change(db, ticket, {"status": TicketStatus.IN_PROGRESS, "resolved_at": None})
        db.add(HelpdeskTicketReply(request_id=str(data.request_id), tenant_id=ticket.tenant_id,
            ticket_id=ticket.id, author_id=user.id, author_name=user.full_name, direction="requester", body=explanation))
        record_event(db, ticket, user, "status_changed", {"from": TicketStatus.RESOLVED.value, "to": TicketStatus.IN_PROGRESS.value})
    event = record_event(db, ticket, user, event_type, payload, str(data.request_id))
    if kind == "confirm":
        event_to_notify = status_event
    else:
        event_to_notify = event
    try:
        await db.flush()
        await notify_event(db, ticket, user, event_to_notify)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        ticket = await requester_ticket(db, user, ticket_identity)
        existing = await db.scalar(select(HelpdeskTicketEvent).where(HelpdeskTicketEvent.id == str(data.request_id)))
        if existing:
            if existing.tenant_id == user.tenant_id and existing.ticket_id == ticket.id and existing.author_id == user.id and existing.event_type == event_type and existing.payload == payload:
                return {"id": ticket.id, "status": ticket.status.value, "updated_at": iso_time(ticket.updated_at), "cached": True}
            raise HTTPException(409, "Request ID already belongs to another operation")
        raise HTTPException(409, "工单操作冲突，请刷新后重试")
    return {"id": ticket.id, "status": ticket.status.value, "updated_at": iso_time(ticket.updated_at), "cached": False}


@router.post("/my-tickets/{ticket_id}/confirm-resolved")
async def confirm_resolved(ticket_id: UUID, data: ActionInput, user=Depends(get_current_user), db=Depends(get_db)):
    return await requester_action(ticket_id, data, user, db, "confirm")


@router.post("/my-tickets/{ticket_id}/reopen")
async def reopen(ticket_id: UUID, data: ActionInput, user=Depends(get_current_user), db=Depends(get_db)):
    if not data.explanation:
        raise HTTPException(422, "请说明仍未解决的原因")
    return await requester_action(ticket_id, data, user, db, "reopen")
