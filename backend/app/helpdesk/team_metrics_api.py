"""Tenant-scoped operational metrics for the support team."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select

from app.api.deps import get_current_user
from app.core.database import get_db
from app.helpdesk.api import operator, utc_time
from app.helpdesk.operations_api import ticket_conditions
from app.helpdesk.resolution_models import ResolutionSatisfaction, TicketResolution
from app.helpdesk.ticket_ops import FINISHED
from app.models.ticket import Ticket, TicketPriority, TicketStatus
from app.models.user import User

router = APIRouter(prefix="/helpdesk", tags=["Team metrics"])


def utc_now():
    return datetime.now(timezone.utc)


def value(item):
    return item.value if hasattr(item, "value") else item


@router.get("/team-metrics")
async def team_metrics(days: int = Query(7, ge=1, le=90),
        user=Depends(get_current_user), db=Depends(get_db)):
    operator(user)
    if days not in (7, 30, 90):
        from fastapi import HTTPException
        raise HTTPException(422, "days must be 7, 30, or 90")
    now = utc_now()
    start = now - timedelta(days=days)
    tenant = Ticket.tenant_id == user.tenant_id
    active = Ticket.status.not_in([status.value for status in FINISHED])

    status_rows = (await db.execute(select(Ticket.status, func.count(Ticket.id))
        .where(tenant).group_by(Ticket.status))).all()
    statuses = {status.value: 0 for status in TicketStatus}
    statuses.update({value(status): count for status, count in status_rows})
    priority_rows = (await db.execute(select(Ticket.priority, func.count(Ticket.id))
        .where(tenant, active).group_by(Ticket.priority))).all()
    priorities = {priority.value: 0 for priority in TicketPriority}
    priorities.update({value(priority): count for priority, count in priority_rows})

    backlog = await db.scalar(select(func.count(Ticket.id)).where(tenant, active)) or 0
    unassigned = await db.scalar(select(func.count(Ticket.id)).where(
        tenant, active, Ticket.assigned_agent_id.is_(None))) or 0
    due_soon_conditions = ticket_conditions(user, "", None, None, "all", "due_soon", now)
    overdue_conditions = ticket_conditions(user, "", None, None, "all", "overdue", now)
    due_soon = await db.scalar(select(func.count(Ticket.id)).where(*due_soon_conditions)) or 0
    overdue = await db.scalar(select(func.count(Ticket.id)).where(*overdue_conditions)) or 0
    workload_rows = (await db.execute(select(Ticket.assigned_agent_id, User.full_name, func.count(Ticket.id))
        .select_from(Ticket).outerjoin(User, and_(User.id == Ticket.assigned_agent_id,
            User.tenant_id == Ticket.tenant_id)).where(tenant, active)
        .group_by(Ticket.assigned_agent_id, User.full_name).order_by(Ticket.assigned_agent_id))).all()
    workload = [{"assignee_id": identity, "assignee_name": name or ("未分派" if identity is None else "历史成员"),
        "count": count} for identity, name, count in workload_rows]

    resolution_scope = (TicketResolution.tenant_id == user.tenant_id,
        TicketResolution.resolved_at >= start, TicketResolution.resolved_at <= now)
    round_count, distinct_tickets = (await db.execute(select(func.count(TicketResolution.sequence),
        func.count(func.distinct(TicketResolution.ticket_id))).where(*resolution_scope))).one()
    category_rows = (await db.execute(select(TicketResolution.category, func.count(TicketResolution.sequence))
        .where(*resolution_scope).group_by(TicketResolution.category))).all()
    categories = {category: count for category, count in category_rows}

    rating_rows = (await db.execute(select(ResolutionSatisfaction.rating,
        func.count(ResolutionSatisfaction.id)).where(
            ResolutionSatisfaction.tenant_id == user.tenant_id,
            ResolutionSatisfaction.created_at >= start, ResolutionSatisfaction.created_at <= now)
        .group_by(ResolutionSatisfaction.rating))).all()
    distribution = {rating: 0 for rating in range(1, 6)}
    distribution.update({rating: count for rating, count in rating_rows})
    rating_count = sum(distribution.values())
    average = (sum(rating * count for rating, count in distribution.items()) / rating_count
        if rating_count else None)

    stamp = lambda dt: utc_time(dt).isoformat().replace("+00:00", "Z")
    return {
        "scope": "current_workspace", "timezone": "UTC", "days": days,
        "as_of": stamp(now), "generated_at": stamp(now),
        "snapshot": {"current_backlog": backlog, "statuses": statuses, "priorities": priorities,
            "unassigned": unassigned, "due_soon": due_soon, "overdue": overdue,
            "active_workload": workload},
        "resolution_window": {"from": stamp(start), "to": stamp(now),
            "basis": "TicketResolution.resolved_at", "rounds": round_count,
            "distinct_resolved_tickets": distinct_tickets, "categories": categories},
        "rating_window": {"from": stamp(start), "to": stamp(now),
            "basis": "ResolutionSatisfaction.created_at", "rating_count": rating_count,
            "average_rating": round(average, 2) if average is not None else None,
            "distribution": distribution},
        "definitions": {
            "snapshot": "当前工作区全时间实时快照；积压包含等待客户反馈，不含已解决或已关闭。",
            "resolution_window": "按UTC滚动时间窗口统计解决轮次；同一工单多次解决按多轮计，并单独报告去重工单数。",
            "rating_window": "按UTC滚动时间窗口统计评分提交时间；无样本时平均分为null。",
            "workload": "按当前未完成工单的当前接手人统计；历史成员单独保留，未分派单独计数。",
        },
    }
