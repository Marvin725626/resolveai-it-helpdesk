"""Exact-scope and window tests for tenant-wide operational metrics."""
import os
import secrets
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

_directory = tempfile.TemporaryDirectory(prefix="resolveai-team-metrics-")
_db_path = Path(_directory.name) / "metrics.db"
_password = "Metrics-" + secrets.token_hex(10) + "aA1!"
os.environ.update({"DATABASE_URL": "sqlite+aiosqlite:///" + _db_path.as_posix(), "DEFAULT_LLM_PROVIDER": "mock",
    "IT_EMBEDDING_PROVIDER": "local", "APP_ENV": "development", "IT_DEMO_ENABLED": "true",
    "IT_DEMO_PASSWORD": _password})
from app.main import app
import app.helpdesk.team_metrics_api as metrics_api


def test_team_metrics_are_tenant_scoped_and_use_distinct_utc_windows(monkeypatch):
    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    start = now - timedelta(days=7)
    monkeypatch.setattr(metrics_api, "utc_now", lambda: now)
    suffix = uuid4().hex
    with TestClient(app) as client:
        def register(name):
            result = client.post("/api/v1/auth/register", json={"email": f"{name}-{suffix}@example.com",
                "password": _password, "full_name": name, "tenant_name": name,
                "tenant_slug": f"{name}-{suffix}"})
            assert result.status_code == 201, result.text
            value = result.json()
            return value, {"Authorization": "Bearer " + value["access_token"]}
        owner, owner_h = register("owner")
        outsider, outsider_h = register("outsider")
        invited = client.post("/api/v1/auth/invitations", headers=owner_h,
            json={"email": f"inactive-{suffix}@example.com"})
        assert invited.status_code == 201, invited.text
        accepted = client.post("/api/v1/auth/invitations/accept", json={"token": invited.json()["token"],
            "email": f"inactive-{suffix}@example.com", "password": _password, "full_name": "历史成员"})
        assert accepted.status_code == 200, accepted.text
        inactive_id = accepted.json()["user"]["id"]
        ticket_ids = []
        for index in range(6):
            run = client.post("/api/v1/helpdesk/runs", headers=owner_h, json={"request_id": str(uuid4()),
                "question": f"VPN连接故障需要人工支持样本 {index}"})
            assert run.status_code == 200, run.text
            ticket_ids.append(run.json()["ticket_id"])
        other_run = client.post("/api/v1/helpdesk/runs", headers=outsider_h, json={"request_id": str(uuid4()),
            "question": "VPN连接故障需要人工支持另一个租户"})
        assert other_run.status_code == 200, other_run.text
        other_ticket = other_run.json()["ticket_id"]

        def sql_time(value):
            return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
        connection = sqlite3.connect(_db_path)
        try:
            connection.execute("UPDATE users SET is_active=0 WHERE id=?", (inactive_id,))
            states = [
                ("IN_PROGRESS", "HIGH", now - timedelta(hours=3, minutes=30), inactive_id),
                ("WAITING_FOR_CUSTOMER", "LOW", now - timedelta(minutes=5), None),
                ("OPEN", "URGENT", now - timedelta(hours=1, minutes=10), inactive_id),
                ("RESOLVED", "MEDIUM", now - timedelta(days=10), inactive_id),
                ("RESOLVED", "LOW", now - timedelta(days=2), None),
                ("RESOLVED", "MEDIUM", now - timedelta(days=12), None),
            ]
            for ticket_id, (status, priority, created, assignee) in zip(ticket_ids, states):
                connection.execute("UPDATE tickets SET status=?,priority=?,created_at=?,assigned_agent_id=?,resolved_at=? WHERE id=?",
                    (status, priority, sql_time(created), assignee, sql_time(now - timedelta(days=1)) if status == "RESOLVED" else None, ticket_id))
            connection.execute("UPDATE tickets SET status='RESOLVED', resolved_at=? WHERE id=?",
                (sql_time(now - timedelta(days=1)), other_ticket))
            resolutions = [
                (ticket_ids[3], now - timedelta(days=3), "service"),
                (ticket_ids[3], now - timedelta(days=1), "configuration"),
                (ticket_ids[4], start, "software"),
                (ticket_ids[5], start - timedelta(microseconds=1), "other"),
                (other_ticket, now - timedelta(days=1), "account_access"),
            ]
            resolution_ids = []
            for ticket_id, resolved_at, category in resolutions:
                resolution_id, request_id = str(uuid4()), str(uuid4())
                resolution_ids.append((resolution_id, ticket_id))
                connection.execute("INSERT INTO resolveai_ticket_resolutions (id,request_id,tenant_id,ticket_id,category,summary,steps,author_id,author_name,expected_updated_at,resolved_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (resolution_id, request_id, owner["user"]["tenant_id"] if ticket_id != other_ticket else outsider["user"]["tenant_id"], ticket_id, category, "公开摘要", "公开步骤", owner["user"]["id"], "owner", sql_time(now), sql_time(resolved_at), sql_time(resolved_at)))
            for resolution_id, ticket_id, rating_at, rating in [
                (resolution_ids[0][0], ticket_ids[3], start, 4),
                (resolution_ids[1][0], ticket_ids[3], now, 5),
                (resolution_ids[2][0], ticket_ids[4], start - timedelta(microseconds=1), 1),
            ]:
                connection.execute("INSERT INTO resolveai_resolution_satisfaction (id,request_id,resolution_id,tenant_id,ticket_id,user_id,rating,comment,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (str(uuid4()), str(uuid4()), resolution_id, owner["user"]["tenant_id"] if ticket_id != other_ticket else outsider["user"]["tenant_id"], ticket_id, owner["user"]["id"], rating, "PRIVATE COMMENT MUST NOT APPEAR", sql_time(rating_at)))
            connection.commit()
        finally:
            connection.close()

        response = client.get("/api/v1/helpdesk/team-metrics?days=7", headers=owner_h)
        assert response.status_code == 200, response.text
        result = response.json()
        snapshot = result["snapshot"]
        assert snapshot["current_backlog"] == 3
        assert snapshot["statuses"]["RESOLVED"] == 3
        assert snapshot["priorities"]["HIGH"] == 1 and snapshot["priorities"]["URGENT"] == 1
        assert snapshot["unassigned"] == 1 and snapshot["due_soon"] == 1 and snapshot["overdue"] == 1
        inactive_work = next(row for row in snapshot["active_workload"] if row["assignee_id"] == inactive_id)
        assert inactive_work["assignee_name"] == "历史成员" and inactive_work["count"] == 2
        assert result["resolution_window"]["rounds"] == 3
        assert result["resolution_window"]["distinct_resolved_tickets"] == 2
        assert result["resolution_window"]["categories"] == {"service": 1, "configuration": 1, "software": 1}
        ratings = result["rating_window"]
        assert ratings["rating_count"] == 2 and ratings["average_rating"] == 4.5
        assert ratings["distribution"] == {"1": 0, "2": 0, "3": 0, "4": 1, "5": 1}
        assert "PRIVATE COMMENT" not in response.text and "@example.com" not in response.text
        assert client.get("/api/v1/helpdesk/team-metrics?days=14", headers=owner_h).status_code == 422
        empty = client.get("/api/v1/helpdesk/team-metrics?days=7", headers=outsider_h).json()
        assert empty["snapshot"]["current_backlog"] == 0
        assert empty["resolution_window"]["rounds"] == 1
        assert empty["rating_window"]["rating_count"] == 0 and empty["rating_window"]["average_rating"] is None
        connection = sqlite3.connect(_db_path)
        try:
            connection.execute("UPDATE users SET role='PLATFORM_ADMIN' WHERE id=?", (outsider["user"]["id"],))
            connection.commit()
        finally:
            connection.close()
        platform_login = client.post("/api/v1/auth/login", json={"email": outsider["user"]["email"], "password": _password})
        assert platform_login.status_code == 200, platform_login.text
        platform_h = {"Authorization": "Bearer " + platform_login.json()["access_token"]}
        assert client.get("/api/v1/helpdesk/team-metrics?days=7", headers=platform_h).status_code == 403
