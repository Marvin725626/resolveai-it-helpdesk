"""Private attachment lifecycle in isolated DB/storage, with real FK constraints."""
import asyncio
import hashlib
import os
from pathlib import Path
import secrets
import struct
import tempfile
import time
from uuid import uuid4
import zlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

_directory = tempfile.TemporaryDirectory(prefix="resolveai-attachments-")
_root = Path(_directory.name)
os.environ.update({"DATABASE_URL": "sqlite+aiosqlite:///" + (_root / "test.db").as_posix(),
    "IT_ATTACHMENT_ROOT": (_root / "storage").as_posix(), "IT_DEMO_ENABLED": "false",
    "DEFAULT_LLM_PROVIDER": "mock", "IT_EMBEDDING_PROVIDER": "local", "APP_ENV": "development"})
from app.main import app
from app.core.database import AsyncSessionLocal, engine
from app.helpdesk.attachment_storage import MAX_BODY_BYTES, MAX_FILE_BYTES, cleanup_orphans, storage_path

@event.listens_for(engine.sync_engine, "connect")
def foreign_keys(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")


def png(row=b"\x00\xff\x00\x00\xff"):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(row)) + chunk(b"IEND", b"")


def test_private_attachments_lifecycle_limits_and_cleanup(monkeypatch):
    password = "Attach-" + secrets.token_hex(16) + "Aa1!"
    suffix = uuid4().hex
    with TestClient(app, raise_server_exceptions=False) as client:
        def register(label):
            r = client.post("/api/v1/auth/register", json={"email": f"{label}-{suffix}@example.com", "password": password,
                "full_name": label, "tenant_name": label, "tenant_slug": f"{label}-{suffix}"})
            assert r.status_code == 201, r.text
            return r.json()
        owner = register("requester"); stranger = register("stranger")
        def headers(account): return {"Authorization": "Bearer " + account["access_token"]}
        ho, hx = headers(owner), headers(stranger)
        agents = []
        for label in ("support", "other-support"):
            email = f"{label}-{suffix}@example.com"
            invite = client.post("/api/v1/auth/invitations", headers=ho, json={"email": email})
            accepted = client.post("/api/v1/auth/invitations/accept", json={"email": email, "password": password,
                "full_name": label, "token": invite.json()["token"]})
            assert accepted.status_code == 200, accepted.text
            agents.append(accepted.json())
        support, other = agents; hs, hc = headers(support), headers(other)
        def ticket():
            r = client.post("/api/v1/helpdesk/runs", headers=ho, json={"request_id": str(uuid4()), "question": "VPN 无法连接，请转人工"})
            assert r.status_code == 200, r.text
            return r.json()["ticket_id"]
        identity = ticket(); wrong_ticket = ticket()
        personal = f"/api/v1/helpdesk/my-tickets/{identity}/attachments"
        ops = f"/api/v1/helpdesk/tickets/{identity}/attachments"
        def detail(): return client.get(f"/api/v1/helpdesk/tickets/{identity}", headers=ho).json()["ticket"]
        def upload(route, h, name="trace.txt", content=b"diagnostic log", request=None):
            request = request or {"request_id": str(uuid4()), "expected_updated_at": detail()["updated_at"]}
            return client.post(route, headers=h, data=request, files={"file": (name, content, "application/octet-stream")}), request
        def files(): return sorted(p for p in (_root / "storage").rglob("*") if p.is_file())
        assigned = client.post(f"/api/v1/helpdesk/tickets/{identity}/assignment", headers=ho, json={"request_id": str(uuid4()),
            "agent_id": support["user"]["id"], "reason": "请接手", "expected_updated_at": detail()["updated_at"]})
        assert assigned.status_code == 200
        before = detail()
        image, image_request = upload(personal, ho, "截图.png", png())
        assert image.status_code == 201, image.text
        image_item = image.json()["item"]; image_id = image_item["id"]
        assert image_item["content_type"] == "image/png" and image_item["sha256"] == hashlib.sha256(png()).hexdigest()
        assert "storage" not in image.text and "path" not in image.text
        assert len(files()) == 1
        replay, _ = upload(personal, ho, "截图.png", png(), image_request)
        assert replay.status_code == 201 and replay.json()["cached"] and replay.json()["item"]["id"] == image_id
        assert len(files()) == 1
        changed, _ = upload(personal, ho, "截图.png", png(b"\x00\x00\xff\x00\xff"), image_request)
        assert changed.status_code == 409
        events = client.get(f"/api/v1/helpdesk/tickets/{identity}/events", headers=ho).json()["events"]
        assert sum(row["id"] == image_request["request_id"] for row in events) == 1
        notifications = client.get("/api/v1/helpdesk/notifications", headers=hs).json()["items"]
        assert sum(row["kind"] == "attachment_added" for row in notifications) == 1
        text, text_request = upload(personal, ho, "环境.txt", "公司无线网络，认证超时。".encode())
        assert text.status_code == 201, text.text
        different, _ = upload(personal, ho, "环境.txt", b"different valid text", text_request)
        assert different.status_code == 409
        stale, _ = upload(personal, ho, request={"request_id": str(uuid4()), "expected_updated_at": before["updated_at"]})
        assert stale.status_code == 409 and len(files()) == 2
        downloaded = client.get(f"{ops}/{image_id}/download", headers=hs)
        assert downloaded.content == png() and downloaded.headers["cache-control"] == "private, no-store"
        assert downloaded.headers["x-content-type-options"] == "nosniff" and downloaded.headers["content-disposition"].startswith("attachment;")
        assert client.get(f"{personal}/{image_id}/download", headers=hs).status_code == 404
        assert client.get(f"{ops}/{image_id}/download", headers=hx).status_code == 404
        assert client.get(f"/api/v1/helpdesk/tickets/{wrong_ticket}/attachments/{image_id}/download", headers=hs).status_code == 404
        assert upload(ops, hc)[0].status_code == 403
        assert client.request("DELETE", f"{ops}/{image_id}", headers=hc, json={"expected_updated_at": detail()["updated_at"]}).status_code == 403
        support_log, _ = upload(ops, hs, "support.log", b"service check completed\n")
        assert support_log.status_code == 201, support_log.text
        persisted = client.get(personal, headers=ho).json()
        assert len(persisted["items"]) == 3
        assert client.get(personal+"?page_size=2", headers=ho).json()["has_more"]
        first_page = client.get(personal+"?page_size=2", headers=ho).json()
        older = client.get(personal+f"?page_size=2&before={first_page['next_before']}", headers=ho).json()
        assert len(older["items"]) == 1
        # Image/text validation and both declared-length and streamed total-body limits leave no files.
        baseline = len(files())
        for name, body in (("fake.png", b"not an image"), ("image.svg", b"<svg/>"), ("page.html", b"<html/>"),
                ("page.txt", b"<html>active</html>"), ("../trace.txt", b"safe"), ("bad.txt", b"\xff\x00"),
                ("large.log", b"x" * (MAX_FILE_BYTES + 1))):
            rejected, _ = upload(personal, ho, name, body)
            assert rejected.status_code in (413, 422), (name, rejected.status_code, rejected.text)
            assert len(files()) == baseline
        oversized = client.post(personal, headers=ho, content=b"x" * (MAX_BODY_BYTES + 1))
        assert oversized.status_code == 413
        streamed = client.post(personal, headers={**ho, "Content-Type": "multipart/form-data; boundary=test"},
            content=iter([b"x" * (MAX_BODY_BYTES // 2), b"x" * (MAX_BODY_BYTES // 2 + 2)]))
        assert streamed.status_code == 413 and len(files()) == baseline
        # WAITING requester upload is a single primary notification and resumes work without changing SLA/owner.
        assert client.patch(f"/api/v1/helpdesk/tickets/{identity}", headers=hs, json={"status":"IN_PROGRESS", "expected_updated_at":detail()["updated_at"]}).status_code == 200
        assert client.patch(f"/api/v1/helpdesk/tickets/{identity}", headers=hs, json={"status":"WAITING_FOR_CUSTOMER", "expected_updated_at":detail()["updated_at"]}).status_code == 200
        client.post("/api/v1/helpdesk/notifications/read-all", headers=hs)
        waiting_before = detail()
        resumed, _ = upload(personal, ho, "more.log", b"more detail")
        assert resumed.status_code == 201
        after = detail()
        assert after["status"] == "IN_PROGRESS" and after["created_at"] == waiting_before["created_at"]
        assert after["assigned_agent_id"] == waiting_before["assigned_agent_id"] and after["sla"]["due_at"] == waiting_before["sla"]["due_at"]
        unread = client.get("/api/v1/helpdesk/notifications?unread_only=true", headers=hs).json()
        assert unread["unread_count"] == 1 and unread["items"][0]["kind"] == "attachment_added"
        assert "more.log" not in str(unread)
        # Failed DB commit removes both finalized file and metadata/event transaction.
        from sqlalchemy.ext.asyncio import AsyncSession
        async def fail_commit(self): raise RuntimeError("simulated database failure")
        baseline = len(files())
        with monkeypatch.context() as patch:
            patch.setattr(AsyncSession, "commit", fail_commit)
            failed, _ = upload(personal, ho, "failure.txt", b"failure fixture")
            assert failed.status_code == 500
        assert len(files()) == baseline and len(client.get(personal, headers=ho).json()["items"]) == baseline
        # Fill the serialized per-ticket quota, then verify another upload cannot leave an object.
        for i in range(20 - baseline):
            filled, _ = upload(personal, ho, f"fixture-{i}.log", b"quota fixture")
            assert filled.status_code == 201, filled.text
        assert len(files()) == 20
        assert upload(personal, ho, "overflow.log", b"quota fixture")[0].status_code == 409
        assert len(files()) == 20
        # Closed ticket: cached old upload succeeds, new upload fails, uploader can still remove.
        assert client.post(f"/api/v1/helpdesk/tickets/{identity}/resolve", headers=hs, json={"request_id":str(uuid4()), "category":"configuration", "summary":"已修复演示网络配置并验证连接恢复。", "steps":"检查配置并验证连接。", "expected_updated_at":detail()["updated_at"]}).status_code == 201
        assert client.post(f"/api/v1/helpdesk/my-tickets/{identity}/confirm-resolved", headers=ho, json={"request_id":str(uuid4()),"expected_updated_at":detail()["updated_at"]}).status_code == 200
        assert upload(personal, ho, "截图.png", png(), image_request)[0].status_code == 201
        assert upload(personal, ho)[0].status_code == 409
        # Simulate Windows unlink failure. Tombstone blocks downloads, is hidden, retry cleans it.
        image_path = next(p for p in files() if p.read_bytes() == png())
        real_unlink = Path.unlink
        def fail_unlink(self, *args, **kwargs):
            if self.resolve() == image_path.resolve(): raise PermissionError("simulated busy file")
            return real_unlink(self, *args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(Path, "unlink", fail_unlink)
            removed = client.request("DELETE", f"{personal}/{image_id}", headers=ho, json={"expected_updated_at":detail()["updated_at"]})
            assert removed.status_code == 200 and removed.json()["cleanup_pending"]
        assert client.get(f"{ops}/{image_id}/download", headers=hs).status_code == 404
        assert image_id not in {row["id"] for row in client.get(personal, headers=ho).json()["items"]}
        assert client.request("DELETE", f"{personal}/{image_id}", headers=ho, json={"expected_updated_at":before["updated_at"]}).status_code == 200
        assert not image_path.exists()
        assert upload(personal, ho, "截图.png", png(), image_request)[0].status_code == 410
        assert client.get(personal+"?page_size=51", headers=ho).status_code == 422
        # Cleanup never uses user filenames, leaves live refs / fresh temps / outside files alone.
        async def cleanup_check():
            root = _root / "storage"; tenant = root / owner["user"]["tenant_id"]
            orphan = tenant / str(uuid4()); old_temp = tenant / (".tmp-"+str(uuid4())); fresh_temp = tenant / (".tmp-"+str(uuid4()))
            for path in (orphan, old_temp, fresh_temp): path.write_bytes(b"fixture")
            old = time.time()-90000
            os.utime(orphan,(old,old)); os.utime(old_temp,(old,old))
            live = next(p for p in files() if p.name != fresh_temp.name and p not in (orphan,old_temp))
            os.utime(live,(old,old))
            outside = _root / "outside.txt"; outside.write_bytes(b"keep")
            with pytest.raises(ValueError): storage_path("../outside.txt", root)
            async with AsyncSessionLocal() as db:
                planned = await cleanup_orphans(db, root=root)
                assert f"{tenant.name}/{orphan.name}" in planned and f"{tenant.name}/{old_temp.name}" in planned
                assert orphan.exists() and old_temp.exists()
                await cleanup_orphans(db, root=root, dry_run=False)
            assert not orphan.exists() and not old_temp.exists() and fresh_temp.exists() and live.exists() and outside.exists()
            fresh_temp.unlink(); outside.unlink()
        asyncio.run(cleanup_check())
