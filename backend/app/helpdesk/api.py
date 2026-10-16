import asyncio
import json
import time
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.helpdesk.catalog_snapshot import service_snapshot
from app.helpdesk.models import HelpdeskRun, RunbookChunk, HelpdeskTicketEvent, ManualTicketSubmission
from app.helpdesk.ticket_source import ticket_source_expression
from app.helpdesk.retrieval import embedding_identity, index_runbook
from app.helpdesk.ticket_ops import change_status, claim_ticket, find_ticket, record_event, sla_snapshot
from app.helpdesk.tools import services
from app.helpdesk.workflow import build_workflow, redact
from app.models.ticket import Ticket, TicketStatus
from app.models.user import User, UserRole

router = APIRouter(prefix="/helpdesk", tags=["ResolveAI IT HelpDesk"])


class RunRequest(BaseModel):
    request_id: UUID
    question: str = Field(min_length=4, max_length=2000)


class RunbookRequest(BaseModel):
    code: str = Field(pattern=r"^[A-Z]{2,10}-\d{3,5}$")
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=20, max_length=15000)
    keywords: str = Field(default="", max_length=500)


class TicketUpdate(BaseModel):
    status: TicketStatus
    expected_updated_at: datetime | None = None


class TicketClaim(BaseModel):
    expected_updated_at: datetime | None = None


class TicketNoteRequest(BaseModel):
    request_id: UUID
    note: str = Field(min_length=2, max_length=3000)


def operator(user):
    if user.role not in (UserRole.TENANT_OWNER, UserRole.TENANT_ADMIN, UserRole.SUPPORT_AGENT):
        raise HTTPException(403, "Workspace support role is required")


def utc_time(value):
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def reserve_run(data, db, user):
    question = redact(data.question.strip())
    if len(question) < 4:
        raise HTTPException(422, "Please describe the problem in at least four characters")
    identity = str(data.request_id)
    existing = await db.get(HelpdeskRun, identity)
    if existing:
        if existing.tenant_id != user.tenant_id or existing.user_id != user.id:
            raise HTTPException(404, "Run not found")
        if existing.question != question:
            raise HTTPException(409, "Request ID already belongs to another question")
        if existing.result.get("status") == "running":
            raise HTTPException(409, "This request is already running")
        return existing, True
    run = HelpdeskRun(id=identity, tenant_id=user.tenant_id, user_id=user.id, question=question, result={"status": "running"})
    db.add(run)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "This request is already running")
    return run, False


async def execute(run, db, user):
    start = time.perf_counter()
    identity = run.id
    trace = []
    state = {"question": run.question}
    try:
        graph = build_workflow(db, user)
        async with asyncio.timeout(100):
            async for update in graph.astream(state, stream_mode="updates", config={"recursion_limit": 20}):
                for values in update.values():
                    state.update(values)
                    step = values.get("last_step")
                    if step:
                        trace.append(step)
                        yield {"type": "trace", "step": step}
        state.pop("last_step", None)
        result = {**state, "run_id": run.id, "status": "completed", "trace": trace,
                  "latency_ms": round((time.perf_counter() - start) * 1000, 2), "tool_data": "simulated",
                  "embedding_provider": embedding_identity(), "retrieval_backend": db.bind.dialect.name}
        run.result = result
        await db.commit()  # Ticket and completed trace are committed together.
        yield {"type": "result", "result": result}
    except Exception:
        logging.getLogger(__name__).exception("ResolveAI diagnosis failed: %s", identity)
        await db.rollback()
        failed = {"run_id": identity, "status": "failed", "trace": trace,
                  "error": "诊断未完成，请检查服务日志、模型配置和数据库连接。"}
        persisted = await db.get(HelpdeskRun, identity)
        persisted.result = failed
        await db.commit()
        yield {"type": "error", "result": failed}
    except asyncio.CancelledError:
        await db.rollback()
        persisted = await db.get(HelpdeskRun, identity)
        persisted.result = {"run_id": identity, "status": "cancelled", "trace": trace, "error": "诊断连接已取消，请重新提交。"}
        await db.commit()
        raise


@router.post("/runs")
async def run_diagnosis(data: RunRequest, user: User = Depends(get_current_user), db=Depends(get_db)):
    run, cached = await reserve_run(data, db, user)
    if cached:
        return run.result
    result = None
    async for event in execute(run, db, user):
        if event["type"] in ("result", "error"):
            result = event["result"]
    if result["status"] == "failed":
        raise HTTPException(502, result["error"])
    return result


@router.post("/runs/stream")
async def stream_diagnosis(data: RunRequest, user: User = Depends(get_current_user), db=Depends(get_db)):
    run, cached = await reserve_run(data, db, user)
    async def events():
        if cached:
            yield "data: " + json.dumps({"type": "result", "result": run.result}, ensure_ascii=False) + "\n\n"
            return
        async for event in execute(run, db, user):
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/overview")
async def overview(user: User = Depends(get_current_user), db=Depends(get_db)):
    chunks = await db.scalar(select(func.count()).select_from(RunbookChunk).where(RunbookChunk.tenant_id == user.tenant_id))
    runs = await db.scalar(select(func.count()).select_from(HelpdeskRun).where(HelpdeskRun.tenant_id == user.tenant_id, HelpdeskRun.user_id == user.id))
    open_tickets = await db.scalar(select(func.count()).select_from(Ticket).where(Ticket.tenant_id == user.tenant_id, Ticket.status.not_in([TicketStatus.RESOLVED, TicketStatus.CLOSED])))
    return {"chunks": chunks, "runs": runs, "open_tickets": open_tickets, "mode": settings.DEFAULT_LLM_PROVIDER,
            "embedding_provider": embedding_identity(), "database": db.bind.dialect.name, "tool_data": "simulated", "services": services()}


@router.get("/runs")
async def history(user: User = Depends(get_current_user), db=Depends(get_db)):
    rows = (await db.scalars(select(HelpdeskRun).where(HelpdeskRun.tenant_id == user.tenant_id, HelpdeskRun.user_id == user.id)
                            .order_by(HelpdeskRun.created_at.desc()).limit(30))).all()
    return [{"id": r.id, "question": r.question, "created_at": utc_time(r.created_at), "result": r.result} for r in rows]


@router.get("/runbooks")
async def runbooks(user: User = Depends(get_current_user), db=Depends(get_db)):
    rows = (await db.scalars(select(RunbookChunk).where(RunbookChunk.tenant_id == user.tenant_id).order_by(RunbookChunk.code, RunbookChunk.chunk_index))).all()
    return [{"id": r.id, "code": r.code, "title": r.title, "content": r.content, "keywords": r.keywords} for r in rows]


@router.post("/runbooks", status_code=201)
async def add_runbook(data: RunbookRequest, user: User = Depends(get_current_user), db=Depends(get_db)):
    if user.role not in (UserRole.TENANT_OWNER, UserRole.TENANT_ADMIN):
        raise HTTPException(403, "Only workspace administrators can add knowledge")
    from app.helpdesk.knowledge import save_document
    return await save_document(db, user, data.code, data.model_dump(), action="created")


def ticket_dict(ticket, agent_name=None, now=None, include_description=True):
    result={"id": ticket.id, "subject": ticket.subject, "status": ticket.status.value,
        "priority": ticket.priority.value, "reason": ticket.escalation_reason,
        "created_at": utc_time(ticket.created_at), "updated_at": utc_time(ticket.updated_at),
        "resolved_at": utc_time(ticket.resolved_at) if ticket.resolved_at else None,
        "assigned_agent_id": ticket.assigned_agent_id, "assigned_agent_name": agent_name,
        "sla": sla_snapshot(ticket, now)}
    if include_description:
        result["description"]=ticket.description
    return result


@router.get("/tickets")
async def tickets(user: User = Depends(get_current_user), db=Depends(get_db)):
    operator(user)
    rows = (await db.execute(select(Ticket, User.full_name).outerjoin(User, and_(
        User.id == Ticket.assigned_agent_id, User.tenant_id == Ticket.tenant_id)).where(
        Ticket.tenant_id == user.tenant_id).order_by(Ticket.created_at.desc()).limit(100))).all()
    return [ticket_dict(ticket, name) for ticket, name in rows]


@router.get("/tickets/{ticket_id}")
async def ticket_detail(ticket_id: UUID, user: User = Depends(get_current_user), db=Depends(get_db)):
    operator(user)
    ticket = await find_ticket(db, user, ticket_id)
    name = await db.scalar(select(User.full_name).where(User.id == ticket.assigned_agent_id, User.tenant_id == user.tenant_id)) if ticket.assigned_agent_id else None
    condition = (HelpdeskTicketEvent.ticket_id == ticket.id, HelpdeskTicketEvent.tenant_id == user.tenant_id)
    # Fetch one sentinel row so a concurrent insert cannot make the cursor
    # calculation depend on a separate COUNT query's snapshot.
    events = list((await db.scalars(select(HelpdeskTicketEvent).where(*condition).order_by(
        HelpdeskTicketEvent.sequence.desc()).limit(101))).all())
    count = await db.scalar(select(func.count()).select_from(HelpdeskTicketEvent).where(*condition))
    has_more = len(events) > 100
    events = events[:100]
    detail_ticket = ticket_dict(ticket, name)
    submission = await db.scalar(select(ManualTicketSubmission).where(
        ManualTicketSubmission.tenant_id == ticket.tenant_id, ManualTicketSubmission.ticket_id == ticket.id))
    source_code = "manual" if submission else await db.scalar(select(ticket_source_expression()).where(
        Ticket.id == ticket.id, Ticket.tenant_id == user.tenant_id))
    detail_ticket["source"] = source_code
    if submission:
        detail_ticket["request"] = {"description": submission.payload["description"], "category": submission.payload["category"]}
        snapshot = service_snapshot(submission.payload)
        if snapshot:
            detail_ticket["request"]["service"] = snapshot
    return {"ticket": detail_ticket, "event_count": count,
        "can_manage_assignment": user.role in (UserRole.TENANT_OWNER, UserRole.TENANT_ADMIN),
        "has_more": has_more, "next_before": events[-1].sequence if has_more else None,
        "events": [{"id": event.id, "type": event.event_type, "author": event.author_name,
                    "payload": event.payload, "created_at": utc_time(event.created_at)} for event in reversed(events)]}


@router.patch("/tickets/{ticket_id}")
async def update_ticket(ticket_id: UUID, data: TicketUpdate, user: User = Depends(get_current_user), db=Depends(get_db)):
    operator(user)
    ticket = await find_ticket(db, user, ticket_id)
    if data.status == TicketStatus.RESOLVED and ticket.status != TicketStatus.RESOLVED:
        raise HTTPException(409, "请通过解决记录填写公开分类、摘要和排查步骤，再标记解决")
    await change_status(db, user, ticket, data.status, data.expected_updated_at)
    await db.commit()
    return {"id": ticket.id, "status": ticket.status.value, "updated_at": utc_time(ticket.updated_at)}


@router.post("/tickets/{ticket_id}/claim")
async def take_ticket(ticket_id: UUID, data: TicketClaim, user: User = Depends(get_current_user), db=Depends(get_db)):
    operator(user)
    ticket = await find_ticket(db, user, ticket_id)
    await claim_ticket(db, user, ticket, data.expected_updated_at)
    await db.commit()
    return {"id": ticket.id, "status": ticket.status.value, "assigned_agent_id": ticket.assigned_agent_id}


@router.post("/tickets/{ticket_id}/notes", status_code=201)
async def add_ticket_note(ticket_id: UUID, data: TicketNoteRequest, user: User = Depends(get_current_user), db=Depends(get_db)):
    operator(user)
    ticket = await find_ticket(db, user, ticket_id)
    text = redact(data.note.strip())
    if len(text) < 2:
        raise HTTPException(422, "备注至少需要两个字符")
    existing = await db.scalar(select(HelpdeskTicketEvent).where(HelpdeskTicketEvent.id == str(data.request_id)))
    if existing:
        if existing.tenant_id != user.tenant_id or existing.ticket_id != ticket.id or existing.author_id != user.id:
            raise HTTPException(404, "Note not found")
        if existing.event_type != "note" or existing.payload != {"text": text}:
            raise HTTPException(409, "Request ID already belongs to another note")
        return {"id": existing.id, "cached": True}
    event = record_event(db, ticket, user, "note", {"text": text}, str(data.request_id))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "备注请求正在处理，请稍后重试")
    return {"id": event.id, "cached": False}


@router.get("/analytics")
async def analytics(days: int = Query(default=7, ge=1, le=90), user: User = Depends(get_current_user), db=Depends(get_db)):
    from app.helpdesk.analytics import DISPLAY_ZONE, summarize_runs
    operator(user)
    now = datetime.now(timezone.utc)
    first_day = now.astimezone(DISPLAY_ZONE).date() - timedelta(days=days - 1)
    start = datetime.combine(first_day, datetime.min.time(), tzinfo=DISPLAY_ZONE).astimezone(timezone.utc)
    rows = (await db.scalars(select(HelpdeskRun).where(
        HelpdeskRun.tenant_id == user.tenant_id, HelpdeskRun.user_id == user.id,
        HelpdeskRun.created_at >= start, HelpdeskRun.created_at <= now))).all()
    summary = summarize_runs(rows, days, now)
    counts = (await db.execute(select(Ticket.status, func.count(Ticket.id)).where(
        Ticket.tenant_id == user.tenant_id).group_by(Ticket.status))).all()
    summary["ticket_statuses"] = {status.value: count for status, count in counts}
    summary["scope"] = {"runs": "current_user", "tickets": "current_workspace_all_time"}
    summary["generated_at"] = now
    return summary


class RunFeedbackRequest(BaseModel):
    helpful: bool = Field(strict=True)


@router.post("/runs/{run_id}/feedback")
async def give_feedback(run_id: UUID, data: RunFeedbackRequest, user: User = Depends(get_current_user), db=Depends(get_db)):
    run = await db.scalar(select(HelpdeskRun).where(HelpdeskRun.id == str(run_id),
        HelpdeskRun.tenant_id == user.tenant_id, HelpdeskRun.user_id == user.id))
    if not run:
        raise HTTPException(404, "Run not found")
    if run.result.get("status") != "completed":
        raise HTTPException(409, "只能评价已完成的诊断")
    previous = run.result.get("feedback")
    if isinstance(previous, dict) and previous.get("helpful") == data.helpful:
        return previous
    feedback = {"helpful": data.helpful, "updated_at": datetime.now(timezone.utc).isoformat()}
    run.result = {**run.result, "feedback": feedback}
    await db.commit()
    return feedback
