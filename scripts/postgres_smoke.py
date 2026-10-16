"""Real PostgreSQL/pgvector migration + business checks in two newly-created databases.
Run in the backend image: docker compose ... exec -T backend python /app/scripts/postgres_smoke.py
Requires a role with CREATEDB (the local Compose role). Never drops the configured source DB.
"""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from uuid import uuid4

import asyncpg
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def require(condition, label):
    if not condition:
        raise AssertionError(label)


def migrate(url, revision="head"):
    environment = {**os.environ, "DATABASE_URL": url, "APP_SCHEMA_MODE": "migrate", "IT_DEMO_ENABLED": "false"}
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", revision], cwd=BACKEND,
                            env=environment, capture_output=True, text=True)
    if result.returncode:
        # Redact credentials even if a driver embeds its DSN in an error.
        error = result.stderr
        for secret in (make_url(url).password, os.environ.get("AUTH_SECRET"), os.environ.get("IT_DEMO_PASSWORD")):
            if secret:
                error = error.replace(secret, "[redacted]")
        raise RuntimeError("Migration failed: " + error[-3500:])


async def business(url, attachment_root, live=False):
    os.environ.update(DATABASE_URL=url, APP_SCHEMA_MODE="migrate", IT_DEMO_ENABLED="false",
                      IT_ATTACHMENT_ROOT=str(attachment_root), DEFAULT_LLM_PROVIDER="mock", IT_EMBEDDING_PROVIDER="local")
    sys.path.insert(0, str(BACKEND))
    import httpx
    from app.main import app
    from app.core.database import engine
    from sqlalchemy import text
    suffix = uuid4().hex
    password = secrets.token_hex(24) + "Aa1!"
    @asynccontextmanager
    async def context():
        if live:
            yield
        else:
            async with app.router.lifespan_context(app):
                yield
    async with context():
        transport = None if live else httpx.ASGITransport(app=app, raise_app_exceptions=True)
        base_url = "http://frontend:5174" if live else "http://test"
        async with httpx.AsyncClient(transport=transport, base_url=base_url, timeout=120) as client:
            async def api(method, path, token=None, status=200, **kwargs):
                response = await client.request(method, "/api/v1" + path,
                    headers={"Authorization": "Bearer " + token} if token else {}, **kwargs)
                require(response.status_code == status, f"{method} {path}: expected {status}, got {response.status_code}")
                return response.json() if response.content and "json" in response.headers.get("content-type", "") else response
            async def register(label):
                return await api("POST", "/auth/register", status=201, json={"email":f"{label}-{suffix}@example.com",
                    "password":password,"full_name":label,"tenant_name":label,"tenant_slug":label+"-"+suffix})
            owner, outsider = await register("pg-owner"), await register("pg-outsider")
            token, wrong = owner["access_token"], outsider["access_token"]
            invitation = await api("POST", "/auth/invitations", token, status=201, json={"email":f"support-{suffix}@example.com"})
            support = await api("POST", "/auth/invitations/accept", json={"email":f"support-{suffix}@example.com",
                "token":invitation["token"],"password":password,"full_name":"PG support"})
            support_token = support["access_token"]
            # Manual requests must be independent of AI runs, including racing retries.
            manual_body = {"request_id":str(uuid4()), "subject":"PG主动报障并发验收", "category":"network",
                "description":"仅用于合成验收的办公网络故障，重连后仍无法访问测试服务。"}
            manual_responses = await asyncio.gather(*(client.post("/api/v1/helpdesk/my-tickets",
                headers={"Authorization":"Bearer "+token},json=manual_body) for _ in range(2)))
            require(all(r.status_code==201 for r in manual_responses), "manual racing submissions both succeed")
            manual_ids = {r.json()["ticket_id"] for r in manual_responses}
            require(len(manual_ids)==1 and sorted(r.json()["cached"] for r in manual_responses)==[False,True], "manual race creates exactly one ticket")
            manual_id = manual_ids.pop()
            manual_mine = "/helpdesk/my-tickets/"+manual_id
            manual_ops = "/helpdesk/tickets/"+manual_id
            require((await api("GET","/helpdesk/my-tickets",token))["total"]==1, "manual list has no duplicate ownership joins")
            require((await api("GET","/helpdesk/runs",token))==[], "manual submission does not fabricate AI runs")
            await api("GET",manual_mine,wrong,status=404)
            await api("GET",manual_mine,support_token,status=404)
            await api("POST","/helpdesk/my-tickets",wrong,status=404,json=manual_body)
            await api("POST","/helpdesk/my-tickets",token,status=409,json={**manual_body,"subject":"修改后的标题不能复用原请求"})
            manual_ticket = (await api("GET",manual_ops,support_token))["ticket"]
            require(manual_ticket["status"]=="OPEN" and manual_ticket["priority"]=="MEDIUM" and manual_ticket["assigned_agent_id"] is None,"server controls initial triage")
            await api("POST",manual_ops+"/claim",support_token,json={"expected_updated_at":manual_ticket["updated_at"]})
            replayed = await api("POST","/helpdesk/my-tickets",token,status=201,json=manual_body)
            require(replayed["cached"] and replayed["ticket_id"]==manual_id,"manual replay after later processing")
            manual_ticket = (await api("GET",manual_ops,support_token))["ticket"]
            require(manual_ticket["status"]=="IN_PROGRESS", "replay must not reset later ticket state")
            await api("POST",manual_ops+"/replies",support_token,status=201,json={"request_id":str(uuid4()),
                "expected_updated_at":manual_ticket["updated_at"],"body":"合成支持回复：正在检查网络配置。"})
            require(len((await api("GET",manual_mine+"/replies",token))["items"])==1,"manual requester sees public reply")
            require(any(n["ticket_id"]==manual_id and n["kind"]=="support_reply" for n in
                (await api("GET","/helpdesk/notifications",token))["items"]),"manual requester notified")
            async with engine.connect() as connection:
                require(await connection.scalar(text("SELECT count(*) FROM resolveai_manual_ticket_submissions WHERE tenant_id=:tenant"),{"tenant":owner["user"]["tenant_id"]})==1,"one manual ownership record")
                require(await connection.scalar(text("SELECT count(*) FROM customers WHERE tenant_id=:tenant"),{"tenant":owner["user"]["tenant_id"]})==1,"racing retry leaves no orphan customer")
            run_body = {"request_id":str(uuid4()),"question":"VPN认证失败，请转人工处理"}
            if live:
                events=[]
                async with client.stream("POST","/api/v1/helpdesk/runs/stream",headers={"Authorization":"Bearer "+token},json=run_body) as response:
                    require(response.status_code==200 and "text/event-stream" in response.headers.get("content-type", ""), "same-origin SSE headers")
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            events.append(json.loads(line[6:]))
                require(any(event["type"]=="trace" for event in events),"SSE progress events through Nginx")
                run=next(event["result"] for event in events if event["type"]=="result")
                report=await api("GET","/helpdesk/evaluation-report",token)
                require(report["source"]=="bundled_offline_fixture_report","offline report packaged in image")
            else:
                run = await api("POST", "/helpdesk/runs", token, json=run_body)
            ticket_id = run["ticket_id"]
            # SQL source filters must behave identically on PostgreSQL and SQLite.
            manual_page = await api("GET","/helpdesk/ticket-queue?source=manual",token)
            require(manual_page["total"]==1 and manual_page["items"][0]["id"]==manual_id and manual_page["items"][0]["source"]=="manual","queue manual provenance")
            ai_page = await api("GET","/helpdesk/ticket-queue?source=ai",token)
            require(ai_page["total"]==1 and ai_page["items"][0]["id"]==ticket_id,"queue AI provenance")
            require((await api("GET","/helpdesk/ticket-queue?source=legacy",token))["total"]==0,"legacy is not guessed from title")
            exported = await api("GET","/helpdesk/ticket-queue/export?source=manual",token)
            require(exported["total"]==manual_page["total"] and [r["id"] for r in exported["items"]]==[manual_id],"export uses same source predicate")
            private_marker = "internal-diagnostic-"+suffix
            async with engine.begin() as connection:
                context_json = json.loads(await connection.scalar(text("SELECT description FROM tickets WHERE tenant_id=:tenant AND id=:id"),{"tenant":owner["user"]["tenant_id"],"id":ticket_id}))
                context_json["internal_search_marker"] = private_marker
                await connection.execute(text("UPDATE tickets SET description=:description WHERE tenant_id=:tenant AND id=:id"),{"description":json.dumps(context_json,ensure_ascii=False),"tenant":owner["user"]["tenant_id"],"id":ticket_id})
            require((await api("GET","/helpdesk/my-tickets",token,params={"q":private_marker}))["total"]==0,"personal search must not match internal context")
            personal = await api("GET","/helpdesk/my-tickets",token,params={"q":"合成验收的办公网络","source":"manual"})
            require(personal["total"]==1 and personal["items"][0]["id"]==manual_id,"personal search matches own submitted description")
            require((await api("GET","/helpdesk/my-tickets",wrong,params={"q":"合成验收的办公网络"}))["total"]==0,"personal search tenant isolation")
            require((await api("GET","/helpdesk/my-tickets",token,params={"q":"%_"}))["total"]==0,"wildcards are literal")
            require((await api("GET","/helpdesk/my-tickets?source=manual&status=ESCALATED",token))["total"]==0,"source and status compose")
            path = "/helpdesk/tickets/" + ticket_id
            mine = "/helpdesk/my-tickets/" + ticket_id
            async def ticket(): return (await api("GET", path, token))["ticket"]
            await api("GET", path, wrong, status=404)
            await api("POST", path+"/assignment", token, json={"request_id":str(uuid4()),"agent_id":support["user"]["id"],
                "reason":"PG业务验证接手","expected_updated_at":(await ticket())["updated_at"]})
            await api("PATCH", path, support_token, json={"status":"IN_PROGRESS","expected_updated_at":(await ticket())["updated_at"]})
            content = b"Synthetic PG diagnostic log; no real credentials."
            upload_body = {"request_id":str(uuid4()),"expected_updated_at":(await ticket())["updated_at"]}
            uploaded = await api("POST", mine+"/attachments", token, status=201, data=upload_body, files={"file":("diagnostic.txt",content,"text/plain")})
            item = uploaded["item"]
            replay = await api("POST", mine+"/attachments", token, status=201, data=upload_body, files={"file":("diagnostic.txt",content,"text/plain")})
            require(replay["cached"] and replay["item"]["id"] == item["id"], "attachment replay")
            download = await api("GET", path+"/attachments/"+item["id"]+"/download", support_token)
            require(hashlib.sha256(download.content).hexdigest() == item["sha256"], "attachment bytes/hash")
            await api("GET", mine+"/attachments/"+item["id"]+"/download", support_token, status=404)
            await api("GET", path+"/attachments/"+item["id"]+"/download", wrong, status=404)

            # CAS case 1: different requests, identical ticket revision. Exactly one wins.
            revision = (await ticket())["updated_at"]
            priorities = ["LOW", "URGENT"]
            requests = [{"request_id":str(uuid4()),"expected_updated_at":revision,"priority":p,"reason":"PG并发分诊验证"} for p in priorities]
            responses = await asyncio.gather(*(client.post("/api/v1"+path+"/priority",headers={"Authorization":"Bearer "+support_token},json=body) for body in requests))
            require(sorted(r.status_code for r in responses)==[200,409], "ticket CAS must yield one success and one explicit conflict")
            winner = next(i for i,r in enumerate(responses) if r.status_code==200)
            require((await ticket())["priority"] == priorities[winner], "loser must not overwrite ticket priority")
            exact = await api("POST", path+"/priority",support_token,json=requests[winner])
            require(exact["cached"], "CAS winning request replay")
            await api("POST", path+"/priority",wrong,status=404,json=requests[winner])

            # CAS case 2: personal views are separately scoped and versioned.
            filters={"q":"VPN","status":None,"priority":None,"assignment":"mine","sla":None,"page_size":20}
            view_request={"request_id":str(uuid4()),"name":"PG view","filters":filters}
            created=await api("POST","/helpdesk/queue-views",token,status=201,json=view_request)
            view=created["view"]; view_path="/helpdesk/queue-views/"+view["id"]
            view_responses=await asyncio.gather(*(client.put("/api/v1"+view_path,headers={"Authorization":"Bearer "+token},
                json={"expected_version":view["version"],"name":name,"filters":filters}) for name in ("PG winner A","PG winner B")))
            require(sorted(r.status_code for r in view_responses)==[200,409],"view CAS must yield one success and one conflict")
            winning_view=next(r.json()["view"] for r in view_responses if r.status_code==200)
            require((await api("GET","/helpdesk/queue-views",token))["items"][0]["name"]==winning_view["name"],"view loser must not overwrite winner")
            await api("PUT",view_path,wrong,status=404,json={"expected_version":2,"name":"bad","filters":filters})
            require((await api("GET","/helpdesk/queue-views",support_token))["items"]==[],"views are personal")

            compatible = await api("POST","/helpdesk/queue-views",token,status=201,json={**view_request,"filters":{**filters,"source":None}})
            require(compatible["cached"] and compatible["view"]["id"]==view["id"],"omitted and null source preserve old creation replay")
            source_view = await api("POST","/helpdesk/queue-views",token,status=201,json={"request_id":str(uuid4()),"name":"PG manual source","filters":{**filters,"source":"manual"}})
            require(source_view["view"]["filters"]["source"]=="manual","source view persists")
            changed_source = await api("PUT","/helpdesk/queue-views/"+source_view["view"]["id"],token,json={"expected_version":1,"name":"PG AI source","filters":{**filters,"source":"ai"}})
            require(changed_source["view"]["filters"]["source"]=="ai","source view update persists")
            preserved = None
            if live:
                preserved = await api("POST",path+"/attachments",support_token,status=201,
                    data={"request_id":str(uuid4()),"expected_updated_at":(await ticket())["updated_at"]},
                    files={"file":("recovery-fixture.log",b"Synthetic backup recovery attachment.","text/plain")})
            resolved = await api("POST",path+"/resolve",support_token,status=201,json={"request_id":str(uuid4()),
                "expected_updated_at":(await ticket())["updated_at"],"category":"configuration",
                "summary":"修正模拟VPN配置后连接恢复。","steps":"检查模拟配置，重新连接并验证。"})
            resolution_id=resolved["resolution"]["id"]
            draft=await api("POST","/helpdesk/knowledge-drafts",support_token,status=201,json={"request_id":str(uuid4()),"resolution_id":resolution_id,
                "title":"PG演练VPN连接方法","content":"打开批准的VPN客户端，检查模拟服务器配置，重新连接后确认测试内网服务能够访问。","keywords":"VPN 连接 PG"})
            draft_id=draft["draft"]["id"]
            published=await api("POST","/helpdesk/knowledge-drafts/"+draft_id+"/publish",token,json={"expected_version":1,"note":"核对模拟内容"})
            searched=await api("POST","/helpdesk/knowledge/search",token,json={"query":"PG演练VPN连接方法"})
            require(any(row["code"]==published["source_code"] for row in searched["results"]),"pgvector-backed hybrid retrieval finds published knowledge")
            await api("POST",mine+"/confirm-resolved",token,json={"request_id":str(uuid4()),"expected_updated_at":(await ticket())["updated_at"]})
            rating=await api("POST",mine+"/satisfaction",token,status=201,json={"request_id":str(uuid4()),"resolution_id":resolution_id,"rating":5,"comment":"模拟流程验证完成"})
            require(rating["satisfaction"]["rating"]==5,"per-round rating persists")
            require((await api("GET",mine+"/resolution",token))["satisfaction"]["rating"]==5,"rating refresh")
            await api("DELETE",mine+"/attachments/"+item["id"],token,json={"expected_updated_at":(await ticket())["updated_at"]})
            await api("GET",path+"/attachments/"+item["id"]+"/download",support_token,status=404)
            async with engine.connect() as connection:
                require(await connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'")),"vector extension installed")
                require(await connection.scalar(text("SELECT count(*) FROM resolveai_chunks")) > 0,"real vector rows exist")
            require((await api("GET","/health"))["database"]=="healthy","database health")
            if live:
                # Private, synthetic fixture manifest for the separately-run restore drill.
                async with engine.connect() as connection:
                    key = await connection.scalar(text("SELECT storage_key FROM resolveai_ticket_attachments WHERE id=:id"), {"id":preserved["item"]["id"]})
                manifest = {"tenant_id":owner["user"]["tenant_id"], "ticket_id":ticket_id, "resolution_id":resolution_id,
                    "draft_id":draft_id, "source_code":published["source_code"], "attachment_id":preserved["item"]["id"],
                    "storage_key":key, "sha256":preserved["item"]["sha256"], "rating":5,
                    "manual_ticket_id":manual_id, "manual_request_id":manual_body["request_id"], "manual_user_id":owner["user"]["id"]}
                output=Path("/tmp/resolveai-deployment-fixture.json")
                descriptor=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
                with os.fdopen(descriptor,"w",encoding="utf-8") as target:
                    json.dump(manifest,target)
                print(json.dumps({"live_deployment_passed":True,"same_origin_nginx":True,"sse_progress":True,"bundled_report":True,"fixture_manifest":"/tmp/resolveai-deployment-fixture.json"}))
    await engine.dispose()


async def main():
    source=make_url(os.environ.get("RESOLVEAI_PG_TEST_URL") or os.environ["DATABASE_URL"])
    require(source.get_backend_name()=="postgresql", "Only PostgreSQL is supported; configured DB is never modified")
    if "--live" in sys.argv:
        await business(source.render_as_string(hide_password=False),Path(os.environ["IT_ATTACHMENT_ROOT"]),live=True)
        return
    connection=await asyncpg.connect(host=source.host,port=source.port or 5432,user=source.username,password=source.password,database=source.database)
    databases=[]
    try:
        fresh="resolveai_test_"+uuid4().hex
        upgrade="resolveai_test_"+uuid4().hex
        for name in (fresh,upgrade):
            await connection.execute('CREATE DATABASE "'+name+'"')
            databases.append(name)
        fresh_url=source.set(drivername="postgresql+asyncpg",database=fresh).render_as_string(hide_password=False)
        upgrade_url=source.set(drivername="postgresql+asyncpg",database=upgrade).render_as_string(hide_password=False)
        await asyncio.to_thread(migrate,fresh_url)
        await asyncio.to_thread(migrate,fresh_url)  # repeat startup is harmless
        await asyncio.to_thread(migrate,upgrade_url,"53df04c2178b")
        previous=await asyncpg.connect(host=source.host,port=source.port or 5432,user=source.username,password=source.password,database=upgrade)
        try:
            # Reproduce an older deployment missing both latest additive tables.
            await previous.execute("DROP TABLE resolveai_saved_queue_views")
            await previous.execute("DROP TABLE resolveai_manual_ticket_submissions")
            await previous.execute("CREATE TABLE migration_sentinel (value text PRIMARY KEY)")
            await previous.execute("INSERT INTO migration_sentinel VALUES ('preserve-existing-data')")
        finally:
            await previous.close()
        await asyncio.to_thread(migrate,upgrade_url)
        checked=await asyncpg.connect(host=source.host,port=source.port or 5432,user=source.username,password=source.password,database=upgrade)
        try:
            require(await checked.fetchval("SELECT value FROM migration_sentinel")=="preserve-existing-data","upgrade preserves data")
            require(await checked.fetchval("SELECT to_regclass('resolveai_saved_queue_views')") is not None,"upgrade adds table")
            require(await checked.fetchval("SELECT to_regclass('resolveai_manual_ticket_submissions')") is not None,"upgrade adds manual request ownership table")
            require(await checked.fetchval("SELECT version_num FROM alembic_version")=="d1a4f8c29b73","upgrade revision")
        finally:
            await checked.close()
        with tempfile.TemporaryDirectory(prefix="resolveai-pg-attachments-") as storage:
            await business(fresh_url,Path(storage))
        print(json.dumps({"passed":True,"database":"PostgreSQL","migrations":["fresh","repeat","upgrade-preserves-data"],
            "pgvector_hybrid_search":True,"resolution_rating_draft_publish":True,"attachment_bytes_delete":True,
            "scoped_concurrent_CAS_cases":2,"manual_submission_race_and_isolation":True,"source_filters_and_private_search":True,"source_database_untouched":True}))
    finally:
        for name in databases:
            # Names are generated UUIDs, never caller-controlled. Drop only our new DBs.
            require(re.fullmatch(r"resolveai_test_[0-9a-f]{32}",name) is not None,"cleanup database guard")
            await connection.execute('DROP DATABASE IF EXISTS "'+name+'" WITH (FORCE)')
        await connection.close()


if __name__=="__main__":
    asyncio.run(main())
