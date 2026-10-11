import asyncio
import json
import time
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.helpdesk.models import HelpdeskRun, RunbookChunk
from app.helpdesk.retrieval import embedding_identity, index_runbook
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
    if await db.scalar(select(RunbookChunk.id).where(RunbookChunk.tenant_id == user.tenant_id, RunbookChunk.code == data.code)):
        raise HTTPException(409, "Source code already exists")
    count = await index_runbook(db, user.tenant_id, data.model_dump())
    await db.commit()
    return {"code": data.code, "chunks": count}


@router.get("/tickets")
async def tickets(user: User = Depends(get_current_user), db=Depends(get_db)):
    operator(user)
    rows = (await db.scalars(select(Ticket).where(Ticket.tenant_id == user.tenant_id).order_by(Ticket.created_at.desc()).limit(100))).all()
    return [{"id": t.id, "subject": t.subject, "status": t.status.value, "priority": t.priority.value,
             "description": t.description, "created_at": utc_time(t.created_at), "reason": t.escalation_reason} for t in rows]


@router.patch("/tickets/{ticket_id}")
async def update_ticket(ticket_id: UUID, data: TicketUpdate, user: User = Depends(get_current_user), db=Depends(get_db)):
    operator(user)
    ticket = await db.scalar(select(Ticket).where(Ticket.id == str(ticket_id), Ticket.tenant_id == user.tenant_id))
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    transitions = {
        TicketStatus.OPEN: {TicketStatus.IN_PROGRESS, TicketStatus.ESCALATED},
        TicketStatus.ESCALATED: {TicketStatus.IN_PROGRESS},
        TicketStatus.IN_PROGRESS: {TicketStatus.RESOLVED, TicketStatus.WAITING_FOR_CUSTOMER},
        TicketStatus.WAITING_FOR_CUSTOMER: {TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED},
        TicketStatus.RESOLVED: {TicketStatus.CLOSED, TicketStatus.IN_PROGRESS},
        TicketStatus.CLOSED: {TicketStatus.IN_PROGRESS},
    }
    if data.status != ticket.status and data.status not in transitions[ticket.status]:
        raise HTTPException(409, "Invalid ticket status transition")
    ticket.status = data.status
    ticket.resolved_at = datetime.now(timezone.utc) if data.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED) else None
    await db.commit()
    return {"id": ticket.id, "status": ticket.status.value}


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
