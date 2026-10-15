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
os.environ["IT_DEMO_PASSWORD"] = "ResolveAI-Test-Only-123!"

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def auth(client):
    response = client.post("/api/v1/auth/login", json={"email": "demo@resolveai.example.com", "password": os.environ["IT_DEMO_PASSWORD"]})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def diagnose(client, auth, question, identity=None):
    response = client.post("/api/v1/helpdesk/runs", headers=auth, json={"request_id": identity or str(uuid4()), "question": question})
    assert response.status_code == 200, response.text
    return response.json()



def resolve_ticket(client, auth, path, expected=None):
    stamp = expected or client.get(path, headers=auth).json()["ticket"]["updated_at"]
    return client.post(path + "/resolve", headers=auth, json={
        "request_id": str(uuid4()), "expected_updated_at": stamp,
        "category": "configuration", "summary": "已调整演示网络配置并验证连接恢复。", "steps": "检查配置并完成连接验证。"})


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
        response = resolve_ticket(client, auth, path) if status == "RESOLVED" else client.patch(path, headers=auth, json={"status": status})
        assert response.status_code == (201 if status == "RESOLVED" else 200)
        assert client.get(path, headers=auth).json()["ticket"]["status"] == status


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
    assert resolve_ticket(client, auth, path, stamp).status_code == 409
    for status in ["WAITING_FOR_CUSTOMER", "IN_PROGRESS", "RESOLVED"]:
        assert (resolve_ticket(client, auth, path) if status == "RESOLVED" else client.patch(path, headers=auth, json={"status": status})).status_code == (201 if status == "RESOLVED" else 200)
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
    assert resolve_ticket(client, colleague, path).status_code == 403
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


def test_database_queue_pagination_literal_search_assignment_and_export_limit(client,auth):
    from datetime import datetime,timedelta,timezone
    from app.core.database import AsyncSessionLocal
    from app.models.ticket import Ticket,TicketPriority,TicketStatus
    seed=diagnose(client,auth,"VPN 认证超时需要支持")
    owner=client.get("/api/v1/auth/me",headers=auth).json()
    prefix="BULK-"+uuid4().hex
    async def seed_rows():
        async with AsyncSessionLocal() as db:
            template=await db.get(Ticket,seed["ticket_id"])
            now=datetime.now(timezone.utc)
            db.add_all([Ticket(tenant_id=owner["tenant_id"],customer_id=template.customer_id,
                subject=f"{prefix} isolated item {index}"+(" literal%_token" if index==0 else ""),description="isolated pagination fixture",
                priority=TicketPriority.MEDIUM,status=TicketStatus.OPEN,assigned_agent_id=owner["id"] if index%2==0 else None,
                created_at=now-timedelta(seconds=index)) for index in range(1005)])
            await db.commit()
    client.portal.call(seed_rows)
    first=client.get("/api/v1/helpdesk/ticket-queue",headers=auth,params={"q":prefix,"page_size":50}).json()
    second=client.get("/api/v1/helpdesk/ticket-queue",headers=auth,params={"q":prefix,"page_size":50,"page":2}).json()
    assert first["total"]==1005 and len(first["items"])==50
    assert "description" not in first["items"][0]
    assert not ({item["id"] for item in first["items"]}&{item["id"] for item in second["items"]})
    mine=client.get("/api/v1/helpdesk/ticket-queue",headers=auth,params={"q":prefix,"assignment":"mine"}).json()
    unassigned=client.get("/api/v1/helpdesk/ticket-queue",headers=auth,params={"q":prefix,"assignment":"unassigned"}).json()
    assert mine["total"]==503 and unassigned["total"]==502
    literal=client.get("/api/v1/helpdesk/ticket-queue",headers=auth,params={"q":"%_"}).json()
    assert literal["total"]==1
    exported=client.get("/api/v1/helpdesk/ticket-queue/export",headers=auth,params={"q":prefix}).json()
    assert len(exported["items"])==1000 and exported["total"]==1005 and exported["truncated"]
    assert "description" not in exported["items"][0]
    for params in ({"page":0},{"page_size":101},{"status":"BOGUS"},{"assignment":"other"}):
        assert client.get("/api/v1/helpdesk/ticket-queue",headers=auth,params=params).status_code==422


def test_queue_sla_filters_are_database_scoped_and_exclude_completed(client,auth):
    from datetime import datetime,timedelta,timezone
    from app.core.database import AsyncSessionLocal
    from app.models.ticket import Ticket,TicketPriority,TicketStatus
    run=diagnose(client,auth,"VPN 认证失败需要帮助")
    owner=client.get("/api/v1/auth/me",headers=auth).json();prefix="SLA-"+uuid4().hex
    async def seed_rows():
        async with AsyncSessionLocal() as db:
            template=await db.get(Ticket,run["ticket_id"]);now=datetime.now(timezone.utc)
            for label,age,status in [("late",5,TicketStatus.OPEN),("near",3.5,TicketStatus.IN_PROGRESS),("fresh",1,TicketStatus.ESCALATED),("done",6,TicketStatus.RESOLVED)]:
                db.add(Ticket(tenant_id=owner["tenant_id"],customer_id=template.customer_id,subject=prefix+label,description="isolated SLA fixture",priority=TicketPriority.HIGH,status=status,created_at=now-timedelta(hours=age),resolved_at=now if status==TicketStatus.RESOLVED else None))
            await db.commit()
    client.portal.call(seed_rows)
    for state,label in [("overdue","late"),("due_soon","near"),("on_track","fresh")]:
        page=client.get("/api/v1/helpdesk/ticket-queue",headers=auth,params={"q":prefix,"sla":state}).json()
        assert page["total"]==1 and page["items"][0]["subject"].endswith(label)
        assert page["items"][0]["sla"]["state"]==state


def test_run_history_paginates_stably_and_loads_details_on_demand(client,auth):
    from datetime import datetime,timedelta,timezone
    from app.core.database import AsyncSessionLocal
    from app.helpdesk.models import HelpdeskRun
    owner=client.get("/api/v1/auth/me",headers=auth).json();prefix="HISTORY-"+uuid4().hex
    identities=[str(uuid4()) for _ in range(55)]
    async def seed_rows():
        async with AsyncSessionLocal() as db:
            stamp=datetime.now(timezone.utc)
            for index,identity in enumerate(identities):
                db.add(HelpdeskRun(id=identity,tenant_id=owner["tenant_id"],user_id=owner["id"],question=prefix+str(index),created_at=stamp,
                    result={"run_id":identity,"status":"completed" if index%2==0 else "failed","category":"software" if index%2==0 else "account","trace":[{"node":"fixture"}],"answer":"isolated fixture answer"}))
            db.add(HelpdeskRun(id=str(uuid4()),tenant_id=owner["tenant_id"],user_id=owner["id"],question=prefix+"old",created_at=stamp-timedelta(days=60),result={"status":"completed","category":"software"}))
            await db.commit()
    client.portal.call(seed_rows)
    page=client.get("/api/v1/helpdesk/run-history",headers=auth,params={"q":prefix,"days":7,"page_size":10}).json()
    assert page["total"]==55 and [row["id"] for row in page["items"]]==sorted(identities,reverse=True)[:10]
    assert "trace" not in page["items"][0]["result"]
    filtered=client.get("/api/v1/helpdesk/run-history",headers=auth,params={"q":prefix,"days":7,"status":"completed","category":"software"}).json()
    assert filtered["total"]==28
    detail=client.get("/api/v1/helpdesk/runs/"+page["items"][0]["id"],headers=auth).json()
    assert detail["result"]["trace"]==[{"node":"fixture"}]
    assert client.get("/api/v1/helpdesk/run-history",headers=auth,params={"q":prefix}).json()["total"]==56
    assert client.get("/api/v1/helpdesk/run-history",headers=auth,params={"days":0}).status_code==422


def test_paged_endpoints_preserve_identity_and_tenant_boundaries(client,auth):
    response=client.post("/api/v1/auth/register",json={"email":"paged@resolveai.example.com","password":"OtherTenant123!","full_name":"Paged owner","tenant_name":"Paged","tenant_slug":"paged-"+uuid4().hex})
    other={"Authorization":"Bearer "+response.json()["access_token"]}
    for path in ["/ticket-queue","/ticket-queue/export","/run-history"]:
        assert client.get("/api/v1/helpdesk"+path,headers=other).json()["total"]==0
        assert client.get("/api/v1/helpdesk"+path).status_code==401
    login=client.post("/api/v1/auth/login",json={"email":"colleague@resolveai.example.com","password":"Colleague123!"})
    colleague={"Authorization":"Bearer "+login.json()["access_token"]}
    assert client.get("/api/v1/helpdesk/run-history",headers=colleague).json()["total"]==0


def test_readiness_reports_actual_queries_and_never_returns_key(client,auth,monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings,"OPENAI_API_KEY","sk-test-private-placeholder")
    checks=client.get("/api/v1/helpdesk/readiness",headers=auth).json()
    assert checks["database"]["connected"] and checks["configuration"]["model_key_configured"]
    assert checks["external_model_connectivity"]=="not_checked" and checks["enterprise_tools"]=="simulated"
    assert "sk-test-private-placeholder" not in __import__('json').dumps(checks)
    monkeypatch.setattr(settings,"DEFAULT_LLM_PROVIDER","openai");monkeypatch.setattr(settings,"OPENAI_API_KEY","")
    checks=client.get("/api/v1/helpdesk/readiness",headers=auth).json()
    assert any("API Key" in warning for warning in checks["warnings"])
    assert client.get("/api/v1/helpdesk/readiness").status_code==401


def test_bundled_evaluation_is_not_workspace_user_data(client,auth):
    response=client.get("/api/v1/helpdesk/evaluation-report",headers=auth)
    assert response.status_code==200
    data=response.json()
    assert data["source"]=="bundled_offline_fixture_report"
    assert data["report"]["real_model_calls"] is False and data["report"]["case_count"]==16
    assert all("run_id" not in item for item in data["report"]["cases"])
    assert client.get("/api/v1/helpdesk/evaluation-report").status_code==401


def test_sqlite_backup_preserves_data_and_refuses_overwrite_or_outside_path(tmp_path):
    import importlib.util
    import sqlite3
    source_path=Path(__file__).resolve().parents[2]/"scripts/backup_sqlite.py"
    spec=importlib.util.spec_from_file_location("resolveai_backup",source_path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    original=tmp_path/"source.db";snapshot=tmp_path/"private/backup.sqlite3"
    with sqlite3.connect(original) as db:
        db.execute("CREATE TABLE fixtures (name TEXT)");db.execute("INSERT INTO fixtures VALUES (?)",("isolated fixture",))
    result=module.backup_database(original,snapshot,tmp_path)
    assert result["quick_check"]=="ok" and result["bytes"]>0
    with sqlite3.connect(snapshot) as db:assert db.execute("SELECT name FROM fixtures").fetchone()[0]=="isolated fixture"
    with pytest.raises(FileExistsError):module.backup_database(original,snapshot,tmp_path)
    with pytest.raises(ValueError):module.backup_database(original,original,tmp_path)
    with pytest.raises(ValueError):module.backup_database(original,tmp_path.parent/"outside.sqlite3",tmp_path)
    with sqlite3.connect(original) as db:assert db.execute("SELECT COUNT(*) FROM fixtures").fetchone()[0]==1


def add_support_member(client, auth):
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.models.user import User, UserRole
    owner = client.get("/api/v1/auth/me", headers=auth).json()
    identity = str(uuid4())
    async def insert_member():
        async with AsyncSessionLocal() as db:
            db.add(User(id=identity, tenant_id=owner["tenant_id"], email=f"support-{identity}@example.com",
                hashed_password="unused-by-this-fixture", full_name="Isolated support fixture", role=UserRole.SUPPORT_AGENT, is_active=True))
            await db.commit()
    client.portal.call(insert_member)
    token = create_access_token(subject=identity, tenant_id=owner["tenant_id"], role=UserRole.SUPPORT_AGENT.value)
    return identity, {"Authorization": "Bearer " + token}


def clear_test_rate_limit(client):
    layer = client.app.middleware_stack
    while layer is not None:
        if layer.__class__.__name__ == "RateLimitMiddleware":
            layer.request_history.clear()
            layer.auth_history.clear()
            return
        layer = getattr(layer, "app", None)


def test_assignment_is_idempotent_and_preserves_ticket_state(client, auth):
    run = diagnose(client, auth, "VPN 认证超时需要管理员转交")
    path = "/api/v1/helpdesk/tickets/" + run["ticket_id"]
    before = client.get(path, headers=auth).json()
    identity = str(uuid4())
    request = {"request_id": identity, "agent_id": before["ticket"]["assigned_agent_id"] or client.get("/api/v1/auth/me", headers=auth).json()["id"],
               "reason": "由管理员安排专人跟进 password=secret-fixture-4932", "expected_updated_at": before["ticket"]["updated_at"]}
    first = client.post(path + "/assignment", headers=auth, json=request)
    assert first.status_code == 200 and first.json()["cached"] is False
    # A lost response can be retried after later mutations; idempotency is checked first.
    assert client.post(path + "/assignment", headers=auth, json=request).json()["cached"] is True
    assert client.post(path + "/assignment", headers=auth, json={**request, "reason": "另一项交接"}).status_code == 409
    assigned = client.get(path, headers=auth).json()
    assert assigned["ticket"]["status"] == before["ticket"]["status"]
    assert assigned["ticket"]["sla"]["due_at"] == before["ticket"]["sla"]["due_at"]
    changed = next(event for event in assigned["events"] if event["type"] == "assignment_changed")
    assert changed["payload"]["reason"] == "由管理员安排专人跟进 password=[已脱敏]"
    assert "secret-fixture-4932" not in str(changed["payload"])
    noop = {**request, "request_id": str(uuid4()), "expected_updated_at": assigned["ticket"]["updated_at"]}
    assert client.post(path + "/assignment", headers=auth, json=noop).status_code == 409
    release = {"request_id": str(uuid4()), "agent_id": None, "reason": "暂时释放以重新分配", "expected_updated_at": assigned["ticket"]["updated_at"]}
    released = client.post(path + "/assignment", headers=auth, json=release)
    assert released.status_code == 200
    after = client.get(path, headers=auth).json()
    assert after["ticket"]["assigned_agent_id"] is None
    assert after["ticket"]["status"] == before["ticket"]["status"]
    assert sum(event["type"] == "assignment_changed" for event in after["events"]) == 2
    assert client.post(path + "/assignment", headers=auth, json=request).json()["cached"] is True
    assert client.get(path, headers=auth).json()["ticket"]["assigned_agent_id"] is None


def test_assignment_scope_permissions_and_active_roster(client, auth):
    run = diagnose(client, auth, "VPN 连不上需要工作区支持人员处理")
    ticket_path = "/api/v1/helpdesk/tickets/" + run["ticket_id"]
    ticket = client.get(ticket_path, headers=auth).json()["ticket"]
    owner = client.get("/api/v1/auth/me", headers=auth).json()
    listed = client.get("/api/v1/helpdesk/assignees", headers=auth)
    assert listed.status_code == 200 and len(listed.json()["items"]) <= 50
    assert all(item["id"] == owner["id"] or item["role"] in ("TENANT_OWNER", "TENANT_ADMIN", "SUPPORT_AGENT") for item in listed.json()["items"])
    other = client.post("/api/v1/auth/register", json={"email": "assign-" + uuid4().hex + "@example.com", "password": "OtherTenant123!", "full_name": "Other workspace", "tenant_name": "Other", "tenant_slug": "assign-" + uuid4().hex})
    assert other.status_code == 201
    outsider_id = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + other.json()["access_token"]}).json()["id"]
    request = {"request_id": str(uuid4()), "agent_id": outsider_id, "reason": "不允许跨工作区", "expected_updated_at": ticket["updated_at"]}
    assert client.post(ticket_path + "/assignment", headers=auth, json=request).status_code == 404
    _, agent_auth = add_support_member(client, auth)
    assert client.get("/api/v1/helpdesk/assignees", headers=agent_auth).status_code == 403
    assert client.post(ticket_path + "/assignment", headers=agent_auth, json=request).status_code == 403
    assert client.post(ticket_path + "/assignment", headers={"Authorization": "Bearer " + other.json()["access_token"]}, json=request).status_code == 404
    assert client.get("/api/v1/helpdesk/assignees").status_code == 401


def test_event_history_cursor_traverses_more_than_two_hundred_stably(client, auth):
    clear_test_rate_limit(client)
    from app.core.database import AsyncSessionLocal
    from app.helpdesk.models import HelpdeskTicketEvent
    run = diagnose(client, auth, "网络问题需要支持，请查看历史记录")
    ticket_id = run["ticket_id"]
    owner = client.get("/api/v1/auth/me", headers=auth).json()
    async def seed_events():
        async with AsyncSessionLocal() as db:
            ticket = await db.get(__import__("app.models.ticket", fromlist=["Ticket"]).Ticket, ticket_id)
            stamp = ticket.created_at
            for index in range(237):
                db.add(HelpdeskTicketEvent(id=str(uuid4()), tenant_id=owner["tenant_id"], ticket_id=ticket_id,
                    author_id=owner["id"], author_name="Cursor fixture", event_type="note", payload={"text": f"isolated {index}"}, created_at=stamp))
            await db.commit()
            rows = (await db.scalars(select(HelpdeskTicketEvent).where(HelpdeskTicketEvent.ticket_id == ticket_id).order_by(HelpdeskTicketEvent.sequence))).all()
            return [row.id for row in rows]
    from sqlalchemy import select
    expected_ids = client.portal.call(seed_events)
    path = f"/api/v1/helpdesk/tickets/{ticket_id}"
    first = client.get(path, headers=auth).json()
    assert first["event_count"] == 238 and len(first["events"]) == 100 and first["has_more"]
    assert first["next_before"] is not None
    async def insert_newer():
        async with AsyncSessionLocal() as db:
            db.add(HelpdeskTicketEvent(id=str(uuid4()), tenant_id=owner["tenant_id"], ticket_id=ticket_id,
                author_id=owner["id"], author_name="Cursor fixture", event_type="note", payload={"text": "inserted after page one"}))
            await db.commit()
    client.portal.call(insert_newer)
    seen = [event["id"] for event in first["events"]]
    cursor = first["next_before"]
    while cursor is not None:
        page = client.get(path + "/events", headers=auth, params={"before": cursor, "page_size": 50})
        assert page.status_code == 200
        value = page.json()
        seen = [event["id"] for event in value["events"]] + seen
        cursor = value["next_before"]
        assert value["has_more"] == (cursor is not None)
    assert seen == expected_ids
    assert client.get(path + "/events", headers=auth, params={"before": 0}).status_code == 422
    assert client.get(path + "/events", headers=auth, params={"page_size": 101}).status_code == 422


def test_assignment_stale_revision_finished_ticket_and_request_validation(client, auth):
    clear_test_rate_limit(client)
    run = diagnose(client, auth, "VPN 超时需要管理员分派支持")
    path = "/api/v1/helpdesk/tickets/" + run["ticket_id"]
    initial = client.get(path, headers=auth).json()
    target_id, _ = add_support_member(client, auth)
    base = {"request_id": str(uuid4()), "agent_id": target_id, "reason": "管理员安排专人排查", "expected_updated_at": initial["ticket"]["updated_at"]}
    assert client.post(path + "/assignment", headers=auth, json={**base, "reason": " "}).status_code == 422
    assert client.post(path + "/assignment", headers=auth, json={k: v for k, v in base.items() if k != "expected_updated_at"}).status_code == 422
    assert client.patch(path, headers=auth, json={"status": "IN_PROGRESS", "expected_updated_at": initial["ticket"]["updated_at"]}).status_code == 200
    stale = client.post(path + "/assignment", headers=auth, json=base)
    assert stale.status_code == 409
    detail = client.get(path, headers=auth).json()
    assert detail["ticket"]["assigned_agent_id"] == client.get("/api/v1/auth/me", headers=auth).json()["id"]
    assert not any(event["type"] == "assignment_changed" for event in detail["events"])
    assert resolve_ticket(client, auth, path).status_code == 201
    current = client.get(path, headers=auth).json()["ticket"]
    finished = {**base, "request_id": str(uuid4()), "expected_updated_at": current["updated_at"]}
    assert client.post(path + "/assignment", headers=auth, json=finished).status_code == 409


def test_assignment_rejects_inactive_same_workspace_target(client, auth):
    clear_test_rate_limit(client)
    from app.core.database import AsyncSessionLocal
    from app.models.user import User
    run = diagnose(client, auth, "VPN 连不上，提示认证超时，转人工排查")
    path = "/api/v1/helpdesk/tickets/" + run["ticket_id"]
    stamp = client.get(path, headers=auth).json()["ticket"]["updated_at"]
    colleague_id, _ = add_support_member(client, auth)
    async def deactivate():
        async with AsyncSessionLocal() as db:
            user = await db.get(User, colleague_id)
            user.is_active = False
            await db.commit()
    client.portal.call(deactivate)
    request = {"request_id": str(uuid4()), "agent_id": colleague_id, "reason": "分派给指定支持人员", "expected_updated_at": stamp}
    assert client.post(path + "/assignment", headers=auth, json=request).status_code == 404
    assert all(row["id"] != colleague_id for row in client.get("/api/v1/helpdesk/assignees", headers=auth).json()["items"])
