"""Real ticket ownership, application events and an explicitly local demo SLA."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm.attributes import set_committed_value

from app.helpdesk.models import HelpdeskNotification, HelpdeskTicketEvent
from app.models.ticket import Ticket, TicketStatus
from app.models.user import User, UserRole

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
    kwargs = {"id": identity or str(uuid4())}
    event = HelpdeskTicketEvent(tenant_id=ticket.tenant_id, ticket_id=ticket.id,
        author_id=user.id, author_name=user.full_name, event_type=event_type, payload=payload, **kwargs)
    db.add(event)
    return event


async def notify_event(db, ticket, actor, event):
    """Add minimal notifications to the caller's transaction; never commit here."""
    recipients = {}
    if event.event_type == "assignment_changed":
        target = event.payload.get("agent_id")
        previous = event.payload.get("from_agent_id")
        if target:
            recipients[target] = ("assigned_to_me", "新工单分派", f"{actor.full_name} 将工单分派给了你。")
        if previous and previous != target:
            recipients[previous] = ("assignment_removed", "工单交接更新",
                f"{actor.full_name} 已将你负责的工单转交。" if target else f"{actor.full_name} 已释放你负责的工单。")
    elif event.event_type == "status_changed" and ticket.assigned_agent_id:
        labels = {"OPEN": "待处理", "ESCALATED": "转人工", "IN_PROGRESS": "处理中",
                  "WAITING_FOR_CUSTOMER": "等待反馈", "RESOLVED": "已解决", "CLOSED": "已关闭"}
        state = labels[event.payload["to"]]
        recipients[ticket.assigned_agent_id] = ("status_changed", "工单状态更新",
            f"{actor.full_name} 将你负责的工单状态改为“{state}”。")
    if event.event_type in ("support_reply", "status_changed", "requester_confirmed", "requester_reopened"):
        from app.helpdesk.models import HelpdeskRun
        run = await db.scalar(select(HelpdeskRun).where(HelpdeskRun.tenant_id == ticket.tenant_id,
            HelpdeskRun.result["ticket_id"].as_string() == ticket.id).order_by(HelpdeskRun.created_at).limit(1))
        if run:
            recipients[run.user_id] = ("support_reply" if event.event_type == "support_reply" else "status_changed",
                "工单有新回复" if event.event_type == "support_reply" else "工单状态更新",
                "支持人员已回复你的工单。" if event.event_type == "support_reply" else "你的工单状态有更新。")
    if event.event_type == "requester_reply" and ticket.assigned_agent_id:
        recipients[ticket.assigned_agent_id] = ("requester_reply", "报障人补充了信息", "报障人已补充工单信息。")
    if event.event_type in ("requester_confirmed", "requester_reopened") and ticket.assigned_agent_id:
        recipients[ticket.assigned_agent_id] = ("status_changed", "工单状态更新",
            "报障人已确认工单解决。" if event.event_type == "requester_confirmed" else "报障人表示问题仍未解决。")
    if event.event_type in ("attachment_added", "attachment_deleted"):
        from app.helpdesk.models import HelpdeskRun
        run = await db.scalar(select(HelpdeskRun).where(HelpdeskRun.tenant_id == ticket.tenant_id,
            HelpdeskRun.result["ticket_id"].as_string() == ticket.id).order_by(HelpdeskRun.created_at).limit(1))
        kind = event.event_type
        message = (kind, "工单有新附件" if kind == "attachment_added" else "工单附件已移除",
            "工单新增了一份私有附件。" if kind == "attachment_added" else "工单的一份私有附件已移除。")
        if run and (event.payload["direction"] == "support" or kind == "attachment_deleted"):
            recipients[run.user_id] = message
        if ticket.assigned_agent_id and (event.payload["direction"] == "requester" or kind == "attachment_deleted"):
            recipients[ticket.assigned_agent_id] = message
    recipients.pop(actor.id, None)
    if not recipients:
        return
    active = (await db.scalars(select(User.id).where(User.id.in_(recipients),
        User.tenant_id == ticket.tenant_id, User.is_active.is_(True),
        User.role.in_((UserRole.TENANT_OWNER, UserRole.TENANT_ADMIN, UserRole.SUPPORT_AGENT))))).all()
    if active:
        # Resolve the parent FK before notification inserts, still in the same transaction.
        await db.flush([event])
    for recipient in active:
        kind, title, text = recipients[recipient]
        db.add(HelpdeskNotification(tenant_id=ticket.tenant_id, user_id=recipient,
            ticket_id=ticket.id, event_id=event.id, kind=kind, title=title, text=text))


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
    event = record_event(db, ticket, user, "status_changed", {"from": previous.value, "to": status.value})
    await notify_event(db, ticket, user, event)


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
        event = record_event(db, ticket, user, "status_changed", {"from": previous.value, "to": "IN_PROGRESS"})
        await notify_event(db, ticket, user, event)
