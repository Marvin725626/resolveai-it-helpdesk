"""Bearer-authenticated, ticket-scoped private attachments."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_current_user
from app.core.database import get_db
from app.helpdesk.api import operator
from app.helpdesk.attachment_storage import MAX_FILE_BYTES, safe_filename, storage_path, validated_type
from app.helpdesk.models import HelpdeskTicketAttachment
from app.helpdesk.requester_api import iso_time, requester_ticket
from app.helpdesk.ticket_ops import atomic_change, check_revision, find_ticket, notify_event, record_event
from app.models.ticket import TicketStatus
from app.models.user import UserRole

router = APIRouter(prefix="/helpdesk", tags=["Private ticket attachments"])
Scope = Literal["my-tickets", "tickets"]
MANAGERS = (UserRole.TENANT_OWNER, UserRole.TENANT_ADMIN)


def principal(user):
    # Rollback expires ORM users as well as tickets; keep identity independent of the session.
    return SimpleNamespace(id=user.id, tenant_id=user.tenant_id, role=user.role, full_name=user.full_name)


async def scoped_ticket(db, user, ticket_id, scope_kind):
    if scope_kind == "my-tickets":
        return await requester_ticket(db, user, ticket_id)
    operator(user)
    return await find_ticket(db, user, ticket_id)


def can_upload(ticket, user, scope_kind):
    return ticket.status != TicketStatus.CLOSED and (scope_kind == "my-tickets" or user.role in MANAGERS or ticket.assigned_agent_id == user.id)


def can_delete(row, user):
    return row.uploader_id == user.id or user.role in MANAGERS


def attachment_dto(row, user):
    return {"id": row.id, "filename": row.filename, "content_type": row.content_type,
        "size_bytes": row.size_bytes, "sha256": row.sha256, "uploader_name": row.uploader_name,
        "direction": row.direction, "created_at": iso_time(row.created_at), "can_delete": can_delete(row, user)}


async def find_attachment(db, user, ticket_id, attachment_id):
    row = await db.scalar(select(HelpdeskTicketAttachment).where(HelpdeskTicketAttachment.id == str(attachment_id),
        HelpdeskTicketAttachment.tenant_id == user.tenant_id, HelpdeskTicketAttachment.ticket_id == ticket_id))
    if row is None:
        raise HTTPException(404, "Attachment not found")
    return row


@router.get("/{scope_kind}/{ticket_id}/attachments")
async def attachments(scope_kind: Scope, ticket_id: UUID, before: int | None = Query(None, ge=1),
        page_size: int = Query(20, ge=1, le=50), user=Depends(get_current_user), db=Depends(get_db)):
    ticket = await scoped_ticket(db, user, ticket_id, scope_kind)
    conditions = [HelpdeskTicketAttachment.tenant_id == user.tenant_id,
        HelpdeskTicketAttachment.ticket_id == ticket.id, HelpdeskTicketAttachment.deleted_at.is_(None)]
    if before is not None:
        conditions.append(HelpdeskTicketAttachment.sequence < before)
    rows = list((await db.scalars(select(HelpdeskTicketAttachment).where(*conditions)
        .order_by(HelpdeskTicketAttachment.sequence.desc()).limit(page_size + 1))).all())
    more = len(rows) > page_size; rows = rows[:page_size]
    return {"items": [attachment_dto(row, user) for row in rows], "has_more": more,
        "next_before": rows[-1].sequence if more else None, "can_upload": can_upload(ticket, user, scope_kind),
        "updated_at": iso_time(ticket.updated_at)}


async def replay_upload(db, user, ticket, request_id, filename, digest, direction):
    row = await db.scalar(select(HelpdeskTicketAttachment).where(HelpdeskTicketAttachment.request_id == request_id))
    if row is None:
        return None
    if row.tenant_id != user.tenant_id or row.ticket_id != ticket.id or row.uploader_id != user.id:
        raise HTTPException(404, "Attachment request not found")
    if row.filename != filename or row.sha256 != digest or row.direction != direction:
        raise HTTPException(409, "该请求编号已用于另一份附件")
    if row.deleted_at is not None:
        raise HTTPException(410, "该附件已删除，不能恢复；请使用新的上传请求")
    return {"item": attachment_dto(row, user), "updated_at": iso_time(ticket.updated_at), "cached": True}


@router.post("/{scope_kind}/{ticket_id}/attachments", status_code=201)
async def upload_attachment(scope_kind: Scope, ticket_id: UUID, request_id: UUID = Form(...),
        expected_updated_at: datetime = Form(...), file: UploadFile = File(...),
        user=Depends(get_current_user), db=Depends(get_db)):
    user = principal(user)
    ticket_identity = str(ticket_id)
    ticket = await scoped_ticket(db, user, ticket_id, scope_kind)
    filename = safe_filename(file.filename)
    direction = "requester" if scope_kind == "my-tickets" else "support"
    identity = str(uuid4())
    key = f"{user.tenant_id}/{identity}"
    final_path = storage_path(key)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = final_path.parent / (".tmp-" + identity)
    finalized = False
    committed = False
    size = 0; digest = hashlib.sha256()
    try:
        with temporary.open("xb") as target:
            while chunk := await file.read(64 * 1024):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise HTTPException(413, "单个附件不能超过 5 MiB")
                digest.update(chunk); target.write(chunk)
        content_type = validated_type(filename, temporary.read_bytes())
        checksum = digest.hexdigest()
        replay = await replay_upload(db, user, ticket, str(request_id), filename, checksum, direction)
        if replay:
            return replay
        check_revision(ticket, expected_updated_at)
        if ticket.status == TicketStatus.CLOSED:
            raise HTTPException(409, "已关闭工单不能新增附件")
        if not can_upload(ticket, user, scope_kind):
            raise HTTPException(403, "只有当前接手人或工作区管理员可上传附件")
        resumed = scope_kind == "my-tickets" and ticket.status == TicketStatus.WAITING_FOR_CUSTOMER
        await atomic_change(db, ticket, {"status": TicketStatus.IN_PROGRESS} if resumed else {})
        count = await db.scalar(select(func.count()).select_from(HelpdeskTicketAttachment).where(
            HelpdeskTicketAttachment.tenant_id == user.tenant_id, HelpdeskTicketAttachment.ticket_id == ticket_identity,
            HelpdeskTicketAttachment.deleted_at.is_(None)))
        if count >= 20:
            raise HTTPException(409, "每张工单最多保留 20 份活跃附件，请先删除不再需要的附件")
        if resumed:
            record_event(db, ticket, user, "status_changed", {"from": "WAITING_FOR_CUSTOMER", "to": "IN_PROGRESS"})
        row = HelpdeskTicketAttachment(id=identity, request_id=str(request_id), tenant_id=user.tenant_id,
            ticket_id=ticket_identity, uploader_id=user.id, uploader_name=user.full_name, direction=direction,
            filename=filename, content_type=content_type, size_bytes=size, sha256=checksum, storage_key=key)
        db.add(row)
        event = record_event(db, ticket, user, "attachment_added", {"attachment_id": identity, "direction": direction}, str(request_id))
        await db.flush()
        temporary.replace(final_path); finalized = True
        await notify_event(db, ticket, user, event)
        await db.commit(); committed = True
        return {"item": attachment_dto(row, user), "updated_at": iso_time(ticket.updated_at), "cached": False}
    except IntegrityError:
        await db.rollback()
        if finalized:
            final_path.unlink(missing_ok=True); finalized = False
        ticket = await scoped_ticket(db, user, ticket_identity, scope_kind)
        replay = await replay_upload(db, user, ticket, str(request_id), filename, digest.hexdigest(), direction)
        if replay:
            return replay
        raise HTTPException(409, "附件请求冲突，请刷新后重试")
    except Exception:
        await db.rollback()
        raise
    finally:
        await file.close()
        temporary.unlink(missing_ok=True)
        if finalized and not committed:
            final_path.unlink(missing_ok=True)


@router.get("/{scope_kind}/{ticket_id}/attachments/{attachment_id}/download")
async def download_attachment(scope_kind: Scope, ticket_id: UUID, attachment_id: UUID,
        user=Depends(get_current_user), db=Depends(get_db)):
    ticket = await scoped_ticket(db, user, ticket_id, scope_kind)
    row = await find_attachment(db, user, ticket.id, attachment_id)
    if row.deleted_at is not None:
        raise HTTPException(404, "Attachment not found")
    try:
        path = storage_path(row.storage_key)
        if path.stat().st_size > MAX_FILE_BYTES:
            raise HTTPException(404, "Attachment not found")
        content = path.read_bytes()
    except (OSError, ValueError):
        raise HTTPException(404, "Attachment not found")
    return Response(content, media_type=row.content_type, headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(row.filename, safe=""),
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


class DeleteAttachment(BaseModel):
    expected_updated_at: datetime


@router.delete("/{scope_kind}/{ticket_id}/attachments/{attachment_id}")
async def delete_attachment(scope_kind: Scope, ticket_id: UUID, attachment_id: UUID, data: DeleteAttachment,
        user=Depends(get_current_user), db=Depends(get_db)):
    user = principal(user)
    ticket = await scoped_ticket(db, user, ticket_id, scope_kind)
    row = await find_attachment(db, user, ticket.id, attachment_id)
    if not can_delete(row, user):
        raise HTTPException(403, "只有上传者或工作区管理员可删除附件")
    path = storage_path(row.storage_key)
    if row.deleted_at is None:
        check_revision(ticket, data.expected_updated_at)
        await atomic_change(db, ticket, {})
        row.deleted_at = datetime.now(timezone.utc)
        event = record_event(db, ticket, user, "attachment_deleted", {"attachment_id": row.id, "direction": row.direction})
        try:
            await db.flush()
            await notify_event(db, ticket, user, event)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    # The tombstone is durable before touching the file. A failed unlink is safe to retry.
    pending = False
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pending = True
    return {"ok": True, "cleanup_pending": pending, "updated_at": iso_time(ticket.updated_at)}
