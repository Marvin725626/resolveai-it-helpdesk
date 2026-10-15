"""Structured public resolution, immutable rounds and requester-only per-round feedback."""
import os
import secrets
import sqlite3
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event

_directory = tempfile.TemporaryDirectory(prefix="resolveai-resolutions-")
_database = Path(_directory.name) / "test.db"
os.environ.update({"DATABASE_URL": "sqlite+aiosqlite:///" + _database.as_posix(), "IT_DEMO_ENABLED": "false",
    "DEFAULT_LLM_PROVIDER": "mock", "IT_EMBEDDING_PROVIDER": "local", "APP_ENV": "development"})
from app.main import app
from app.core.database import engine

@event.listens_for(engine.sync_engine, "connect")
def foreign_keys(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")


def test_resolution_rounds_are_scoped_atomic_idempotent_and_rated_once(monkeypatch):
    suffix = uuid4().hex; password = "Resolution-" + secrets.token_hex(12) + "Aa1!"
    with TestClient(app, raise_server_exceptions=False) as client:
        def register(label):
            response = client.post("/api/v1/auth/register", json={"email": f"{label}-{suffix}@example.com", "password": password,
                "full_name": label, "tenant_name": label, "tenant_slug": f"{label}-{suffix}"})
            assert response.status_code == 201, response.text
            return response.json()
        owner = register("requester"); stranger = register("stranger")
        def headers(account): return {"Authorization": "Bearer " + account["access_token"]}
        ho, hx = headers(owner), headers(stranger)
        agents=[]
        for label in ("support", "other"):
            email=f"{label}-{suffix}@example.com"
            invite=client.post("/api/v1/auth/invitations", headers=ho, json={"email":email})
            accepted=client.post("/api/v1/auth/invitations/accept", json={"email":email,"password":password,"full_name":label,"token":invite.json()["token"]})
            assert accepted.status_code == 200
            agents.append(accepted.json())
        hs,hc=map(headers,agents)
        def create():
            response=client.post("/api/v1/helpdesk/runs", headers=ho, json={"request_id":str(uuid4()),"question":"VPN认证超时，请人工处理"})
            assert response.status_code==200
            return response.json()["ticket_id"]
        ticket_id=create(); legacy_id=create()
        ops=f"/api/v1/helpdesk/tickets/{ticket_id}"
        mine=f"/api/v1/helpdesk/my-tickets/{ticket_id}"
        def ticket(): return client.get(ops,headers=ho).json()["ticket"]
        def resolution(h=ho, path=ops):
            response=client.get(path+"/resolution",headers=h);assert response.status_code==200,response.text;return response.json()
        def solve(body=None, h=hs):
            body=body or {"request_id":str(uuid4()),"expected_updated_at":ticket()["updated_at"],"category":"service","summary":"已恢复VPN服务并验证登录。","steps":"检查服务状态，修复配置，再验证连接。"}
            return client.post(ops+"/resolve",headers=h,json=body),body
        before=ticket()
        assert client.post(ops+"/claim",headers=hs,json={"expected_updated_at":before["updated_at"]}).status_code==200
        assert resolution()["can_resolve"]
        assert client.get(mine+"/resolution",headers=hs).status_code==404
        assert client.get(ops+"/resolution",headers=hx).status_code==404
        assert solve(h=hc)[0].status_code==403
        assert client.patch(ops,headers=hs,json={"status":"RESOLVED","expected_updated_at":ticket()["updated_at"]}).status_code==409
        assert solve({"request_id":str(uuid4()),"expected_updated_at":before["updated_at"],"category":"other","summary":"陈旧版本不得覆盖"})[0].status_code==409
        assert solve({"request_id":str(uuid4()),"expected_updated_at":ticket()["updated_at"],"category":"other","summary":"  "})[0].status_code==422
        client.post("/api/v1/helpdesk/notifications/read-all",headers=ho)
        first,body=solve();assert first.status_code==201,first.text
        first_id=first.json()["resolution"]["id"]
        snapshot=resolution()["resolution"]
        assert snapshot["summary"]==body["summary"] and snapshot["steps"]==body["steps"]
        assert resolution(path=mine)["current"] and snapshot["resolved_at"].endswith("+00:00")
        assert "description" not in str(snapshot) and "expected_updated_at" not in snapshot
        replay,_=solve(body);assert replay.status_code==201 and replay.json()["cached"] and replay.json()["resolution"]["id"]==first_id
        assert solve({**body,"summary":"同请求不能变更公开摘要"})[0].status_code==409
        events=client.get(ops+"/events",headers=ho).json()["events"]
        assert sum(row["id"]==body["request_id"] for row in events)==1
        notices=client.get("/api/v1/helpdesk/notifications?unread_only=true",headers=ho).json()
        assert notices["unread_count"]==1 and body["summary"] not in str(notices)
        def rate(resolution_id, rating=5, comment="处理说明清楚", request_id=None, h=ho):
            data={"request_id":request_id or str(uuid4()),"resolution_id":resolution_id,"rating":rating,"comment":comment}
            return client.post(mine+"/satisfaction",headers=h,json=data),data
        assert rate(first_id)[0].status_code==409
        reopened=client.post(mine+"/reopen",headers=ho,json={"request_id":str(uuid4()),"expected_updated_at":ticket()["updated_at"],"explanation":"仍有认证错误，请继续处理。"})
        assert reopened.status_code==200
        assert not resolution()["current"] and resolution()["resolution"]==snapshot
        assert ticket()["resolved_at"] is None
        second,_=solve();assert second.status_code==201,second.text
        second_id=second.json()["resolution"]["id"];assert second_id!=first_id
        confirmed=client.post(mine+"/confirm-resolved",headers=ho,json={"request_id":str(uuid4()),"expected_updated_at":ticket()["updated_at"]})
        assert confirmed.status_code==200 and ticket()["status"]=="CLOSED"
        assert rate(first_id)[0].status_code==409
        assert rate(second_id,h=hs)[0].status_code==404
        assert rate(second_id,h=hx)[0].status_code==404
        assert rate(str(uuid4()))[0].status_code==404
        for invalid in (0,6,True): assert rate(second_id,rating=invalid)[0].status_code==422
        submitted,rating_body=rate(second_id);assert submitted.status_code==201,submitted.text
        replayed=client.post(mine+"/satisfaction",headers=ho,json=rating_body)
        assert replayed.status_code==201 and replayed.json()["cached"] and replayed.json()["satisfaction"]["id"]==submitted.json()["satisfaction"]["id"]
        assert client.post(mine+"/satisfaction",headers=ho,json={**rating_body,"rating":4}).status_code==409
        assert rate(second_id)[0].status_code==409
        assert resolution()["satisfaction"]["rating"]==5
        # A new round never inherits the previous round's rating. Commit failure cannot leave a snapshot or solved status.
        assert client.patch(ops,headers=hs,json={"status":"IN_PROGRESS","expected_updated_at":ticket()["updated_at"]}).status_code==200
        from sqlalchemy.ext.asyncio import AsyncSession
        async def fail_commit(self): raise RuntimeError("simulated database failure")
        with monkeypatch.context() as patch:
            patch.setattr(AsyncSession,"commit",fail_commit)
            failed,_=solve();assert failed.status_code==500
        assert ticket()["status"]=="IN_PROGRESS" and resolution()["resolution"]["id"]==second_id
        third,_=solve();assert third.status_code==201
        third_id=third.json()["resolution"]["id"]
        assert resolution()["satisfaction"] is None
        # Retrying the successful previous feedback only replays it; it cannot rate or close the new round.
        assert client.post(mine+"/satisfaction",headers=ho,json=rating_body).json()["cached"]
        assert resolution()["satisfaction"] is None and ticket()["status"]=="RESOLVED"
        assert client.post(mine+"/confirm-resolved",headers=ho,json={"request_id":str(uuid4()),"expected_updated_at":ticket()["updated_at"]}).status_code==200
        assert rate(third_id,rating=3,comment="再次处理后恢复。")[0].status_code==201
        assert resolution()["satisfaction"]["rating"]==3
        conn=sqlite3.connect(_database)
        first_row=conn.execute("SELECT summary,steps FROM resolveai_ticket_resolutions WHERE id=?",(first_id,)).fetchone()
        assert first_row==(snapshot["summary"],snapshot["steps"])
        assert conn.execute("SELECT count(*) FROM resolveai_ticket_resolutions WHERE ticket_id=?",(ticket_id,)).fetchone()[0]==3
        # Real historical rows may have RESOLVED without a structured snapshot; old confirmation still works.
        conn.execute("UPDATE tickets SET status='RESOLVED',resolved_at='2026-10-15 00:00:00' WHERE id=?",(legacy_id,));conn.commit();conn.close()
        legacy=f"/api/v1/helpdesk/my-tickets/{legacy_id}"
        legacy_detail=client.get(legacy,headers=ho).json()["ticket"]
        assert resolution(path=f"/api/v1/helpdesk/tickets/{legacy_id}")["resolution"] is None
        assert client.post(legacy+"/confirm-resolved",headers=ho,json={"request_id":str(uuid4()),"expected_updated_at":legacy_detail["updated_at"]}).status_code==200
