"""Requester-owned AI escalations and public follow-up lifecycle."""
import os
import secrets
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event

_directory = tempfile.TemporaryDirectory(prefix="resolveai-requester-")
_password = "Follow-" + secrets.token_hex(12) + "aA1!"
os.environ.update({"DATABASE_URL": "sqlite+aiosqlite:///" + (Path(_directory.name) / "test.db").as_posix(),
    "DEFAULT_LLM_PROVIDER": "mock", "IT_EMBEDDING_PROVIDER": "local", "APP_ENV": "development",
    "IT_DEMO_ENABLED": "true", "IT_DEMO_PASSWORD": _password})
from app.main import app
from app.core.database import engine


@event.listens_for(engine.sync_engine, "connect")
def foreign_keys(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")


def test_requester_followup_is_private_idempotent_and_cas_safe():
    suffix = uuid4().hex
    with TestClient(app) as client:
        def register(label, tenant=None):
            response = client.post("/api/v1/auth/register", json={"email": f"{label}-{suffix}@example.com",
                "password": _password, "full_name": label, "tenant_name": tenant or label,
                "tenant_slug": f"{(tenant or label).lower()}-{suffix}"})
            assert response.status_code == 201, response.text
            return response.json()
        owner = register("requester")
        stranger = register("stranger")
        def auth(account): return {"Authorization": "Bearer " + account["access_token"]}
        ho = auth(owner); hs = auth(stranger)
        email = f"support-{suffix}@example.com"
        invited = client.post("/api/v1/auth/invitations", headers=ho, json={"email": email})
        assert invited.status_code == 201, invited.text
        support = client.post("/api/v1/auth/invitations/accept", json={"token": invited.json()["token"],
            "email": email, "password": _password, "full_name": "Support"}).json()
        hsup = auth(support)

        def create_ticket(question):
            result = client.post("/api/v1/helpdesk/runs", headers=ho,
                json={"request_id": str(uuid4()), "question": question})
            assert result.status_code == 200, result.text
            return result.json()["ticket_id"]
        first = create_ticket("VPN 连接失败，请转人工处理")
        assert client.get("/api/v1/helpdesk/my-tickets", headers=ho).json()["total"] == 1
        assert client.get(f"/api/v1/helpdesk/my-tickets/{first}", headers=ho).status_code == 200
        assert client.get(f"/api/v1/helpdesk/my-tickets/{first}", headers=hsup).status_code == 404
        assert client.get(f"/api/v1/helpdesk/my-tickets/{first}/replies", headers=hsup).status_code == 404
        assert client.get(f"/api/v1/helpdesk/my-tickets/{first}", headers=hs).status_code == 404
        assert client.get(f"/api/v1/helpdesk/my-tickets/{first}/replies", headers=hs).status_code == 404
        personal = client.get(f"/api/v1/helpdesk/my-tickets/{first}", headers=ho).json()
        assert "description" not in personal["ticket"] and "reason" not in personal["ticket"]
        assert "tool_data" not in str(personal) and "payload" not in str(personal)

        def ops_ticket():
            return client.get(f"/api/v1/helpdesk/tickets/{first}", headers=ho).json()["ticket"]
        assigned = client.post(f"/api/v1/helpdesk/tickets/{first}/assignment", headers=ho,
            json={"request_id": str(uuid4()), "agent_id": support["user"]["id"], "reason": "接手处理",
                "expected_updated_at": ops_ticket()["updated_at"]})
        assert assigned.status_code == 200, assigned.text
        started = client.patch(f"/api/v1/helpdesk/tickets/{first}", headers=hsup,
            json={"status": "IN_PROGRESS", "expected_updated_at": ops_ticket()["updated_at"]})
        assert started.status_code == 200, started.text
        waiting = client.patch(f"/api/v1/helpdesk/tickets/{first}", headers=hsup,
            json={"status": "WAITING_FOR_CUSTOMER", "expected_updated_at": ops_ticket()["updated_at"]})
        assert waiting.status_code == 200, waiting.text
        # Public support reply; replay remains valid after the requester responds and changes the version.
        reply_body = {"request_id": str(uuid4()), "expected_updated_at": ops_ticket()["updated_at"], "body": "请补充故障开始时间。"}
        posted = client.post(f"/api/v1/helpdesk/tickets/{first}/replies", headers=hsup, json=reply_body)
        assert posted.status_code == 201, posted.text
        thread = client.get(f"/api/v1/helpdesk/tickets/{first}/replies", headers=ho).json()
        assert len(thread["items"]) == 1 and thread["items"][0]["direction"] == "support"
        assert client.get(f"/api/v1/helpdesk/my-tickets/{first}/replies?page_size=51", headers=ho).status_code == 422
        run_owner_notice = client.get("/api/v1/helpdesk/notifications", headers=ho).json()
        assert any(item["kind"] == "support_reply" for item in run_owner_notice["items"])
        assert all("故障开始时间" not in item["text"] for item in run_owner_notice["items"])

        old = ops_ticket()["updated_at"]
        add_body = {"request_id": str(uuid4()), "expected_updated_at": old, "body": "问题从今天上午开始。"}
        added = client.post(f"/api/v1/helpdesk/my-tickets/{first}/replies", headers=ho, json=add_body)
        assert added.status_code == 201, added.text
        events = client.get(f"/api/v1/helpdesk/tickets/{first}/events", headers=ho).json()["events"]
        assert any(row["id"] == add_body["request_id"] for row in events), str(events)
        replayed = client.post(f"/api/v1/helpdesk/my-tickets/{first}/replies", headers=ho, json=add_body)
        assert replayed.status_code == 201, replayed.text
        assert replayed.json()["cached"] is True
        assert replayed.json()["id"] == added.json()["id"]
        assert ops_ticket()["status"] == "IN_PROGRESS"
        support_notices = client.get("/api/v1/helpdesk/notifications", headers=hsup).json()["items"]
        assert sum(item["kind"] == "requester_reply" for item in support_notices) == 1
        stale = client.post(f"/api/v1/helpdesk/my-tickets/{first}/replies", headers=ho,
            json={"request_id": str(uuid4()), "expected_updated_at": old, "body": "另一个补充信息"})
        assert stale.status_code == 409

        resolved = client.post(f"/api/v1/helpdesk/tickets/{first}/resolve", headers=hsup,
            json={"request_id": str(uuid4()), "category": "configuration", "summary": "已修正网络配置并在演示环境完成连接验证。", "steps": "检查网络配置并测试连接。", "expected_updated_at": ops_ticket()["updated_at"]})
        assert resolved.status_code == 201
        confirm_body = {"request_id": str(uuid4()), "expected_updated_at": ops_ticket()["updated_at"]}
        closed = client.post(f"/api/v1/helpdesk/my-tickets/{first}/confirm-resolved", headers=ho, json=confirm_body)
        assert closed.status_code == 200 and closed.json()["status"] == "CLOSED"
        assert client.post(f"/api/v1/helpdesk/my-tickets/{first}/confirm-resolved", headers=ho, json=confirm_body).json()["cached"] is True
        assert client.post(f"/api/v1/helpdesk/my-tickets/{first}/replies", headers=ho, json=add_body).json()["cached"] is True
        assert client.post(f"/api/v1/helpdesk/my-tickets/{first}/replies", headers=ho,
            json={"request_id": str(uuid4()), "expected_updated_at": ops_ticket()["updated_at"], "body": "新信息"}).status_code == 409

        second = create_ticket("VPN 服务仍然不可用，请转人工处理")
        assign2 = client.post(f"/api/v1/helpdesk/tickets/{second}/assignment", headers=ho,
            json={"request_id": str(uuid4()), "agent_id": support["user"]["id"], "reason": "接手处理",
                "expected_updated_at": client.get(f"/api/v1/helpdesk/tickets/{second}", headers=ho).json()["ticket"]["updated_at"]})
        assert assign2.status_code == 200
        start2 = client.patch(f"/api/v1/helpdesk/tickets/{second}", headers=hsup,
            json={"status": "IN_PROGRESS", "expected_updated_at": client.get(f"/api/v1/helpdesk/tickets/{second}", headers=ho).json()["ticket"]["updated_at"]})
        assert start2.status_code == 200
        resolve2 = client.post(f"/api/v1/helpdesk/tickets/{second}/resolve", headers=hsup,
            json={"request_id": str(uuid4()), "category": "service", "summary": "已恢复演示服务并完成可用性检查。", "steps": "检查服务状态和连接。", "expected_updated_at": client.get(f"/api/v1/helpdesk/tickets/{second}", headers=ho).json()["ticket"]["updated_at"]})
        assert resolve2.status_code == 201
        before = client.get(f"/api/v1/helpdesk/tickets/{second}", headers=ho).json()["ticket"]
        reopen_body = {"request_id": str(uuid4()), "expected_updated_at": before["updated_at"], "explanation": "VPN 还是连不上。"}
        reopened = client.post(f"/api/v1/helpdesk/my-tickets/{second}/reopen", headers=ho, json=reopen_body)
        assert reopened.status_code == 200 and reopened.json()["status"] == "IN_PROGRESS"
        after = client.get(f"/api/v1/helpdesk/tickets/{second}", headers=ho).json()["ticket"]
        assert after["resolved_at"] is None and after["created_at"] == before["created_at"]
        visible = client.get(f"/api/v1/helpdesk/tickets/{second}/replies", headers=ho).json()["items"]
        assert visible[-1]["body"] == "VPN 还是连不上。"
        assert client.get(f"/api/v1/helpdesk/my-tickets/{second}", headers=ho).status_code == 200
