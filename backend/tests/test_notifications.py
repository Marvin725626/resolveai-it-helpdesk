"""Notification handoff workflow against an isolated database with foreign keys."""
import os
import secrets
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

_directory = tempfile.TemporaryDirectory(prefix="resolveai-notifications-")
os.environ.update({"DATABASE_URL": "sqlite+aiosqlite:///" + (Path(_directory.name) / "test.db").as_posix(),
    "DEFAULT_LLM_PROVIDER": "mock", "IT_EMBEDDING_PROVIDER": "local", "APP_ENV": "development",
    "IT_DEMO_ENABLED": "true", "IT_DEMO_PASSWORD": "Test-" + secrets.token_hex(16) + "aA1!"})
from app.main import app
from app.core.database import engine

@event.listens_for(engine.sync_engine, "connect")
def foreign_keys(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as value:
        yield value


def test_handoff_notifications_persist_are_private_and_paginate(client):
    password = "Test-" + secrets.token_hex(16) + "aA1!"
    suffix = uuid4().hex
    def register(label):
        response = client.post("/api/v1/auth/register", json={"email": f"{label}-{suffix}@example.com",
            "password": password, "full_name": label, "tenant_name": label, "tenant_slug": f"{label}-{suffix}"})
        assert response.status_code == 201, response.text
        return response.json()
    owner = register("owner")
    stranger = register("stranger")
    def headers(account): return {"Authorization": "Bearer " + account["access_token"]}
    own = headers(owner)
    agents = []
    for label in ("agent-b", "agent-c"):
        email = f"{label}-{suffix}@example.com"
        invitation = client.post("/api/v1/auth/invitations", headers=own, json={"email": email})
        assert invitation.status_code == 201
        accepted = client.post("/api/v1/auth/invitations/accept", json={"token": invitation.json()["token"],
            "email": email, "password": password, "full_name": label})
        assert accepted.status_code == 200
        agents.append(accepted.json())
    b, c = agents
    hb, hc = headers(b), headers(c)
    run = client.post("/api/v1/helpdesk/runs", headers=own, json={"request_id": str(uuid4()), "question": "VPN 连接失败，请转人工处理"})
    assert run.status_code == 200, run.text
    ticket_id = run.json()["ticket_id"]
    def detail(): return client.get(f"/api/v1/helpdesk/tickets/{ticket_id}", headers=own).json()["ticket"]
    def inbox(h, query=""):
        response = client.get("/api/v1/helpdesk/notifications" + query, headers=h)
        assert response.status_code == 200, response.text
        return response.json()
    def assign(target, request=None):
        body = request or {"request_id": str(uuid4()), "agent_id": target, "reason": "private handoff reason",
            "expected_updated_at": detail()["updated_at"]}
        response = client.post(f"/api/v1/helpdesk/tickets/{ticket_id}/assignment", headers=own, json=body)
        assert response.status_code == 200, response.text
        return body, response.json()
    body, first = assign(b["user"]["id"])
    assert first["cached"] is False
    assert assign(None, body)[1]["cached"] is True
    assert inbox(hb)["unread_count"] == 1
    item = inbox(hb)["items"][0]
    assert item["kind"] == "assigned_to_me" and item["ticket_id"] == ticket_id
    assert "private handoff reason" not in str(item) and "VPN" not in item["text"]
    assert inbox(own)["items"] == []
    for h in (own, hc, headers(stranger)):
        assert client.post(f"/api/v1/helpdesk/notifications/{item['id']}/read", headers=h).status_code == 404
    assert inbox(headers(stranger))["items"] == []
    for _ in range(2):
        assert client.post(f"/api/v1/helpdesk/notifications/{item['id']}/read", headers=hb).status_code == 200
    assert inbox(hb)["unread_count"] == 0 and inbox(hb)["items"][0]["read_at"]
    # Login again proves read state belongs to persistent user data, not a token.
    relogin = client.post("/api/v1/auth/login", json={"email": b["user"]["email"], "password": password}).json()
    assert inbox(headers(relogin))["items"][0]["read_at"] == inbox(hb)["items"][0]["read_at"]
    assign(c["user"]["id"])
    assert inbox(hb)["unread_count"] == 1 and inbox(hb)["items"][0]["kind"] == "assignment_removed"
    assert inbox(hc)["unread_count"] == 1
    # A manager updates C's status; C is notified, then C's own update is silent.
    for h, state in ((own, "IN_PROGRESS"), (hc, "WAITING_FOR_CUSTOMER")):
        response = client.patch(f"/api/v1/helpdesk/tickets/{ticket_id}", headers=h,
            json={"status": state, "expected_updated_at": detail()["updated_at"]})
        assert response.status_code == 200, response.text
    assert inbox(hc)["unread_count"] == 2
    # Same state is a no-op and does not create another notification.
    response = client.patch(f"/api/v1/helpdesk/tickets/{ticket_id}", headers=own,
        json={"status": "WAITING_FOR_CUSTOMER", "expected_updated_at": detail()["updated_at"]})
    assert response.status_code == 200 and inbox(hc)["unread_count"] == 2
    assign(None)
    assert inbox(hc)["unread_count"] == 3 and "释放" in inbox(hc)["items"][0]["text"]
    page = inbox(hc, "?page_size=1")
    assert page["has_more"] and len(page["items"]) == 1
    second = inbox(hc, f"?page_size=1&before={page['next_before']}")
    assert second["items"][0]["id"] != page["items"][0]["id"]
    assert client.post("/api/v1/helpdesk/notifications/read-all", headers=hc).status_code == 200
    assert inbox(hc, "?unread_only=true")["items"] == []
    assert inbox(hb)["unread_count"] == 1
    # Earlier requester reminders are valid; self-operations must not add another.
    own_unread_before = inbox(own)["unread_count"]
    assign(owner["user"]["id"])
    response = client.patch(f"/api/v1/helpdesk/tickets/{ticket_id}", headers=own,
        json={"status": "IN_PROGRESS", "expected_updated_at": detail()["updated_at"]})
    assert response.status_code == 200 and inbox(own)["unread_count"] == own_unread_before
    assert client.get("/api/v1/helpdesk/notifications?page_size=51", headers=own).status_code == 422
    assert client.get("/api/v1/helpdesk/notifications").status_code == 401
