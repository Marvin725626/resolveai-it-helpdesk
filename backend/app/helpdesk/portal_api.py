"""Private, requester-scoped summary for the employee helpdesk portal."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api.deps import get_current_user
from app.core.database import get_db
from app.helpdesk.requester_api import iso_time, public_ticket, requester_ownership, assignee_name
from app.helpdesk.ticket_source import ticket_source_expression
from app.models.ticket import Ticket, TicketStatus

router = APIRouter(prefix="/helpdesk/portal", tags=["Requester portal"])


@router.get("/overview")
async def overview(user=Depends(get_current_user), db=Depends(get_db)):
    conditions = (Ticket.tenant_id == user.tenant_id, requester_ownership(user))
    count_rows = await db.execute(
        select(Ticket.status, func.count()).where(*conditions).group_by(Ticket.status)
    )
    counts = {status.value: count for status, count in count_rows.all()}
    for status in TicketStatus:
        counts.setdefault(status.value, 0)
    total = sum(counts.values())
    latest_rows = (await db.execute(
        select(Ticket, ticket_source_expression().label("source_code"))
        .where(*conditions)
        .order_by(Ticket.created_at.desc(), Ticket.id.desc()).limit(5)
    )).all()
    labels = {"manual": "手动报障", "ai": "AI 转人工", "legacy": "历史工单"}
    latest = []
    for ticket, source_code in latest_rows:
        latest.append(public_ticket(ticket, await assignee_name(db, ticket), labels[source_code], source_code))
    return {
        "statuses": counts,
        "total": total,
        "active": sum(counts[s.value] for s in TicketStatus if s not in (TicketStatus.RESOLVED, TicketStatus.CLOSED)),
        "resolved_awaiting_confirmation": counts[TicketStatus.RESOLVED.value],
        "closed": counts[TicketStatus.CLOSED.value],
        "latest": latest,
    }
