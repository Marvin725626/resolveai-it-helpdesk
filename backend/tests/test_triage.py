"""Priority triage and persistent personal queue views on an isolated database."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event

_directory=tempfile.TemporaryDirectory(prefix="resolveai-triage-")
_database=Path(_directory.name)/"test.db"
os.environ.update({"DATABASE_URL":"sqlite+aiosqlite:///"+_database.as_posix(),"IT_DEMO_ENABLED":"false",
    "DEFAULT_LLM_PROVIDER":"mock","IT_EMBEDDING_PROVIDER":"local","APP_ENV":"development"})
from app.main import app
from app.core.database import engine

@event.listens_for(engine.sync_engine,"connect")
def foreign_keys(connection,_): connection.execute("PRAGMA foreign_keys=ON")


def test_priority_sla_and_personal_views_are_atomic_private_and_persistent(monkeypatch):
    suffix=uuid4().hex;password="Triage-"+secrets.token_hex(12)+"Aa1!"
    with TestClient(app,raise_server_exceptions=False) as client:
        def register(label):
            result=client.post("/api/v1/auth/register",json={"email":f"{label}-{suffix}@example.com","password":password,
                "full_name":label,"tenant_name":label,"tenant_slug":f"{label}-{suffix}"})
            assert result.status_code==201,result.text
            return result.json()
        owner=register("owner");stranger=register("stranger")
        def auth(account):return {"Authorization":"Bearer "+account["access_token"]}
        ho,hx=auth(owner),auth(stranger)
        agents=[]
        for label in ("assigned","other"):
            email=f"{label}-{suffix}@example.com"
            invited=client.post("/api/v1/auth/invitations",headers=ho,json={"email":email})
            result=client.post("/api/v1/auth/invitations/accept",json={"email":email,"password":password,
                "full_name":label,"token":invited.json()["token"]})
            assert result.status_code==200
            agents.append(result.json())
        hs,hc=map(auth,agents)
        def create_ticket():
            result=client.post("/api/v1/helpdesk/runs",headers=ho,json={"request_id":str(uuid4()),"question":"VPN认证失败，请转人工处理"})
            assert result.status_code==200
            return result.json()["ticket_id"]
        identity=create_ticket();other_ticket=create_ticket();path=f"/api/v1/helpdesk/tickets/{identity}"
        created=datetime.now(timezone.utc)-timedelta(hours=3)
        conn=sqlite3.connect(_database);conn.execute("UPDATE tickets SET created_at=? WHERE id=?",(created.replace(tzinfo=None).isoformat(" "),identity));conn.commit();conn.close()
        def ticket():return client.get(path,headers=ho).json()["ticket"]
        assert client.post(path+"/claim",headers=hs,json={"expected_updated_at":ticket()["updated_at"]}).status_code==200
        before=ticket()
        def priority(priority="URGENT",reason="需要优先处理",h=hs,body=None):
            body=body or {"request_id":str(uuid4()),"expected_updated_at":ticket()["updated_at"],"priority":priority,"reason":reason}
            return client.post(path+"/priority",headers=h,json=body),body
        assert client.get(path+"/priority",headers=hx).status_code==404
        assert priority(h=hc)[0].status_code==403
        assert priority(body={"request_id":str(uuid4()),"expected_updated_at":before["created_at"],"priority":"URGENT","reason":"陈旧版本"})[0].status_code==409
        for invalid in ({"priority":"NOW"},{"reason":" "},{"arbitrary":True}):
            body={"request_id":str(uuid4()),"expected_updated_at":ticket()["updated_at"],"priority":"URGENT","reason":"调整原因",**invalid}
            assert priority(body=body)[0].status_code==422
        client.post("/api/v1/helpdesk/notifications/read-all",headers=ho)
        changed,body=priority(reason="token=private-sample-value 需加快处理")
        assert changed.status_code==200,changed.text
        after=ticket()
        assert after["priority"]=="URGENT" and after["sla"]["state"]=="overdue"
        assert after["created_at"]==before["created_at"] and after["assigned_agent_id"]==before["assigned_agent_id"] and after["resolved_at"]==before["resolved_at"]
        assert datetime.fromisoformat(after["sla"]["due_at"])-datetime.fromisoformat(after["created_at"])==timedelta(hours=1)
        replay,_=priority(body=body);assert replay.status_code==200 and replay.json()["cached"]
        assert priority(body={**body,"priority":"LOW"})[0].status_code==409
        assert priority()[0].status_code==409
        events=client.get(path+"/events",headers=ho).json()["events"]
        rows=[row for row in events if row["id"]==body["request_id"]]
        assert len(rows)==1 and rows[0]["type"]=="priority_changed"
        assert rows[0]["payload"]["from_due_at"]==before["sla"]["due_at"] and rows[0]["payload"]["to_due_at"]==after["sla"]["due_at"]
        assert "private-sample-value" not in str(rows)
        notices=client.get("/api/v1/helpdesk/notifications?unread_only=true",headers=ho).json()
        assert notices["unread_count"]==1 and notices["items"][0]["kind"]=="priority_changed"
        assert "token" not in str(notices) and "需加快处理" not in str(notices)
        # A failed commit rolls back priority, event and notification together.
        from sqlalchemy.ext.asyncio import AsyncSession
        async def fail_commit(self):raise RuntimeError("simulated database failure")
        failed_id=str(uuid4())
        with monkeypatch.context() as patch:
            patch.setattr(AsyncSession,"commit",fail_commit)
            failed,_=priority(body={"request_id":failed_id,"expected_updated_at":ticket()["updated_at"],"priority":"LOW","reason":"故障夹具"})
            assert failed.status_code==500
        assert ticket()["priority"]=="URGENT" and not any(row["id"]==failed_id for row in client.get(path+"/events",headers=ho).json()["events"])
        # Retry the same successful request after handing off and finishing, before new permission/status/version guards.
        assigned=client.post(path+"/assignment",headers=ho,json={"request_id":str(uuid4()),"agent_id":agents[1]["user"]["id"],"reason":"请继续处理","expected_updated_at":ticket()["updated_at"]})
        assert assigned.status_code==200
        assert priority(body=body)[0].json()["cached"]
        assert priority(priority="LOW")[0].status_code==403
        solved=client.post(path+"/resolve",headers=hc,json={"request_id":str(uuid4()),"expected_updated_at":ticket()["updated_at"],"category":"service","summary":"演示服务恢复并完成验证。"})
        assert solved.status_code==201
        assert priority(body=body)[0].json()["cached"]
        assert priority(priority="LOW",h=ho)[0].status_code==409
        # Personal filters persist in the backend and cannot hold arbitrary URL/query keys.
        views="/api/v1/helpdesk/queue-views"
        filters={"q":"VPN","status":"IN_PROGRESS","priority":"URGENT","assignment":"mine","sla":"overdue","page_size":10}
        request={"request_id":str(uuid4()),"name":"  我的紧急工单  ","filters":filters}
        saved=client.post(views,headers=ho,json=request);assert saved.status_code==201,saved.text
        view=saved.json()["view"];assert view["name"]=="我的紧急工单" and view["filters"]==filters
        replayed=client.post(views,headers=ho,json=request);assert replayed.json()["cached"] and replayed.json()["view"]["id"]==view["id"]
        assert client.post(views,headers=ho,json={**request,"filters":{**filters,"page_size":20}}).status_code==409
        assert client.get(views,headers=hs).json()["items"]==[] and client.get(views,headers=hx).json()["items"]==[]
        assert client.post(views,headers=hs,json=request).status_code==404
        assert client.put(views+"/"+view["id"],headers=hs,json={"expected_version":1,"name":"越权","filters":filters}).status_code==404
        assert client.request("DELETE",views+"/"+view["id"],headers=hx,json={"expected_version":1}).status_code==404
        relogin=client.post("/api/v1/auth/login",json={"email":owner["user"]["email"],"password":password}).json()
        assert client.get(views,headers=auth(relogin)).json()["items"][0]["filters"]==filters
        for extra in ("page","ticketId","token","url"):
            assert client.post(views,headers=ho,json={"request_id":str(uuid4()),"name":"非法字段","filters":{**filters,extra:"forbidden"}}).status_code==422
        for invalid in ({"status":"ANY"},{"priority":"NOW"},{"assignment":"everyone"},{"sla":"all"},{"page_size":True},{"page_size":101},{"q":"x"*201}):
            assert client.post(views,headers=ho,json={"request_id":str(uuid4()),"name":"非法取值","filters":{**filters,**invalid}}).status_code==422
        assert client.post(views,headers=ho,json={"request_id":str(uuid4()),"name":"x"*51,"filters":filters}).status_code==422
        updated=client.put(views+"/"+view["id"],headers=ho,json={"expected_version":1,"name":"更新后的视图","filters":{**filters,"page_size":27}})
        assert updated.status_code==200 and updated.json()["view"]["version"]==2
        assert client.put(views+"/"+view["id"],headers=ho,json={"expected_version":1,"name":"陈旧覆盖","filters":filters}).status_code==409
        assert client.post(views,headers=ho,json=request).json()["view"]["version"]==2
        assert client.post(views,headers=ho,json={"request_id":str(uuid4()),"name":"更新后的视图","filters":filters}).status_code==409
        for i in range(9):
            assert client.post(views,headers=ho,json={"request_id":str(uuid4()),"name":f"视图{i}","filters":{}}).status_code==201
        assert len(client.get(views,headers=ho).json()["items"])==10
        assert client.post(views,headers=ho,json={"request_id":str(uuid4()),"name":"超出上限","filters":{}}).status_code==409
        assert client.request("DELETE",views+"/"+view["id"],headers=ho,json={"expected_version":1}).status_code==409
        removed=client.request("DELETE",views+"/"+view["id"],headers=ho,json={"expected_version":2})
        assert removed.status_code==200 and removed.json()["version"]==3
        assert client.request("DELETE",views+"/"+view["id"],headers=ho,json={"expected_version":2}).json()["cached"]
        assert client.post(views,headers=ho,json=request).status_code==410
        assert client.post(views,headers=ho,json={"request_id":str(uuid4()),"name":"更新后的视图","filters":{}}).status_code==201
