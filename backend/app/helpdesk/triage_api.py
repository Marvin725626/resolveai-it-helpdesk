"""Ticket priority changes and tenant/user-scoped persistent queue filters."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace
import unicodedata
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_current_user
from app.core.database import get_db
from app.helpdesk.api import operator
from app.helpdesk.models import HelpdeskTicketEvent
from app.helpdesk.operations_api import SlaFilter
from app.helpdesk.requester_api import iso_time
from app.helpdesk.ticket_ops import FINISHED, SLA_HOURS, atomic_change, check_revision, find_ticket, notify_event, record_event, sla_snapshot, utc
from app.helpdesk.view_models import SavedQueueView
from app.helpdesk.workflow import redact
from app.models.ticket import TicketPriority, TicketStatus
from app.models.user import User, UserRole

router = APIRouter(prefix="/helpdesk", tags=["Ticket triage and personal queue views"])
MANAGERS = (UserRole.TENANT_OWNER, UserRole.TENANT_ADMIN)


def identity(user):
    return SimpleNamespace(id=user.id, tenant_id=user.tenant_id, role=user.role, full_name=user.full_name)


class PriorityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_updated_at: datetime
    priority: TicketPriority
    reason: str = Field(min_length=2, max_length=1000)


def can_change_priority(ticket, user):
    return ticket.status not in FINISHED and (user.role in MANAGERS or ticket.assigned_agent_id == user.id)


def priority_view(ticket, user):
    return {"id": ticket.id, "priority": ticket.priority.value, "can_change": can_change_priority(ticket, user),
        "created_at": iso_time(ticket.created_at), "updated_at": iso_time(ticket.updated_at),
        "sla": sla_snapshot(ticket), "target_hours_by_priority": SLA_HOURS}


async def priority_replay(db, user, ticket_id, request_id, payload):
    event = await db.scalar(select(HelpdeskTicketEvent).where(HelpdeskTicketEvent.id == request_id))
    if event is None:
        return None
    if event.tenant_id != user.tenant_id or event.ticket_id != ticket_id or event.author_id != user.id:
        raise HTTPException(404, "Priority request not found")
    if event.event_type != "priority_changed" or event.payload.get("request") != payload:
        raise HTTPException(409, "该请求编号已用于另一项操作")
    return event


@router.get("/tickets/{ticket_id}/priority")
async def get_priority(ticket_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    operator(user)
    return priority_view(await find_ticket(db, user, ticket_id), user)


@router.post("/tickets/{ticket_id}/priority")
async def change_priority(ticket_id: UUID, data: PriorityInput, user=Depends(get_current_user), db=Depends(get_db)):
    operator(user); user = identity(user); ticket_identity = str(ticket_id)
    ticket = await find_ticket(db, user, ticket_identity)
    reason = redact(data.reason.strip()).strip()
    if len(reason) < 2:
        raise HTTPException(422, "请填写至少两个字符的优先级调整原因")
    payload = {"priority": data.priority.value, "reason": reason,
        "expected_updated_at": utc(data.expected_updated_at).isoformat()}
    existing = await priority_replay(db, user, ticket_identity, str(data.request_id), payload)
    if existing:
        return {**priority_view(ticket, user), "event_id": existing.id, "cached": True}
    if ticket.status in FINISHED:
        raise HTTPException(409, "已完成工单不能调整优先级")
    if not can_change_priority(ticket, user):
        raise HTTPException(403, "只有当前接手人或工作区管理员可调整优先级")
    check_revision(ticket, data.expected_updated_at)
    if data.priority == ticket.priority:
        raise HTTPException(409, "优先级没有变化")
    try:
        previous = ticket.priority
        old_due = sla_snapshot(ticket)["due_at"]
        new_due = utc(ticket.created_at) + timedelta(hours=SLA_HOURS[data.priority.value])
        await atomic_change(db, ticket, {"priority": data.priority})
        event = record_event(db, ticket, user, "priority_changed", {"from": previous.value, "to": data.priority.value,
            "from_due_at": iso_time(old_due), "to_due_at": iso_time(new_due), "reason": reason, "request": payload}, str(data.request_id))
        await db.flush([event]); await notify_event(db, ticket, user, event); await db.commit()
        return {**priority_view(ticket, user), "event_id": event.id, "cached": False}
    except (IntegrityError, HTTPException) as error:
        await db.rollback()
        ticket = await find_ticket(db, user, ticket_identity)
        existing = await priority_replay(db, user, ticket_identity, str(data.request_id), payload)
        if existing:
            return {**priority_view(ticket, user), "event_id": existing.id, "cached": True}
        if isinstance(error, HTTPException):
            raise error
        raise HTTPException(409, "优先级请求冲突，请刷新后重试")
    except Exception:
        await db.rollback(); raise


class QueueFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(default="", max_length=200, strict=True)
    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    assignment: Literal["all", "mine", "unassigned"] = "all"
    sla: SlaFilter | None = None
    source: Literal["manual", "ai", "legacy"] | None = None
    page_size: int = Field(default=20, ge=1, le=100, strict=True)

    @field_validator("q")
    @classmethod
    def trim_query(cls, value):
        return value.strip()


class ViewFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=50, strict=True)
    filters: QueueFilters

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value or any(unicodedata.category(c).startswith("C") for c in value):
            raise ValueError("视图名称不能为空或包含控制字符")
        return value


class ViewCreate(ViewFields):
    request_id: UUID


class ViewUpdate(ViewFields):
    expected_version: int = Field(ge=1, strict=True)


class ViewDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1, strict=True)


def view_scope(user):
    return (SavedQueueView.tenant_id == user.tenant_id, SavedQueueView.user_id == user.id)


def view_dto(row):
    return {"id": row.id, "name": row.name, "filters": row.filters, "version": row.version,
        "created_at": iso_time(row.created_at), "updated_at": iso_time(row.updated_at)}


def normalized_filters(filters):
    result = dict(filters)
    if result.get("source") is None:
        result.pop("source", None)
    return result


def fingerprint(name, filters):
    filters = normalized_filters(filters)
    body = json.dumps({"name": name, "filters": filters}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


async def replay_view(db, user, request_id, digest):
    row = await db.scalar(select(SavedQueueView).where(SavedQueueView.request_id == request_id))
    if row is None:
        return None
    if row.tenant_id != user.tenant_id or row.user_id != user.id:
        raise HTTPException(404, "View request not found")
    if row.creation_fingerprint != digest:
        raise HTTPException(409, "该请求编号已用于另一个筛选视图")
    if row.deleted_at is not None:
        raise HTTPException(410, "该筛选视图已删除，不能恢复")
    return row


async def load_view(db, user, view_id):
    row = await db.scalar(select(SavedQueueView).where(*view_scope(user), SavedQueueView.id == str(view_id)))
    if row is None:
        raise HTTPException(404, "Queue view not found")
    return row


@router.get("/queue-views")
async def queue_views(user=Depends(get_current_user), db=Depends(get_db)):
    operator(user)
    rows = (await db.scalars(select(SavedQueueView).where(*view_scope(user), SavedQueueView.deleted_at.is_(None))
        .order_by(SavedQueueView.created_at, SavedQueueView.id))).all()
    return {"items": [view_dto(row) for row in rows], "limit": 10}


@router.post("/queue-views", status_code=201)
async def create_view(data: ViewCreate, user=Depends(get_current_user), db=Depends(get_db)):
    operator(user); user = identity(user)
    filters = normalized_filters(data.filters.model_dump(mode="json")); digest = fingerprint(data.name, filters)
    row = await replay_view(db, user, str(data.request_id), digest)
    if row:
        return {"view": view_dto(row), "cached": True}
    try:
        # Serialize this user's quota/name checks without changing their account timestamps.
        locked = await db.execute(update(User).where(User.id == user.id, User.tenant_id == user.tenant_id,
            User.is_active.is_(True)).values(updated_at=User.updated_at))
        if locked.rowcount != 1:
            raise HTTPException(404, "User not found")
        row = await replay_view(db, user, str(data.request_id), digest)
        if row:
            cached_view = view_dto(row)
            await db.rollback()
            return {"view": cached_view, "cached": True}
        count = await db.scalar(select(func.count()).select_from(SavedQueueView).where(*view_scope(user), SavedQueueView.deleted_at.is_(None)))
        if count >= 10:
            raise HTTPException(409, "每人最多保存 10 个筛选视图，请先删除不再使用的视图")
        row = SavedQueueView(request_id=str(data.request_id), creation_fingerprint=digest, tenant_id=user.tenant_id,
            user_id=user.id, name=data.name, name_key=data.name.casefold(), filters=filters)
        db.add(row); await db.commit()
        return {"view": view_dto(row), "cached": False}
    except IntegrityError:
        await db.rollback()
        row = await replay_view(db, user, str(data.request_id), digest)
        if row:
            return {"view": view_dto(row), "cached": True}
        raise HTTPException(409, "视图名称已存在或请求冲突，请刷新后重试")
    except Exception:
        await db.rollback(); raise


@router.put("/queue-views/{view_id}")
async def update_view(view_id: UUID, data: ViewUpdate, user=Depends(get_current_user), db=Depends(get_db)):
    operator(user)
    row = await load_view(db, user, view_id)
    if row.deleted_at is not None:
        raise HTTPException(404, "Queue view not found")
    try:
        changed = await db.execute(update(SavedQueueView).where(*view_scope(user), SavedQueueView.id == str(view_id),
            SavedQueueView.deleted_at.is_(None), SavedQueueView.version == data.expected_version).values(
            name=data.name, name_key=data.name.casefold(), filters=normalized_filters(data.filters.model_dump(mode="json")),
            version=SavedQueueView.version + 1, updated_at=datetime.now(timezone.utc)))
        if changed.rowcount != 1:
            raise HTTPException(409, "筛选视图已更新，请刷新后重试")
        await db.commit(); await db.refresh(row)
        return {"view": view_dto(row)}
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "该视图名称已存在")
    except Exception:
        await db.rollback(); raise


@router.delete("/queue-views/{view_id}")
async def delete_view(view_id: UUID, data: ViewDelete, user=Depends(get_current_user), db=Depends(get_db)):
    operator(user)
    row = await load_view(db, user, view_id)
    if row.deleted_at is not None:
        if row.version != data.expected_version + 1:
            raise HTTPException(409, "筛选视图版本不匹配")
        return {"ok": True, "version": row.version, "cached": True}
    changed = await db.execute(update(SavedQueueView).where(*view_scope(user), SavedQueueView.id == str(view_id),
        SavedQueueView.version == data.expected_version, SavedQueueView.deleted_at.is_(None)).values(
        deleted_at=datetime.now(timezone.utc), name_key=None, version=SavedQueueView.version + 1, updated_at=datetime.now(timezone.utc)))
    if changed.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "筛选视图已更新，请刷新后重试")
    await db.commit()
    return {"ok": True, "version": data.expected_version + 1, "cached": False}
