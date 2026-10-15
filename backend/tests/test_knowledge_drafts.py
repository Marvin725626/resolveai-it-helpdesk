"""Focused isolation and atomic-publish coverage for resolution-derived knowledge drafts."""
import os
import secrets
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

_directory = tempfile.TemporaryDirectory(prefix="resolveai-drafts-")
_password = "Draft-" + secrets.token_hex(10) + "aA1!"
os.environ.update({"DATABASE_URL": "sqlite+aiosqlite:///" + (Path(_directory.name) / "test.db").as_posix(),
    "DEFAULT_LLM_PROVIDER": "mock", "IT_EMBEDDING_PROVIDER": "local", "APP_ENV": "development",
    "IT_DEMO_ENABLED": "true", "IT_DEMO_PASSWORD": _password})
from app.main import app


def test_knowledge_draft_scope_publish_and_replay(monkeypatch):
    suffix = uuid4().hex
    with TestClient(app, raise_server_exceptions=False) as client:
        def register(name, tenant=None):
            result = client.post("/api/v1/auth/register", json={"email": f"{name}-{suffix}@example.com",
                "password": _password, "full_name": name, "tenant_name": tenant or name,
                "tenant_slug": f"{(tenant or name).lower()}-{suffix}"})
            assert result.status_code == 201, result.text
            return result.json()
        owner = register("owner")
        owner_h = {"Authorization": "Bearer " + owner["access_token"]}
        other_tenant = register("outsider")
        outsider_h = {"Authorization": "Bearer " + other_tenant["access_token"]}
        def invite(name):
            email = f"{name}-{suffix}@example.com"
            invitation = client.post("/api/v1/auth/invitations", headers=owner_h, json={"email": email})
            assert invitation.status_code == 201, invitation.text
            accepted = client.post("/api/v1/auth/invitations/accept", json={"token": invitation.json()["token"],
                "email": email, "password": _password, "full_name": name})
            assert accepted.status_code == 200, accepted.text
            return accepted.json()
        agent, coworker = invite("agent"), invite("coworker")
        agent_h = {"Authorization": "Bearer " + agent["access_token"]}
        coworker_h = {"Authorization": "Bearer " + coworker["access_token"]}

        run = client.post("/api/v1/helpdesk/runs", headers=owner_h, json={"request_id": str(uuid4()),
            "question": "VPN认证连续失败，请转人工处理"})
        assert run.status_code == 200, run.text
        ticket_id = run.json()["ticket_id"]
        ticket_path = f"/api/v1/helpdesk/tickets/{ticket_id}"
        ticket = client.get(ticket_path, headers=owner_h).json()["ticket"]
        assigned = client.post(ticket_path + "/assignment", headers=owner_h, json={"request_id": str(uuid4()),
            "agent_id": agent["user"]["id"], "reason": "接手处理", "expected_updated_at": ticket["updated_at"]})
        assert assigned.status_code == 200, assigned.text
        ticket = client.get(ticket_path, headers=owner_h).json()["ticket"]
        moved = client.patch(ticket_path, headers=agent_h, json={"status": "IN_PROGRESS", "expected_updated_at": ticket["updated_at"]})
        assert moved.status_code == 200, moved.text
        ticket = client.get(ticket_path, headers=owner_h).json()["ticket"]
        resolved = client.post(ticket_path + "/resolve", headers=agent_h, json={"request_id": str(uuid4()),
            "category": "configuration", "summary": "已修正演示VPN配置并验证连接恢复。",
            "steps": "检查客户端配置\n重新连接并验证", "expected_updated_at": ticket["updated_at"]})
        assert resolved.status_code == 201, resolved.text
        resolution = client.get(ticket_path + "/resolution", headers=owner_h).json()["resolution"]
        assert resolution and "description" not in resolution

        request_id = str(uuid4())
        payload = {"request_id": request_id, "resolution_id": resolution["id"],
            "title": "VPN重新连接操作", "content": "打开批准的VPN客户端，检查服务器地址并重新连接，然后确认内网服务可以访问。",
            "keywords": "VPN 连接 配置"}
        created = client.post("/api/v1/helpdesk/knowledge-drafts", headers=agent_h, json=payload)
        assert created.status_code == 201, created.text
        draft = created.json()["draft"]
        assert created.json()["cached"] is False
        assert client.post("/api/v1/helpdesk/knowledge-drafts", headers=agent_h, json=payload).json()["cached"] is True
        assert client.get(f"/api/v1/helpdesk/knowledge-drafts/{draft['id']}", headers=coworker_h).status_code == 404
        assert client.get(f"/api/v1/helpdesk/knowledge-drafts/{draft['id']}", headers=outsider_h).status_code == 404
        assert client.get("/api/v1/helpdesk/knowledge-drafts", headers=outsider_h).json()["items"] == []
        assert "VPN重新连接操作" not in str(client.get("/api/v1/helpdesk/knowledge", headers=owner_h).json())

        edited = client.put(f"/api/v1/helpdesk/knowledge-drafts/{draft['id']}", headers=agent_h, json={
            "expected_version": 1, "title": "VPN重新连接操作（修订）", "content": payload["content"], "keywords": payload["keywords"]})
        assert edited.status_code == 200, edited.text
        # Creation retry is tied to its immutable original body, not mutable draft fields.
        replay = client.post("/api/v1/helpdesk/knowledge-drafts", headers=agent_h, json=payload)
        assert replay.status_code == 201 and replay.json()["cached"] is True
        admin_h = owner_h
        assert client.post(f"/api/v1/helpdesk/knowledge-drafts/{draft['id']}/reject", headers=admin_h,
            json={"expected_version": 2, "note": ""}).status_code == 422
        rejected = client.post(f"/api/v1/helpdesk/knowledge-drafts/{draft['id']}/reject", headers=admin_h,
            json={"expected_version": 2, "note": "请补充适用范围。"})
        assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED"
        revised = client.put(f"/api/v1/helpdesk/knowledge-drafts/{draft['id']}", headers=agent_h, json={
            "expected_version": 3, "title": payload["title"], "content": payload["content"], "keywords": payload["keywords"]})
        assert revised.status_code == 200 and revised.json()["status"] == "DRAFT"

        import app.helpdesk.knowledge_drafts_api as drafts_api
        original_save = drafts_api.save_document
        async def fail_index(*args, **kwargs):
            raise RuntimeError("injected index failure")
        monkeypatch.setattr(drafts_api, "save_document", fail_index)
        publish_path = f"/api/v1/helpdesk/knowledge-drafts/{draft['id']}/publish"
        failed = client.post(publish_path, headers=admin_h, json={"expected_version": 4, "note": ""})
        assert failed.status_code == 500
        state = client.get(f"/api/v1/helpdesk/knowledge-drafts/{draft['id']}", headers=admin_h).json()["draft"]
        assert state["status"] == "DRAFT" and state["published_code"] is None
        assert "VPN重新连接操作" not in str(client.get("/api/v1/helpdesk/knowledge", headers=owner_h).json())
        monkeypatch.setattr(drafts_api, "save_document", original_save)
        published = client.post(publish_path, headers=admin_h, json={"expected_version": 4, "note": "已核对步骤"})
        assert published.status_code == 200, published.text
        code = published.json()["source_code"]
        assert client.post(publish_path, headers=admin_h, json={"expected_version": 4, "note": ""}).json()["cached"] is True
        sources = client.get("/api/v1/helpdesk/knowledge", headers=owner_h).json()
        assert any(source["code"] == code for source in sources)
        search = client.post("/api/v1/helpdesk/knowledge/search", headers=owner_h, json={"query": "VPN重新连接操作"})
        assert search.status_code == 200 and any(item["code"] == code for item in search.json()["results"])

        # Reopening an older resolution invalidates its pending draft for publication.
        second_run = client.post("/api/v1/helpdesk/runs", headers=owner_h, json={"request_id": str(uuid4()),
            "question": "VPN第二次认证失败，请转人工处理"})
        assert second_run.status_code == 200, second_run.text
        second_path = f"/api/v1/helpdesk/tickets/{second_run.json()['ticket_id']}"
        second = client.get(second_path, headers=owner_h).json()["ticket"]
        assert client.post(second_path + "/assignment", headers=owner_h, json={"request_id": str(uuid4()),
            "agent_id": agent["user"]["id"], "reason": "接手处理", "expected_updated_at": second["updated_at"]}).status_code == 200
        second = client.get(second_path, headers=owner_h).json()["ticket"]
        assert client.patch(second_path, headers=agent_h, json={"status": "IN_PROGRESS", "expected_updated_at": second["updated_at"]}).status_code == 200
        second = client.get(second_path, headers=owner_h).json()["ticket"]
        second_resolved = client.post(second_path + "/resolve", headers=agent_h, json={"request_id": str(uuid4()),
            "category": "service", "summary": "已恢复服务并验证VPN连接。", "steps": "重启服务后验证连接。",
            "expected_updated_at": second["updated_at"]})
        assert second_resolved.status_code == 201, second_resolved.text
        old_resolution = client.get(second_path + "/resolution", headers=owner_h).json()["resolution"]
        old_draft = client.post("/api/v1/helpdesk/knowledge-drafts", headers=agent_h, json={"request_id": str(uuid4()),
            "resolution_id": old_resolution["id"], "title": "VPN服务恢复", "content": "重启VPN服务后检查状态，再由用户确认连接恢复正常。",
            "keywords": "VPN 服务 恢复"})
        assert old_draft.status_code == 201, old_draft.text
        before_reopen = client.get(second_path, headers=owner_h).json()["ticket"]
        reopen = client.post(f"/api/v1/helpdesk/my-tickets/{second_run.json()['ticket_id']}/reopen", headers=owner_h,
            json={"request_id": str(uuid4()), "expected_updated_at": before_reopen["updated_at"], "explanation": "问题仍然存在，需要继续排查。"})
        assert reopen.status_code == 200, reopen.text
        invalidated = client.post(f"/api/v1/helpdesk/knowledge-drafts/{old_draft.json()['draft']['id']}/publish", headers=owner_h,
            json={"expected_version": 1, "note": ""})
        assert invalidated.status_code == 409

