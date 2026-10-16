"""Persistent personal inbox, always scoped to the authenticated workspace and user."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update

from app.api.deps import get_current_user
from app.core.database import get_db
from app.helpdesk.api import operator, utc_time
from app.helpdesk.models import HelpdeskNotification
from app.models.user import UserRole

router = APIRouter(prefix="/helpdesk/notifications", tags=["Notifications"])


def scope(user):
    if user.role != UserRole.REQUESTER:
        operator(user)
    return (HelpdeskNotification.tenant_id == user.tenant_id, HelpdeskNotification.user_id == user.id)


@router.get("")
async def notifications(unread_only: bool = False,
        before: int | None = Query(default=None, ge=1, le=9223372036854775807),
        page_size: int = Query(default=20, ge=1, le=50),
        user=Depends(get_current_user), db=Depends(get_db)):
    conditions = list(scope(user))
    unread_count = await db.scalar(select(func.count()).select_from(HelpdeskNotification)
        .where(*conditions, HelpdeskNotification.read_at.is_(None)))
    if unread_only:
        conditions.append(HelpdeskNotification.read_at.is_(None))
    if before is not None:
        conditions.append(HelpdeskNotification.sequence < before)
    rows = list((await db.scalars(select(HelpdeskNotification).where(*conditions)
        .order_by(HelpdeskNotification.sequence.desc()).limit(page_size + 1))).all())
    more = len(rows) > page_size
    rows = rows[:page_size]
    return {"items": [{"id": row.id, "ticket_id": row.ticket_id, "kind": row.kind,
        "title": row.title, "text": row.text, "created_at": utc_time(row.created_at),
        "read_at": utc_time(row.read_at) if row.read_at else None} for row in rows],
        "unread_count": unread_count, "has_more": more,
        "next_before": rows[-1].sequence if more else None}


@router.post("/read-all")
async def read_all(user=Depends(get_current_user), db=Depends(get_db)):
    await db.execute(update(HelpdeskNotification).where(*scope(user), HelpdeskNotification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc)))
    await db.commit()
    return {"ok": True}


@router.post("/{notification_id}/read")
async def read_notification(notification_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    row = await db.scalar(select(HelpdeskNotification).where(*scope(user), HelpdeskNotification.id == str(notification_id)))
    if row is None:
        raise HTTPException(404, "Notification not found")
    if row.read_at is None:
        await db.execute(update(HelpdeskNotification).where(*scope(user), HelpdeskNotification.id == str(notification_id),
            HelpdeskNotification.read_at.is_(None)).values(read_at=datetime.now(timezone.utc)))
        await db.commit()
    return {"ok": True}
