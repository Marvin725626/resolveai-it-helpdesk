"""Isolated regression tests for actual ResolveAI workflows, not live user data."""
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

test_dir = tempfile.TemporaryDirectory(prefix="resolveai-tests-")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + str(Path(test_dir.name) / "test.db").replace("\\", "/")
os.environ["DEFAULT_LLM_PROVIDER"] = "mock"
os.environ["IT_EMBEDDING_PROVIDER"] = "local"
os.environ["APP_ENV"] = "development"
os.environ["IT_DEMO_ENABLED"] = "true"

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def auth(client):
    response = client.post("/api/v1/auth/login", json={"email": "demo@resolveai.example.com", "password": "ResolveAI123!"})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def diagnose(client, auth, question, identity=None):
    response = client.post("/api/v1/helpdesk/runs", headers=auth, json={"request_id": identity or str(uuid4()), "question": question})
    assert response.status_code == 200, response.text
    return response.json()


def test_requires_identity(client):
    assert client.get("/api/v1/helpdesk/overview").status_code == 401


def test_software_answer_is_grounded(client, auth):
    run = diagnose(client, auth, "如何安装公司批准的办公软件？")
    assert run["supported"] and not run["escalate"]
    assert run["evidence"][0]["code"] == "APP-001"
    assert "[APP-001]" in run["answer"]
    assert not run["ticket_id"]


def test_vpn_outage_escalates_with_context(client, auth):
    run = diagnose(client, auth, "VPN 连不上，提示认证超时，怎么排查？")
    assert run["ticket_id"] and run["escalate"]
    assert run["evidence"][0]["code"] == "VPN-001"
    tool = next(t for t in run["tools"] if t["name"] == "get_service_status")
    assert tool["result"]["status"] == "degraded"
    tickets = client.get("/api/v1/helpdesk/tickets", headers=auth).json()
    ticket = next(t for t in tickets if t["id"] == run["ticket_id"])
    context = __import__('json').loads(ticket["description"])
    assert context["evidence"] and context["tools"] and context["question"]


def test_missing_evidence_is_bounded(client, auth):
    run = diagnose(client, auth, "如何购买潜水艇发动机？")
    assert not run["supported"] and run["ticket_id"]
    assert len([t for t in run["trace"] if t["node"] == "retrieval"]) == 2


def test_human_request_escalates(client, auth):
    run = diagnose(client, auth, "账号权限申请，请帮我转人工审批")
    assert run["escalate"] and run["ticket_id"]
    assert not any(t["name"] in {"reset_password", "grant_access"} for t in run["tools"])


def test_account_issue_uses_account_runbook(client, auth):
    run = diagnose(client, auth, "账号锁定无法登录怎么办")
    assert run["evidence"][0]["code"] == "IAM-001"
    assert run["answer_sources"] == ["IAM-001"]
    assert "[VPN-001]" not in run["answer"]


def test_repeat_request_does_not_duplicate_ticket(client, auth):
    identity = str(uuid4())
    first = diagnose(client, auth, "VPN 连接超时", identity)
    second = diagnose(client, auth, "VPN 连接超时", identity)
    assert first == second
    tickets = client.get("/api/v1/helpdesk/tickets", headers=auth).json()
    assert len([t for t in tickets if t["id"] == first["ticket_id"]]) == 1
    different = client.post("/api/v1/helpdesk/runs", headers=auth, json={"request_id": identity, "question": "软件安装怎么操作"})
    assert different.status_code == 409


def test_stream_delivers_steps_then_result(client, auth):
    response = client.post("/api/v1/helpdesk/runs/stream", headers=auth, json={"request_id": str(uuid4()), "question": "邮箱无法同步怎么排查？"})
    assert response.status_code == 200 and "text/event-stream" in response.headers["content-type"]
    events = [__import__('json').loads(block[6:]) for block in response.text.strip().split("\n\n")]
    assert events[0]["step"]["node"] == "router"
    assert events[-1]["type"] == "result"
    assert events[-1]["result"]["status"] == "completed"


def test_ticket_transitions(client, auth):
    run = diagnose(client, auth, "VPN 认证超时需要支持")
    path = "/api/v1/helpdesk/tickets/" + run["ticket_id"]
    assert client.patch(path, headers=auth, json={"status": "CLOSED"}).status_code == 409
    for status in ["IN_PROGRESS", "RESOLVED", "CLOSED"]:
        response = client.patch(path, headers=auth, json={"status": status})
        assert response.status_code == 200 and response.json()["status"] == status


def test_workspace_isolation(client, auth):
    response = client.post("/api/v1/auth/register", json={"email": "other@resolveai.example.com", "password": "OtherTenant123!", "full_name": "Other owner", "tenant_name": "Other", "tenant_slug": "other-" + uuid4().hex})
    assert response.status_code == 201, response.text
    other = {"Authorization": "Bearer " + response.json()["access_token"]}
    assert client.get("/api/v1/helpdesk/runbooks", headers=other).json() == []
    assert client.get("/api/v1/helpdesk/runs", headers=other).json() == []
    assert client.get("/api/v1/helpdesk/tickets", headers=other).json() == []
    original = diagnose(client, auth, "VPN 连接失败")
    response = client.post("/api/v1/helpdesk/runs", headers=other, json={"request_id": original["run_id"], "question": original["question"]})
    assert response.status_code == 404
    assert client.patch("/api/v1/helpdesk/tickets/" + original["ticket_id"], headers=other, json={"status": "IN_PROGRESS"}).status_code == 404


def test_ingest_and_retrieve_new_runbook(client, auth):
    book = {"code": "APP-900", "title": "Nebula 软件安装手册", "keywords": "Nebula 软件 安装", "content": "安装 Nebula 软件时，请从批准的软件中心下载 Nebula 安装包。安装完成后检查 Nebula 版本号，失败时提交终端团队工单。"}
    assert client.post("/api/v1/helpdesk/runbooks", headers=auth, json=book).status_code == 201
    assert client.post("/api/v1/helpdesk/runbooks", headers=auth, json=book).status_code == 409
    run = diagnose(client, auth, "Nebula 软件安装后怎么检查 Nebula 版本号？")
    assert run["evidence"][0]["code"] == "APP-900"


def test_credentials_are_redacted_before_persistence(client, auth):
    run = diagnose(client, auth, "账号登录失败，password=secret-password-123，请帮我查")
    assert "secret-password-123" not in __import__('json').dumps(run)
    history = client.get("/api/v1/helpdesk/runs", headers=auth).json()
    assert "secret-password-123" not in __import__('json').dumps(history)


def test_tool_allowlist_rejects_identity_override():
    import asyncio
    from app.helpdesk.tools import execute_tools
    with pytest.raises(ValueError):
        asyncio.run(execute_tools(None, None, "account", [{"name": "get_account_status", "arguments": {"employee": "another-user"}}]))


def test_analytics_counts_completed_and_enforces_scope(client, auth):
    before = client.get("/api/v1/helpdesk/analytics?days=7", headers=auth).json()
    diagnose(client, auth, "如何安装公司批准的办公软件？")
    diagnose(client, auth, "VPN 认证超时请人工处理")
    response = client.get("/api/v1/helpdesk/analytics?days=7", headers=auth)
    assert response.status_code == 200
    after = response.json()
    assert after["total_runs"] == before["total_runs"] + 2
    assert after["completed_runs"] == before["completed_runs"] + 2
    assert after["escalated_runs"] == before["escalated_runs"] + 1
    assert after["escalation_rate"] == round(after["escalated_runs"] / after["completed_runs"], 4)
    assert sum(day["runs"] for day in after["daily"]) == after["total_runs"]
    assert len(after["daily"]) == 7
    assert after["scope"]["runs"] == "current_user"
    assert client.get("/api/v1/helpdesk/analytics").status_code == 401
    for invalid in (0, 91):
        assert client.get(f"/api/v1/helpdesk/analytics?days={invalid}", headers=auth).status_code == 422
    response = client.post("/api/v1/auth/register", json={"email": "metrics@resolveai.example.com", "password": "OtherTenant123!", "full_name": "Metrics owner", "tenant_name": "Metrics", "tenant_slug": "metrics-" + uuid4().hex})
    assert response.status_code == 201
    other = {"Authorization": "Bearer " + response.json()["access_token"]}
    empty = client.get("/api/v1/helpdesk/analytics", headers=other).json()
    assert empty["total_runs"] == 0 and empty["ticket_statuses"] == {}
    assert empty["escalation_rate"] is None and empty["avg_latency_ms"] is None


def test_analytics_timezone_percentile_and_noncompleted_denominator():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from app.helpdesk.analytics import summarize_runs
    now = datetime(2026, 10, 12, 17, tzinfo=timezone.utc)
    rows = [SimpleNamespace(created_at=now, result={"status": "completed", "category": "software", "supported": True, "escalate": False, "latency_ms": value}) for value in range(1, 21)]
    rows += [SimpleNamespace(created_at=now.replace(tzinfo=None), result={"status": "failed"})]
    summary = summarize_runs(rows, 7, now)
    assert summary["daily"][-1]["date"] == "2026-10-13"
    assert summary["daily"][-1]["runs"] == 21
    assert summary["completed_runs"] == 20 and summary["supported_rate"] == 1
    assert summary["avg_latency_ms"] == 10.5 and summary["p95_latency_ms"] == 19
    assert summary["statuses"]["failed"] == 1


def test_ticket_claim_timeline_and_idempotency(client, auth):
    run = diagnose(client, auth, "VPN 认证超时需要人工支持")
    path = "/api/v1/helpdesk/tickets/" + run["ticket_id"]
    initial = client.get(path, headers=auth).json()
    assert initial["ticket"]["assigned_agent_id"] is None
    assert initial["events"][0]["type"] == "created"
    assert initial["ticket"]["sla"]["target_hours"] == 4
    assert client.post(path + "/claim", headers=auth, json={"expected_updated_at": initial["ticket"]["updated_at"]}).status_code == 200
    assigned = client.get(path, headers=auth).json()
    assert assigned["ticket"]["assigned_agent_name"] == "演示支持工程师"
    assert assigned["ticket"]["status"] == "IN_PROGRESS"
    assert [event["type"] for event in assigned["events"]] == ["created", "assigned", "status_changed"]
    assert client.post(path + "/claim", headers=auth, json={}).status_code == 200
    assert client.get(path, headers=auth).json()["event_count"] == 3


def test_ticket_note_idempotency_redaction_and_validation(client, auth):
    run = diagnose(client, auth, "VPN 故障请转人工")
    path = "/api/v1/helpdesk/tickets/" + run["ticket_id"]
    data = {"request_id": str(uuid4()), "note": "检查客户端日志：password=private-example-123，需要用户提供错误截图。"}
    first = client.post(path + "/notes", headers=auth, json=data)
    assert first.status_code == 201 and not first.json()["cached"]
    assert client.post(path + "/notes", headers=auth, json=data).json()["cached"]
    detail = client.get(path, headers=auth).json()
    notes = [event for event in detail["events"] if event["type"] == "note"]
    assert len(notes) == 1 and notes[0]["author"] == "演示支持工程师"
    assert "private-example-123" not in __import__('json').dumps(detail)
    assert client.post(path + "/notes", headers=auth, json={**data, "note": "不同的处理备注"}).status_code == 409
    assert client.post(path + "/notes", headers=auth, json={"request_id": str(uuid4()), "note": "  "}).status_code == 422


def test_ticket_revision_conflict_and_resolution_timestamp(client, auth):
    run = diagnose(client, auth, "VPN 故障请支持工程师处理")
    path = "/api/v1/helpdesk/tickets/" + run["ticket_id"]
    stamp = client.get(path, headers=auth).json()["ticket"]["updated_at"]
    assert client.post(path + "/claim", headers=auth, json={"expected_updated_at": stamp}).status_code == 200
    assert client.patch(path, headers=auth, json={"status": "RESOLVED", "expected_updated_at": stamp}).status_code == 409
    for status in ["WAITING_FOR_CUSTOMER", "IN_PROGRESS", "RESOLVED"]:
        assert client.patch(path, headers=auth, json={"status": status}).status_code == 200
    resolved = client.get(path, headers=auth).json()
    assert client.patch(path, headers=auth, json={"status": "CLOSED"}).status_code == 200
    closed = client.get(path, headers=auth).json()
    assert closed["ticket"]["resolved_at"] == resolved["ticket"]["resolved_at"]
    assert closed["ticket"]["sla"]["state"] == "met"
    before = closed["event_count"]
    assert client.patch(path, headers=auth, json={"status": "CLOSED"}).status_code == 200
    assert client.get(path, headers=auth).json()["event_count"] == before
    assert client.patch(path, headers=auth, json={"status": "IN_PROGRESS"}).status_code == 200
    assert client.get(path, headers=auth).json()["ticket"]["resolved_at"] is None


def test_ticket_detail_notes_claim_are_workspace_isolated(client, auth):
    run = diagnose(client, auth, "VPN 认证故障需要支持")
    path = "/api/v1/helpdesk/tickets/" + run["ticket_id"]
    response = client.post("/api/v1/auth/register", json={"email": "events@resolveai.example.com", "password": "OtherTenant123!", "full_name": "Other event owner", "tenant_name": "Events", "tenant_slug": "events-" + uuid4().hex})
    assert response.status_code == 201
    other = {"Authorization": "Bearer " + response.json()["access_token"]}
    assert client.get(path, headers=other).status_code == 404
    assert client.post(path + "/claim", headers=other, json={}).status_code == 404
    assert client.post(path + "/notes", headers=other, json={"request_id": str(uuid4()), "note": "跨工作区写入"}).status_code == 404
    assert client.get(path).status_code == 401


def test_sla_utc_deadline_boundaries_and_late_completion():
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from app.helpdesk.ticket_ops import sla_snapshot
    from app.models.ticket import TicketPriority, TicketStatus
    created = datetime(2026, 10, 12, 0)  # SQLite's timezone-naive value is UTC.
    item = SimpleNamespace(created_at=created, priority=TicketPriority.HIGH, status=TicketStatus.IN_PROGRESS, resolved_at=None)
    due = created.replace(tzinfo=timezone.utc) + timedelta(hours=4)
    assert sla_snapshot(item, due - timedelta(hours=2))["state"] == "on_track"
    assert sla_snapshot(item, due - timedelta(minutes=30))["state"] == "due_soon"
    assert sla_snapshot(item, due)["state"] == "overdue"
    item.status = TicketStatus.RESOLVED
    item.resolved_at = due
    assert sla_snapshot(item, due + timedelta(days=1))["state"] == "met"
    item.resolved_at = due + timedelta(seconds=1)
    assert sla_snapshot(item)["state"] == "breached"
    item.resolved_at = None
    assert sla_snapshot(item)["state"] == "completed_unknown"


def test_feedback_is_persistent_revisable_and_scoped(client, auth):
    run = diagnose(client, auth, "如何安装公司批准的办公软件？")
    path = "/api/v1/helpdesk/runs/" + run["run_id"] + "/feedback"
    first = client.post(path, headers=auth, json={"helpful": True})
    assert first.status_code == 200
    assert client.post(path, headers=auth, json={"helpful": True}).json() == first.json()
    assert client.post(path, headers=auth, json={"helpful": False}).json()["helpful"] is False
    history = client.get("/api/v1/helpdesk/runs", headers=auth).json()
    recorded = next(row for row in history if row["id"] == run["run_id"])
    assert recorded["result"]["feedback"]["helpful"] is False
    assert recorded["result"]["trace"] == run["trace"]
    metrics = client.get("/api/v1/helpdesk/analytics", headers=auth).json()
    assert metrics["feedback"] == {"helpful": 0, "unhelpful": 1, "responses": 1}
    response = client.post("/api/v1/auth/register", json={"email": "feedback@resolveai.example.com", "password": "OtherTenant123!", "full_name": "Other feedback owner", "tenant_name": "Feedback", "tenant_slug": "feedback-" + uuid4().hex})
    other = {"Authorization": "Bearer " + response.json()["access_token"]}
    assert client.post(path, headers=other, json={"helpful": True}).status_code == 404
    assert client.post(path, json={"helpful": True}).status_code == 401


def test_support_agent_cannot_take_or_change_another_agents_ticket(client, auth):
    from app.core.database import AsyncSessionLocal
    from app.core.security import get_password_hash
    from app.models.user import User, UserRole
    owner = client.get("/api/v1/auth/me", headers=auth).json()
    async def create_agent():
        async with AsyncSessionLocal() as db:
            db.add(User(tenant_id=owner["tenant_id"], email="colleague@resolveai.example.com", full_name="测试支持同事",
                        hashed_password=get_password_hash("Colleague123!"), role=UserRole.SUPPORT_AGENT))
            await db.commit()
    client.portal.call(create_agent)
    login = client.post("/api/v1/auth/login", json={"email": "colleague@resolveai.example.com", "password": "Colleague123!"})
    assert login.status_code == 200
    colleague = {"Authorization": "Bearer " + login.json()["access_token"]}
    run = diagnose(client, auth, "VPN 认证超时需要接手")
    path = "/api/v1/helpdesk/tickets/" + run["ticket_id"]
    assert client.post(path + "/claim", headers=auth, json={}).status_code == 200
    assert client.post(path + "/claim", headers=colleague, json={}).status_code == 409
    assert client.patch(path, headers=colleague, json={"status": "RESOLVED"}).status_code == 403
    legacy = "/api/v1/tickets/" + run["ticket_id"]
    assert client.patch(legacy, headers=colleague, json={"status": "RESOLVED"}).status_code == 409
    assert client.post(legacy + "/notes", headers=auth, json={"note": "未记录的旁路备注"}).status_code == 409
    assert client.get(path, headers=auth).json()["ticket"]["status"] == "IN_PROGRESS"
    assert client.post(path + "/notes", headers=colleague, json={"request_id": str(uuid4()), "note": "同工作区协作备注"}).status_code == 201
    # Same-tenant colleagues also cannot rate the owner's private diagnosis.
    assert client.post("/api/v1/helpdesk/runs/" + run["run_id"] + "/feedback", headers=colleague, json={"helpful": True}).status_code == 404


def test_knowledge_edit_versions_archive_restore_and_snapshot(client, auth):
    initial = next(item for item in client.get("/api/v1/helpdesk/knowledge", headers=auth).json() if item["code"] == "VPN-001")
    before = diagnose(client, auth, "VPN 认证失败怎么排查")
    update = {**initial, "expected_version": initial["version"], "title": "VPN Quasar 专项排查", "content": "Quasar VPN 认证失败时，先核对客户端版本和网关地址，再将 Quasar 错误信息提交网络团队处理。"}
    path = "/api/v1/helpdesk/knowledge/VPN-001"
    changed = client.put(path, headers=auth, json=update)
    assert changed.status_code == 200
    version = changed.json()["version"]
    assert client.put(path, headers=auth, json=update).status_code == 409
    preview = client.post("/api/v1/helpdesk/knowledge/search", headers=auth, json={"query":"Quasar VPN 认证排查"}).json()
    assert preview["results"][0]["title"] == update["title"]
    archived = client.put(path, headers=auth, json={**update, "expected_version": version, "active":False}).json()
    from app.helpdesk.seed import seed_demo
    client.portal.call(seed_demo)
    hits = client.post("/api/v1/helpdesk/knowledge/search", headers=auth, json={"query":"Quasar VPN 认证排查"}).json()["results"]
    assert not any(item["code"] == "VPN-001" for item in hits)
    restored = client.post(path+"/restore",headers=auth,json={"expected_version":archived["version"],"version":0})
    assert restored.status_code == 200 and restored.json()["active"]
    history = client.get(path+"/revisions",headers=auth).json()
    assert [row["version"] for row in history] == [3,2,1,0]
    assert history[-1]["action"] == "legacy_snapshot"
    saved = client.get("/api/v1/helpdesk/runs/"+before["run_id"],headers=auth).json()
    assert saved["result"]["evidence"] == before["evidence"]


def test_knowledge_create_export_and_preview_have_no_run_side_effect(client,auth):
    source={"code":"DNS-210","title":"DNS 终端解析排查","keywords":"DNS 网络 解析","content":"DNS 解析异常时，请先检查终端 DNS 服务器地址，记录解析错误信息，再提交网络支持工单。"}
    source["content"] += "\r\n记录 DNS 检查结果。"
    created=client.post("/api/v1/helpdesk/knowledge",headers=auth,json=source)
    assert created.status_code==201 and created.json()["version"]==1
    assert "\r" not in created.json()["content"]
    assert client.post("/api/v1/helpdesk/knowledge",headers=auth,json=source).status_code==409
    before=client.get("/api/v1/helpdesk/overview",headers=auth).json()
    assert client.post("/api/v1/helpdesk/knowledge/search",headers=auth,json={"query":"DNS 解析异常怎么排查"}).status_code==200
    after=client.get("/api/v1/helpdesk/overview",headers=auth).json()
    assert before["runs"]==after["runs"] and before["open_tickets"]==after["open_tickets"]
    export=client.get("/api/v1/helpdesk/knowledge/export",headers=auth).json()
    assert export["format"]=="resolveai-knowledge-v1"
    assert any(item["code"]==source["code"] for item in export["sources"])
    assert "embedding" not in __import__('json').dumps(export)


def test_knowledge_failure_rolls_back_index_and_version(client,auth,monkeypatch):
    from app.helpdesk import knowledge
    source=next(item for item in client.get("/api/v1/helpdesk/knowledge",headers=auth).json() if item["code"]=="DNS-210")
    async def fail_index(*args,**kwargs): raise RuntimeError("simulated indexing failure")
    monkeypatch.setattr(knowledge,"index_runbook",fail_index)
    with pytest.raises(RuntimeError,match="simulated indexing failure"):
        client.put("/api/v1/helpdesk/knowledge/DNS-210",headers=auth,json={**source,"expected_version":source["version"],"content":source["content"]+" 新检查步骤。"})
    latest=next(item for item in client.get("/api/v1/helpdesk/knowledge",headers=auth).json() if item["code"]==source["code"])
    assert latest["version"]==source["version"] and latest["content"]==source["content"]
    assert any(item["code"]==source["code"] for item in client.get("/api/v1/helpdesk/runbooks",headers=auth).json())


def test_knowledge_permissions_and_tenant_scope(client,auth):
    login=client.post("/api/v1/auth/login",json={"email":"colleague@resolveai.example.com","password":"Colleague123!"})
    colleague={"Authorization":"Bearer "+login.json()["access_token"]}
    source=next(item for item in client.get("/api/v1/helpdesk/knowledge",headers=auth).json() if item["code"]=="DNS-210")
    assert client.put("/api/v1/helpdesk/knowledge/DNS-210",headers=colleague,json={**source,"expected_version":source["version"]}).status_code==403
    assert client.get("/api/v1/helpdesk/knowledge/export",headers=colleague).status_code==403
    response=client.post("/api/v1/auth/register",json={"email":"knowledge@resolveai.example.com","password":"OtherTenant123!","full_name":"Other knowledge owner","tenant_name":"Knowledge","tenant_slug":"knowledge-"+uuid4().hex})
    other={"Authorization":"Bearer "+response.json()["access_token"]}
    assert client.get("/api/v1/helpdesk/knowledge",headers=other).json()==[]
    assert client.get("/api/v1/helpdesk/knowledge/DNS-210/revisions",headers=other).status_code==404
    assert client.get("/api/v1/helpdesk/knowledge").status_code==401


def test_recover_abandoned_run_only_after_deadline_and_only_for_owner(client,auth):
    from datetime import datetime,timedelta,timezone
    from app.core.database import AsyncSessionLocal
    from app.helpdesk.models import HelpdeskRun
    owner=client.get("/api/v1/auth/me",headers=auth).json()
    old_id,fresh_id=str(uuid4()),str(uuid4())
    async def create_runs():
        async with AsyncSessionLocal() as db:
            for identity,age in [(old_id,300),(fresh_id,0)]:
                db.add(HelpdeskRun(id=identity,tenant_id=owner["tenant_id"],user_id=owner["id"],question="测试超时运行恢复",result={"status":"running"},created_at=datetime.now(timezone.utc)-timedelta(seconds=age)))
            await db.commit()
    client.portal.call(create_runs)
    assert client.post("/api/v1/helpdesk/runs/"+fresh_id+"/recover",headers=auth).status_code==409
    response=client.post("/api/v1/helpdesk/runs/"+old_id+"/recover",headers=auth)
    assert response.status_code==200 and response.json()["status"]=="interrupted"
    assert client.post("/api/v1/helpdesk/runs/"+old_id+"/recover",headers=auth).status_code==409
    login=client.post("/api/v1/auth/login",json={"email":"colleague@resolveai.example.com","password":"Colleague123!"})
    colleague={"Authorization":"Bearer "+login.json()["access_token"]}
    assert client.get("/api/v1/helpdesk/runs/"+old_id,headers=colleague).status_code==404
    assert client.post("/api/v1/helpdesk/runs/"+fresh_id+"/recover",headers=colleague).status_code==404
