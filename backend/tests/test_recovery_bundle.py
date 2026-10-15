"""Real private SQLite and attachment bundle/restore exercise in temporary roots."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import zlib
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

_root = Path(tempfile.mkdtemp(prefix="resolveai-recovery-"))
_db = _root / "source.sqlite3"
_attachments = _root / "source-attachments"
_password = "Recovery-" + secrets.token_hex(12) + "aA1!"
os.environ.update({"DATABASE_URL": "sqlite+aiosqlite:///" + _db.as_posix(),
    "IT_ATTACHMENT_ROOT": _attachments.as_posix(), "IT_DEMO_ENABLED": "false",
    "DEFAULT_LLM_PROVIDER": "mock", "IT_EMBEDDING_PROVIDER": "local", "APP_ENV": "development"})
_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root))
from app.main import app
from scripts.recovery_bundle import backup_bundle, restore_bundle


def _png():
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff")) + chunk(b"IEND", b"")


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _copy_bundle(source, name):
    destination = _root / ".local" / "backups" / name
    shutil.copytree(source, destination)
    return destination


def test_private_bundle_validates_and_restores_real_app_state(monkeypatch):
    suffix = uuid4().hex
    with TestClient(app, raise_server_exceptions=False) as client:
        owner_result = client.post("/api/v1/auth/register", json={"email": f"owner-{suffix}@example.com",
            "password": _password, "full_name": "Bundle Owner", "tenant_name": "Bundle Workspace",
            "tenant_slug": f"bundle-{suffix}"})
        assert owner_result.status_code == 201, owner_result.text
        owner = owner_result.json()
        owner_h = {"Authorization": "Bearer " + owner["access_token"]}
        agent_email = f"agent-{suffix}@example.com"
        invite = client.post("/api/v1/auth/invitations", headers=owner_h, json={"email": agent_email})
        assert invite.status_code == 201, invite.text
        accepted = client.post("/api/v1/auth/invitations/accept", json={"token": invite.json()["token"],
            "email": agent_email, "password": _password, "full_name": "Backup Agent"})
        assert accepted.status_code == 200, accepted.text
        agent = accepted.json()
        agent_h = {"Authorization": "Bearer " + agent["access_token"]}
        run = client.post("/api/v1/helpdesk/runs", headers=owner_h, json={"request_id": str(uuid4()),
            "question": "VPN连接失败，请转人工支持"})
        assert run.status_code == 200 and run.json()["ticket_id"]
        ticket_id = run.json()["ticket_id"]
        ticket_url = f"/api/v1/helpdesk/tickets/{ticket_id}"
        ticket = client.get(ticket_url, headers=owner_h).json()["ticket"]
        assigned = client.post(ticket_url + "/assignment", headers=owner_h, json={"request_id": str(uuid4()),
            "agent_id": agent["user"]["id"], "reason": "接手演练工单", "expected_updated_at": ticket["updated_at"]})
        assert assigned.status_code == 200, assigned.text
        view = client.post("/api/v1/helpdesk/queue-views", headers=agent_h, json={"request_id": str(uuid4()),
            "name": "恢复检查视图", "filters": {"q": "VPN", "status": None, "priority": None,
                "assignment": "mine", "sla": None, "page_size": 20}})
        assert view.status_code == 201, view.text
        active_body = _png()
        upload = client.post(f"/api/v1/helpdesk/my-tickets/{ticket_id}/attachments", headers=owner_h,
            data={"request_id": str(uuid4()), "expected_updated_at": client.get(ticket_url, headers=owner_h).json()["ticket"]["updated_at"]},
            files={"file": ("evidence.png", active_body, "image/png")})
        assert upload.status_code == 201, upload.text
        active_attachment = upload.json()["item"]
        deleted_body = b"tombstone log contents\n"
        tombstone_upload = client.post(f"/api/v1/helpdesk/my-tickets/{ticket_id}/attachments", headers=owner_h,
            data={"request_id": str(uuid4()), "expected_updated_at": client.get(ticket_url, headers=owner_h).json()["ticket"]["updated_at"]},
            files={"file": ("old.log", deleted_body, "text/plain")})
        assert tombstone_upload.status_code == 201, tombstone_upload.text
        deleted = client.request("DELETE", f"/api/v1/helpdesk/my-tickets/{ticket_id}/attachments/{tombstone_upload.json()['item']['id']}",
            headers=owner_h, json={"expected_updated_at": client.get(ticket_url, headers=owner_h).json()["ticket"]["updated_at"]})
        assert deleted.status_code == 200, deleted.text
    active_key = owner["user"]["tenant_id"] + "/" + active_attachment["id"]
    source_file = _attachments.joinpath(*active_key.split("/"))
    assert hashlib.sha256(source_file.read_bytes()).hexdigest() == active_attachment["sha256"]
    source_db_hash, source_attachment_hash = _hash(_db), _hash(source_file)

    backups = _root / ".local" / "backups"
    bundle_path = backups / "first"
    with pytest.raises(ValueError, match="offline_confirmed"):
        backup_bundle(_db, _attachments, bundle_path, _root)
    result = backup_bundle(_db, _attachments, bundle_path, _root, offline_confirmed=True)
    assert result["attachment_count"] == 1
    manifest = json.loads((bundle_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["database"]["sha256"] == _hash(bundle_path / "database.sqlite3")
    assert len(manifest["attachments"]) == 1 and "password" not in (bundle_path / "manifest.json").read_text().lower()
    assert "tombstone log contents" not in (bundle_path / "manifest.json").read_text()
    with pytest.raises(FileExistsError):
        backup_bundle(_db, _attachments, bundle_path, _root, offline_confirmed=True)

    restored = _root / ".local" / "restores" / "restored-one"
    restored_result = restore_bundle(bundle_path, restored, _root)
    assert restored_result["attachment_count"] == 1
    restored_file = restored / "attachments" / Path(*active_key.split("/"))
    assert _hash(restored_file) == active_attachment["sha256"]
    assert _hash(_db) == source_db_hash and _hash(source_file) == source_attachment_hash
    # A second restore may not overwrite any existing DB, attachment, or unrelated sentinel.
    sentinel = restored / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        restore_bundle(bundle_path, restored, _root)
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    import scripts.recovery_bundle as recovery
    interrupted = _root / ".local" / "restores" / "interrupted-copy"
    staging_before = set(interrupted.parent.glob(".*.staging-*"))
    def fail_copy(*args, **kwargs):
        raise OSError("injected copy failure")
    with monkeypatch.context() as patcher:
        patcher.setattr(recovery.shutil, "copyfile", fail_copy)
        with pytest.raises(OSError, match="injected copy failure"):
            restore_bundle(bundle_path, interrupted, _root)
    assert not interrupted.exists()
    assert set(interrupted.parent.glob(".*.staging-*")) == staging_before

    tampered_db = _copy_bundle(bundle_path, "tampered-db")
    with (tampered_db / "database.sqlite3").open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ValueError, match="Database hash"):
        restore_bundle(tampered_db, _root / ".local" / "restores" / "tampered-db", _root)
    tampered_file = _copy_bundle(bundle_path, "tampered-file")
    stored_key = manifest["attachments"][0]["storage_key"]
    with (tampered_file / "attachments" / Path(*stored_key.split("/"))).open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ValueError, match="Attachment hash"):
        restore_bundle(tampered_file, _root / ".local" / "restores" / "tampered-file", _root)
    missing = _copy_bundle(bundle_path, "missing-file")
    (missing / "attachments" / Path(*stored_key.split("/"))).unlink()
    with pytest.raises(ValueError):
        restore_bundle(missing, _root / ".local" / "restores" / "missing-file", _root)
    traversal = _copy_bundle(bundle_path, "traversal")
    changed = json.loads((traversal / "manifest.json").read_text(encoding="utf-8"))
    changed["attachments"][0]["storage_key"] = "../outside/" + stored_key.split("/")[-1]
    (traversal / "manifest.json").write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="UUID"):
        restore_bundle(traversal, _root / ".local" / "restores" / "traversal", _root)
    with pytest.raises(ValueError, match="traversal|direct child"):
        restore_bundle(bundle_path, _root / ".local" / "restores" / ".." / "escape", _root)

    # Symlinked backup sources are rejected; skip only when this Windows account cannot create links.
    linked_root = _root / "linked-attachments"
    try:
        os.symlink(_attachments, linked_root, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Windows symlink creation is unavailable in this test account")
    with pytest.raises(ValueError, match="symlink|junction"):
        backup_bundle(_db, linked_root, backups / "symlink-source", _root, offline_confirmed=True)

    child_code = r'''
import hashlib, json, os
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app, raise_server_exceptions=False) as client:
    login = client.post("/api/v1/auth/login", json={"email": os.environ["RECOVERY_LOGIN"], "password": os.environ["RECOVERY_PASSWORD"]})
    assert login.status_code == 200, login.text
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    tickets = client.get("/api/v1/helpdesk/tickets/" + os.environ["RECOVERY_TICKET"], headers=headers)
    assert tickets.status_code == 200, tickets.text
    notifications = client.get("/api/v1/helpdesk/notifications", headers=headers)
    assert notifications.status_code == 200 and any(n["kind"] == "assigned_to_me" for n in notifications.json()["items"])
    views = client.get("/api/v1/helpdesk/queue-views", headers=headers)
    assert views.status_code == 200 and any(row["name"] == "恢复检查视图" for row in views.json()["items"])
    attachment = client.get("/api/v1/helpdesk/tickets/" + os.environ["RECOVERY_TICKET"] + "/attachments/" + os.environ["RECOVERY_ATTACHMENT"] + "/download", headers=headers)
    assert attachment.status_code == 200, attachment.text
    print(json.dumps({"ticket": tickets.status_code, "notifications": len(notifications.json()["items"]), "views": len(views.json()["items"]), "attachment_sha256": hashlib.sha256(attachment.content).hexdigest()}))
'''
    child_env = os.environ.copy()
    child_env.update({"DATABASE_URL": "sqlite+aiosqlite:///" + (restored / "database.sqlite3").as_posix(),
        "IT_ATTACHMENT_ROOT": (restored / "attachments").as_posix(), "IT_DEMO_ENABLED": "false",
        "RECOVERY_LOGIN": agent_email, "RECOVERY_PASSWORD": _password, "RECOVERY_TICKET": ticket_id,
        "RECOVERY_ATTACHMENT": active_attachment["id"], "PYTHONPATH": str(_project_root / "backend") + os.pathsep + str(_project_root)})
    child = subprocess.run([sys.executable, "-c", child_code], cwd=_project_root, env=child_env,
        capture_output=True, text=True, timeout=45)
    assert child.returncode == 0, child.stderr[-3000:]
    restored_check = json.loads(child.stdout.strip().splitlines()[-1])
    assert restored_check["ticket"] == 200 and restored_check["attachment_sha256"] == active_attachment["sha256"]
