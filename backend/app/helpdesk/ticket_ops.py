"""Real ticket ownership, application events and an explicitly local demo SLA."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm.attributes import set_committed_value

from app.helpdesk.models import HelpdeskTicketEvent
from app.models.ticket import Ticket, TicketStatus
from app.models.user import UserRole

SLA_HOURS = {"URGENT": 1, "HIGH": 4, "MEDIUM": 24, "LOW": 72}
FINISHED = {TicketStatus.RESOLVED, TicketStatus.CLOSED}


def utc(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def sla_snapshot(ticket, now=None):
    now = now or datetime.now(timezone.utc)
    priority = ticket.priority.value if hasattr(ticket.priority, "value") else ticket.priority
    hours = SLA_HOURS[priority]
    due = utc(ticket.created_at) + timedelta(hours=hours)
    finished = ticket.status in FINISHED
    end = utc(ticket.resolved_at) if finished and ticket.resolved_at else utc(now)
    remaining = (due - end).total_seconds() / 60
    if finished:
        state = "completed_unknown" if not ticket.resolved_at else ("met" if end <= due else "breached")
    else:
        state = "overdue" if remaining <= 0 else ("due_soon" if remaining <= min(60, hours * 15) else "on_track")
    return {"policy": "demo_resolution_target", "target_hours": hours, "due_at": due,
            "state": state, "remaining_minutes": round(remaining, 1), "clock": "calendar_hours_no_pause"}


def record_event(db, ticket, user, event_type, payload, identity=None):
    kwargs = {} if identity is None else {"id": identity}
    event = HelpdeskTicketEvent(tenant_id=ticket.tenant_id, ticket_id=ticket.id,
        author_id=user.id, author_name=user.full_name, event_type=event_type, payload=payload, **kwargs)
    db.add(event)
    return event


async def find_ticket(db, user, ticket_id):
    ticket = await db.scalar(select(Ticket).where(Ticket.id == str(ticket_id), Ticket.tenant_id == user.tenant_id))
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


def check_revision(ticket, expected):
    if expected is not None and utc(ticket.updated_at) != utc(expected):
        raise HTTPException(409, "工单已被更新，请刷新列表后重试")


async def atomic_change(db, ticket, values):
    values["updated_at"] = max(datetime.now(timezone.utc), utc(ticket.updated_at) + timedelta(microseconds=1))
    result = await db.execute(update(Ticket).where(Ticket.id == ticket.id, Ticket.tenant_id == ticket.tenant_id,
        Ticket.updated_at == ticket.updated_at).values(**values).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "工单已被更新，请刷新列表后重试")
    for key, value in values.items():
        # The SQL UPDATE already persisted these values. Mark the ORM state clean.
        set_committed_value(ticket, key, value)


async def change_status(db, user, ticket, status, expected=None):
    check_revision(ticket, expected)
    if user.role == UserRole.SUPPORT_AGENT and ticket.assigned_agent_id not in (None, user.id):
        raise HTTPException(403, "只有接手人或工作区管理员可更改工单状态")
    transitions = {
        TicketStatus.OPEN: {TicketStatus.IN_PROGRESS, TicketStatus.ESCALATED},
        TicketStatus.ESCALATED: {TicketStatus.IN_PROGRESS},
        TicketStatus.IN_PROGRESS: {TicketStatus.RESOLVED, TicketStatus.WAITING_FOR_CUSTOMER},
        TicketStatus.WAITING_FOR_CUSTOMER: {TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED},
        TicketStatus.RESOLVED: {TicketStatus.CLOSED, TicketStatus.IN_PROGRESS},
        TicketStatus.CLOSED: {TicketStatus.IN_PROGRESS},
    }
    if status == ticket.status:
        return
    if status not in transitions[ticket.status]:
        raise HTTPException(409, "Invalid ticket status transition")
    previous = ticket.status
    values = {"status": status, "resolved_at": (
        ticket.resolved_at or datetime.now(timezone.utc)) if status in FINISHED else None}
    auto_assign = status == TicketStatus.IN_PROGRESS and ticket.assigned_agent_id is None
    if auto_assign:
        values["assigned_agent_id"] = user.id
    await atomic_change(db, ticket, values)
    if auto_assign:
        record_event(db, ticket, user, "assigned", {"agent_id": user.id, "agent_name": user.full_name})
    record_event(db, ticket, user, "status_changed", {"from": previous.value, "to": status.value})


async def claim_ticket(db, user, ticket, expected=None):
    check_revision(ticket, expected)
    if ticket.assigned_agent_id == user.id:
        return
    if ticket.assigned_agent_id is not None:
        raise HTTPException(409, "该工单已有人接手，请联系工作区管理员")
    if ticket.status not in (TicketStatus.OPEN, TicketStatus.ESCALATED, TicketStatus.IN_PROGRESS):
        raise HTTPException(409, "请先重新处理工单，再接手")
    previous = ticket.status
    await atomic_change(db, ticket, {"assigned_agent_id": user.id, "status": TicketStatus.IN_PROGRESS})
    record_event(db, ticket, user, "assigned", {"agent_id": user.id, "agent_name": user.full_name})
    if previous != TicketStatus.IN_PROGRESS:
        record_event(db, ticket, user, "status_changed", {"from": previous.value, "to": "IN_PROGRESS"})
