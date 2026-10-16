from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import load_only

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.helpdesk.api import operator, ticket_dict, utc_time
from app.helpdesk.models import HelpdeskRun, RunbookChunk
from app.helpdesk.ticket_source import ticket_source_expression
from app.helpdesk.retrieval import embedding_identity
from app.helpdesk.ticket_ops import FINISHED, SLA_HOURS
from app.models.ticket import Ticket, TicketPriority, TicketStatus
from app.models.user import User

router=APIRouter(prefix="/helpdesk",tags=["Paged queues and operational checks"])
SlaFilter=Literal["on_track","due_soon","overdue"]
RunStatus=Literal["running","completed","failed","cancelled","interrupted"]
Category=Literal["vpn","account","software","service","email","unknown"]

def ticket_conditions(user,q,status,priority,assignment,sla,now,source=None):
    conditions=[Ticket.tenant_id==user.tenant_id]
    if q.strip():
        text=q.strip()
        conditions.append(or_(Ticket.subject.icontains(text,autoescape=True),Ticket.escalation_reason.icontains(text,autoescape=True),Ticket.id.icontains(text,autoescape=True)))
    if status:conditions.append(Ticket.status==status)
    if source:conditions.append(ticket_source_expression()==source)
    if priority:conditions.append(Ticket.priority==priority)
    if assignment=="mine":conditions.append(Ticket.assigned_agent_id==user.id)
    if assignment=="unassigned":conditions.append(Ticket.assigned_agent_id.is_(None))
    if sla:
        ranges=[]
        for key,hours in SLA_HOURS.items():
            due_cutoff=now-timedelta(hours=hours)
            near_cutoff=due_cutoff+timedelta(minutes=min(60,hours*15))
            if sla=="overdue":window=Ticket.created_at<=due_cutoff
            elif sla=="due_soon":window=and_(Ticket.created_at>due_cutoff,Ticket.created_at<=near_cutoff)
            else:window=Ticket.created_at>near_cutoff
            ranges.append(and_(Ticket.priority==TicketPriority(key),window))
        conditions.extend([Ticket.status.not_in(list(FINISHED)),or_(*ranges)])
    return conditions

async def queue_result(db,user,q,status,priority,assignment,sla,page,size,export=False,source=None):
    now=datetime.now(timezone.utc)
    conditions=ticket_conditions(user,q,status,priority,assignment,sla,now,source)
    total=await db.scalar(select(func.count()).select_from(Ticket).where(*conditions))
    stmt=select(Ticket,User.full_name,ticket_source_expression().label("source")).options(load_only(Ticket.id,Ticket.tenant_id,Ticket.subject,Ticket.status,Ticket.priority,Ticket.escalation_reason,Ticket.created_at,Ticket.updated_at,Ticket.resolved_at,Ticket.assigned_agent_id)).outerjoin(User,and_(User.id==Ticket.assigned_agent_id,User.tenant_id==Ticket.tenant_id)).where(*conditions).order_by(Ticket.created_at.desc(),Ticket.id.desc())
    limit=1000 if export else size
    rows=(await db.execute(stmt.offset(0 if export else (page-1)*size).limit(limit))).all()
    return {"items":[{**ticket_dict(ticket,name,now,False),"source":source_code} for ticket,name,source_code in rows],"total":total,"page":page,"page_size":limit,
            "truncated":bool(export and total>limit),"scope":"current_workspace","as_of":now}

@router.get("/ticket-queue")
async def queue(q:str=Query(default="",max_length=200),status:TicketStatus|None=None,priority:TicketPriority|None=None,
                assignment:Literal["all","mine","unassigned"]="all",sla:SlaFilter|None=None,
                page:int=Query(default=1,ge=1,le=100000),page_size:int=Query(default=20,ge=1,le=100),source:Literal["manual","ai","legacy"]|None=None,
                user=Depends(get_current_user),db=Depends(get_db)):
    operator(user)
    return await queue_result(db,user,q,status,priority,assignment,sla,page,page_size,source=source)

@router.get("/ticket-queue/export")
async def export_queue(q:str=Query(default="",max_length=200),status:TicketStatus|None=None,priority:TicketPriority|None=None,
                assignment:Literal["all","mine","unassigned"]="all",sla:SlaFilter|None=None,source:Literal["manual","ai","legacy"]|None=None,
                user=Depends(get_current_user),db=Depends(get_db)):
    operator(user)
    return await queue_result(db,user,q,status,priority,assignment,sla,1,1000,True,source)

@router.get("/run-history")
async def run_history(q:str=Query(default="",max_length=200),status:RunStatus|None=None,category:Category|None=None,
                days:int|None=Query(default=None,ge=1,le=365),page:int=Query(default=1,ge=1,le=100000),
                page_size:int=Query(default=20,ge=1,le=100),user=Depends(get_current_user),db=Depends(get_db)):
    conditions=[HelpdeskRun.tenant_id==user.tenant_id,HelpdeskRun.user_id==user.id]
    if q.strip():conditions.append(or_(HelpdeskRun.question.icontains(q.strip(),autoescape=True),HelpdeskRun.id.icontains(q.strip(),autoescape=True)))
    if status:conditions.append(HelpdeskRun.result["status"].as_string()==status)
    if category:conditions.append(HelpdeskRun.result["category"].as_string()==category)
    if days:conditions.append(HelpdeskRun.created_at>=datetime.now(timezone.utc)-timedelta(days=days))
    total=await db.scalar(select(func.count()).select_from(HelpdeskRun).where(*conditions))
    rows=(await db.execute(select(HelpdeskRun.id,HelpdeskRun.question,HelpdeskRun.created_at,
        HelpdeskRun.result["status"].as_string().label("run_status"),HelpdeskRun.result["category"].as_string().label("category"),
        HelpdeskRun.result["latency_ms"].as_float().label("latency"),HelpdeskRun.result["escalate"].as_boolean().label("escalate"))
        .where(*conditions).order_by(HelpdeskRun.created_at.desc(),HelpdeskRun.id.desc()).offset((page-1)*page_size).limit(page_size))).all()
    return {"items":[{"id":row.id,"question":row.question,"created_at":utc_time(row.created_at),
                     "result":{"status":row.run_status,"category":row.category,"latency_ms":row.latency,"escalate":row.escalate}} for row in rows],
            "total":total,"page":page,"page_size":page_size,"scope":"current_user"}


@router.get("/readiness")
async def readiness(user=Depends(get_current_user),db=Depends(get_db)):
    await db.scalar(select(1))
    count=await db.scalar(select(func.count()).select_from(RunbookChunk).where(RunbookChunk.tenant_id==user.tenant_id))
    matched=await db.scalar(select(func.count()).select_from(RunbookChunk).where(RunbookChunk.tenant_id==user.tenant_id,RunbookChunk.embedding_provider==embedding_identity()))
    warnings=[]
    if not count:warnings.append("当前工作区没有启用的知识片段")
    if count!=matched:warnings.append("部分知识片段的 embedding 身份与当前配置不一致，请重新索引")
    if (settings.DEFAULT_LLM_PROVIDER=="openai" or settings.IT_EMBEDDING_PROVIDER=="openai") and not settings.OPENAI_API_KEY:
        warnings.append("已选择远程模型或 embedding，但尚未配置 API Key")
    if settings.DEFAULT_LLM_PROVIDER not in ("mock","openai"):warnings.append("IT 诊断流程仅验证了 mock 与 OpenAI-compatible 模式")
    return {"database":{"connected":True,"backend":db.bind.dialect.name},
            "knowledge":{"indexed_chunks":count,"embedding_identity_matches":matched},
            "configuration":{"mode":settings.DEFAULT_LLM_PROVIDER,"embedding":embedding_identity(),
                "embedding_dimension":settings.IT_EMBEDDING_DIMENSION,"model_key_configured":bool(settings.OPENAI_API_KEY)},
            "external_model_connectivity":"not_checked","enterprise_tools":"simulated",
            "warnings":warnings,"checked_at":datetime.now(timezone.utc),"scope":"current_workspace"}


@router.get("/evaluation-report")
async def evaluation_report(user=Depends(get_current_user)):
    import json
    from pathlib import Path
    path=Path(__file__).resolve().parents[3]/"docs"/"evaluation.offline.json"
    if not path.exists():
        raise HTTPException(404,"尚无离线评估报告，请在开发环境生成报告")
    return {"source":"bundled_offline_fixture_report","report":json.loads(path.read_text(encoding="utf-8"))}
