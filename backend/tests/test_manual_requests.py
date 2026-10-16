"""Manual requester tickets: isolated SQLite ownership, replay and lifecycle coverage."""
import os
import secrets
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event

_root = Path(tempfile.mkdtemp(prefix="resolveai-manual-requests-"))
os.environ.update({"DATABASE_URL": "sqlite+aiosqlite:///" + (_root / "test.db").as_posix(),
    "IT_ATTACHMENT_ROOT": (_root / "storage").as_posix(), "IT_DEMO_ENABLED": "false",
    "DEFAULT_LLM_PROVIDER": "mock", "IT_EMBEDDING_PROVIDER": "local", "APP_ENV": "development"})
from app.main import app
from app.core.database import engine

@event.listens_for(engine.sync_engine, "connect")
def enable_foreign_keys(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")


def test_manual_ticket_idempotency_privacy_and_helpdesk_lifecycle():
    password = "Manual-" + secrets.token_hex(12) + "Aa1!"
    suffix = uuid4().hex
    with TestClient(app, raise_server_exceptions=False) as client:
        def register(name):
            response = client.post("/api/v1/auth/register", json={"email": f"{name}-{suffix}@example.com",
                "password": password, "full_name": name, "tenant_name": name, "tenant_slug": f"{name}-{suffix}"})
            assert response.status_code == 201, response.text
            return response.json()
        owner, stranger = register("requester"), register("stranger")
        def headers(account): return {"Authorization": "Bearer " + account["access_token"]}
        ho, hx = headers(owner), headers(stranger)
        agent_email = f"agent-{suffix}@example.com"
        invite = client.post("/api/v1/auth/invitations", headers=ho, json={"email": agent_email})
        assert invite.status_code == 201, invite.text
        accepted = client.post("/api/v1/auth/invitations/accept", json={"token": invite.json()["token"],
            "email": agent_email, "password": password, "full_name": "Support"})
        assert accepted.status_code == 200, accepted.text
        hs = headers(accepted.json())

        request = {"request_id": str(uuid4()), "subject": "无法连接办公网络", "category": "network",
            "description": "连接从早上开始失败，password:secret-value，凭据 sk-abcdefghijk。"}
        path = "/api/v1/helpdesk/my-tickets"
        created = client.post(path, headers=ho, json=request)
        assert created.status_code == 201, created.text
        ticket_id = created.json()["ticket_id"]
        replay = client.post(path, headers=ho, json=request)
        assert replay.status_code == 201 and replay.json() == {"ticket_id": ticket_id, "cached": True}
        assert client.post(path, headers=ho, json={**request, "description": "同一个编号不能更换内容"}).status_code == 409
        assert client.post(path, headers=hx, json=request).status_code == 404
        for invalid in ({**request, "priority": "URGENT"}, {**request, "tenant_id": owner["user"]["tenant_id"]},
                        {**request, "status": "CLOSED"}, {**request, "category": "billing"}):
            invalid["request_id"] = str(uuid4())
            assert client.post(path, headers=ho, json=invalid).status_code == 422
        assert client.post(path, headers=ho, json={**request, "request_id": str(uuid4()), "description": "short"}).status_code == 422

        mine = client.get("/api/v1/helpdesk/my-tickets", headers=ho).json()
        assert mine["total"] == 1 and mine["items"][0]["id"] == ticket_id
        assert mine["items"][0]["source"] == "手动报障"
        personal_path = f"/api/v1/helpdesk/my-tickets/{ticket_id}"
        personal = client.get(personal_path, headers=ho)
        assert personal.status_code == 200, personal.text
        assert personal.json()["ticket"]["request"]["category"] == "network"
        assert "secret-value" not in personal.text and "abcdefghijk" not in personal.text
        assert client.get(personal_path, headers=hx).status_code == 404
        assert client.get(personal_path + "/replies", headers=hx).status_code == 404
        assert client.get(f"/api/v1/helpdesk/runs", headers=ho).json() == []
        ops = f"/api/v1/helpdesk/tickets/{ticket_id}"
        assert client.get(ops, headers=ho).json()["ticket"]["source"] == "manual"
        assert client.patch("/api/v1/tickets/" + ticket_id, headers=ho, json={"status": "CLOSED"}).status_code == 409
        assert client.post("/api/v1/tickets/" + ticket_id + "/notes", headers=ho,
            json={"note": "legacy note", "is_internal": True}).status_code == 409

        current = client.get(ops, headers=ho).json()["ticket"]
        upload = client.post(f"/api/v1/helpdesk/my-tickets/{ticket_id}/attachments", headers=ho,
            data={"request_id": str(uuid4()), "expected_updated_at": current["updated_at"]},
            files={"file": ("context.txt", b"wireless network fails", "text/plain")})
        assert upload.status_code == 201, upload.text
        attachment_id = upload.json()["item"]["id"]
        assert client.get(f"/api/v1/helpdesk/my-tickets/{ticket_id}/attachments", headers=ho).json()["items"][0]["id"] == attachment_id

        current = client.get(ops, headers=ho).json()["ticket"]
        assigned = client.post(ops + "/assignment", headers=ho, json={"request_id": str(uuid4()),
            "agent_id": accepted.json()["user"]["id"], "reason": "网络连接问题请检查", "expected_updated_at": current["updated_at"]})
        assert assigned.status_code == 200, assigned.text
        current = client.get(ops, headers=ho).json()["ticket"]
        started = client.patch(ops, headers=hs, json={"status": "IN_PROGRESS", "expected_updated_at": current["updated_at"]})
        assert started.status_code == 200, started.text
        current = client.get(ops, headers=ho).json()["ticket"]
        reply = client.post(f"/api/v1/helpdesk/tickets/{ticket_id}/replies", headers=hs,
            json={"request_id": str(uuid4()), "expected_updated_at": current["updated_at"], "body": "请确认是否仅无线网络受影响。"})
        assert reply.status_code == 201, reply.text
        assert len(client.get(personal_path + "/replies", headers=ho).json()["items"]) == 1
        current = client.get(ops, headers=ho).json()["ticket"]
        resolution_body = {"request_id": str(uuid4()), "expected_updated_at": current["updated_at"],
            "category": "service", "summary": "已恢复网络连接并验证访问正常。", "steps": "修复接入点配置并验证。"}
        resolved = client.post(ops + "/resolve", headers=hs, json=resolution_body)
        assert resolved.status_code == 201, resolved.text
        resolution_id = resolved.json()["resolution"]["id"]
        current = client.get(ops, headers=ho).json()["ticket"]
        closed = client.post(personal_path + "/confirm-resolved", headers=ho,
            json={"request_id": str(uuid4()), "expected_updated_at": current["updated_at"]})
        assert closed.status_code == 200, closed.text
        rating_body = {"request_id": str(uuid4()), "resolution_id": resolution_id, "rating": 5, "comment": "处理清楚"}
        rating = client.post(personal_path + "/satisfaction", headers=ho, json=rating_body)
        assert rating.status_code == 201, rating.text
        notices = client.get("/api/v1/helpdesk/notifications", headers=ho).json()["items"]
        assert any(row["ticket_id"] == ticket_id and row["kind"] == "support_reply" for row in notices)
        assert any(row["ticket_id"] == ticket_id and row["kind"] == "status_changed" for row in notices)
