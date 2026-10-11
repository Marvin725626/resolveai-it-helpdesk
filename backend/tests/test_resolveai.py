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
