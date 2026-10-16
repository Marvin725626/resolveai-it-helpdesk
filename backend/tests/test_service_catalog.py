"""Isolated service catalog API coverage on SQLite."""
import os
import secrets
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

_root = Path(tempfile.mkdtemp(prefix="resolveai-service-catalog-"))
os.environ.update({"DATABASE_URL": "sqlite+aiosqlite:///" + (_root / "test.db").as_posix(),
    "IT_ATTACHMENT_ROOT": (_root / "storage").as_posix(), "IT_DEMO_ENABLED": "false",
    "DEFAULT_LLM_PROVIDER": "mock", "IT_EMBEDDING_PROVIDER": "local", "APP_ENV": "development"})
from app.main import app as fastapi_app
from app.core.config import settings
from app.helpdesk.catalog_api import router as catalog_router
import app.helpdesk.catalog_models  # register metadata before create_all

catalog_path = settings.API_V1_STR + "/helpdesk/service-catalog"
if not any(getattr(route, "path", "") == catalog_path for route in fastapi_app.routes):
    fastapi_app.include_router(catalog_router, prefix=settings.API_V1_STR)


def test_catalog_permissions_validation_versions_and_submit_replay():
    suffix, password = uuid4().hex, "Catalog-" + secrets.token_hex(12) + "Aa1!"
    with TestClient(fastapi_app, raise_server_exceptions=False) as client:
        def register(name):
            response = client.post(settings.API_V1_STR + "/auth/register", json={
                "email": f"{name}-{suffix}@example.com", "password": password, "full_name": name,
                "tenant_name": name, "tenant_slug": f"{name}-{suffix}"})
            assert response.status_code == 201, response.text
            account = response.json()
            return {"Authorization": "Bearer " + account["access_token"]}, account

        owner_headers, owner = register("catalog-owner")
        stranger_headers, _ = register("catalog-stranger")
        invite = client.post(settings.API_V1_STR + "/auth/invitations", headers=owner_headers,
            json={"email": f"agent-{suffix}@example.com"})
        assert invite.status_code == 201, invite.text
        support_response = client.post(settings.API_V1_STR + "/auth/invitations/accept", json={
            "token": invite.json()["token"], "email": f"agent-{suffix}@example.com",
            "password": password, "full_name": "Catalog Support"})
        assert support_response.status_code == 200, support_response.text
        support_headers = {"Authorization": "Bearer " + support_response.json()["access_token"]}

        admin_path = settings.API_V1_STR + "/helpdesk/service-catalog-admin"
        fields = [{"key": "device_name", "label": "设备名称", "type": "text", "required": True},
                  {"key": "urgency", "label": "处理时段", "type": "select", "required": True,
                   "options": ["今天", "本周"]}]
        create = {"request_id": str(uuid4()), "code": "device-access", "title": "设备接入申请",
            "summary": "申请接入办公设备", "category": "network", "fields": fields, "status": "published"}
        bad = {**create, "request_id": str(uuid4()), "fields": [{**fields[0], "key": "Bad-Key"}]}
        assert client.post(admin_path, headers=owner_headers, json=bad).status_code == 422
        created = client.post(admin_path, headers=owner_headers, json=create)
        assert created.status_code == 201, created.text
        item = created.json()["item"]
        assert item["version"] == 1
        assert client.post(admin_path, headers=owner_headers, json=create).json()["replayed"] is True
        assert client.post(admin_path, headers=owner_headers, json={**create, "title": "另一个服务"}).status_code == 409
        assert client.get(admin_path, headers=support_headers).status_code == 403
        public = client.get(catalog_path, headers=support_headers).json()["items"]
        assert [row["id"] for row in public] == [item["id"]]
        assert client.get(catalog_path + "/" + item["id"], headers=stranger_headers).status_code == 404

        submit_path = catalog_path + "/" + item["id"] + "/submit"
        submit = {"request_id": str(uuid4()), "expected_version": 1,
            "answers": {"device_name": "Laptop 42", "urgency": "今天"}}
        assert client.post(submit_path, headers=support_headers,
            json={**submit, "answers": {"unknown": "x"}}).status_code == 422
        assert client.post(submit_path, headers=support_headers,
            json={**submit, "answers": {"device_name": "Laptop 42", "urgency": "tomorrow"}}).status_code == 422
        response = client.post(submit_path, headers=support_headers, json=submit)
        assert response.status_code == 201, response.text
        ticket_id = response.json()["ticket_id"]
        assert client.post(submit_path, headers=support_headers, json=submit).json() == {
            "ticket_id": ticket_id, "request_id": submit["request_id"], "replayed": True}
        assert client.post(submit_path, headers=support_headers,
            json={**submit, "answers": {"device_name": "Another", "urgency": "今天"}}).status_code == 409
        assert client.get(settings.API_V1_STR + f"/helpdesk/my-tickets/{ticket_id}", headers=support_headers).status_code == 200

        edit_path = admin_path + "/" + item["id"]
        update_body = {k: item[k] for k in ("code", "title", "summary", "category", "fields", "status")}
        changed = client.put(edit_path, headers=owner_headers,
            json={**update_body, "expected_version": 1, "title": "设备接入新申请"})
        assert changed.status_code == 200 and changed.json()["item"]["version"] == 2
        assert client.put(edit_path, headers=owner_headers,
            json={**update_body, "expected_version": 1}).status_code == 409
        archived = client.put(edit_path, headers=owner_headers, json={**update_body,
            "expected_version": 2, "status": "archived"})
        assert archived.status_code == 200 and archived.json()["item"]["version"] == 3
        assert client.get(catalog_path + "/" + item["id"], headers=support_headers).status_code == 404
        # A completed submission replays from its immutable payload even after archive/edit.
        assert client.post(submit_path, headers=support_headers, json=submit).json()["ticket_id"] == ticket_id
        revisions = client.get(edit_path + "/revisions", headers=owner_headers).json()["revisions"]
        assert [r["version"] for r in revisions] == [3, 2, 1]
        ops = client.get(settings.API_V1_STR + f"/helpdesk/tickets/{ticket_id}", headers=owner_headers)
        assert ops.status_code == 200
        assert ops.json()["ticket"]["status"] == "OPEN"
