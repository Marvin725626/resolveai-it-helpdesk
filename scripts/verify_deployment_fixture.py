"""Verify a synthetic deployment/recovery manifest from stdin; never prints secrets."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import text
from app.core.database import engine
from app.helpdesk.attachment_storage import storage_path


async def verify(manifest):
    async with engine.connect() as connection:
        values={key:manifest[key] for key in ("tenant_id","ticket_id","resolution_id","draft_id","attachment_id")}
        ticket=await connection.execute(text("SELECT status FROM tickets WHERE tenant_id=:tenant_id AND id=:ticket_id"),values)
        assert ticket.scalar_one()=="CLOSED", "ticket state did not persist"
        resolution=await connection.scalar(text("SELECT count(*) FROM resolveai_ticket_resolutions WHERE tenant_id=:tenant_id AND ticket_id=:ticket_id AND id=:resolution_id"),values)
        assert resolution==1, "resolution did not persist"
        rating=await connection.scalar(text("SELECT rating FROM resolveai_resolution_satisfaction WHERE tenant_id=:tenant_id AND ticket_id=:ticket_id AND resolution_id=:resolution_id"),values)
        assert rating==manifest["rating"], "satisfaction did not persist"
        draft=await connection.scalar(text("SELECT status FROM resolveai_knowledge_drafts WHERE tenant_id=:tenant_id AND id=:draft_id AND resolution_id=:resolution_id"),values)
        assert draft=="PUBLISHED", "published draft did not persist"
        chunks=await connection.scalar(text("SELECT count(*) FROM resolveai_chunks WHERE tenant_id=:tenant_id AND code=:code"),{**values,"code":manifest["source_code"]})
        assert chunks>0, "published vector rows did not persist"
        row=(await connection.execute(text("SELECT storage_key,sha256,deleted_at FROM resolveai_ticket_attachments WHERE tenant_id=:tenant_id AND ticket_id=:ticket_id AND id=:attachment_id"),values)).one()
        assert row.deleted_at is None and row.storage_key==manifest["storage_key"], "active attachment reference did not persist"
        assert hashlib.sha256(storage_path(row.storage_key).read_bytes()).hexdigest()==row.sha256==manifest["sha256"], "attachment bytes did not persist"
        if manifest.get("manual_ticket_id"):
            manual = {"tenant_id":manifest["tenant_id"],"ticket_id":manifest["manual_ticket_id"],
                "request_id":manifest["manual_request_id"],"user_id":manifest["manual_user_id"]}
            assert await connection.scalar(text("SELECT count(*) FROM resolveai_manual_ticket_submissions s JOIN tickets t ON t.id=s.ticket_id AND t.tenant_id=s.tenant_id WHERE s.tenant_id=:tenant_id AND s.ticket_id=:ticket_id AND s.request_id=:request_id AND s.user_id=:user_id AND t.status='IN_PROGRESS'"),manual)==1, "manual requester ownership did not persist"
        catalog = False
        if manifest.get("catalog_ticket_id"):
            service = {"tenant_id":manifest["tenant_id"],"ticket_id":manifest["catalog_ticket_id"],
                "request_id":manifest["catalog_request_id"],"item_id":manifest["catalog_item_id"],
                "version":manifest["catalog_version"]}
            row = (await connection.execute(text("SELECT s.payload->'service_input' AS service_input,t.status "
                "FROM resolveai_manual_ticket_submissions s JOIN tickets t ON t.id=s.ticket_id AND t.tenant_id=s.tenant_id "
                "WHERE s.tenant_id=:tenant_id AND s.ticket_id=:ticket_id AND s.request_id=:request_id"),service)).one()
            service_input = json.loads(row.service_input) if isinstance(row.service_input, str) else row.service_input
            assert row.status=="OPEN" and service_input["item_id"]==service["item_id"] and service_input["version"]==service["version"], "catalog ticket snapshot did not persist"
            item_status = await connection.scalar(text("SELECT status FROM resolveai_service_catalog_items WHERE tenant_id=:tenant_id AND id=:item_id"),service)
            assert item_status=="archived", "catalog archival did not persist"
            revisions = await connection.scalar(text("SELECT count(*) FROM resolveai_service_catalog_revisions WHERE item_id=:item_id"),service)
            assert revisions==3, "catalog revisions did not persist"
            if manifest.get("requester_user_id"):
                role = await connection.scalar(text("SELECT role::text FROM users WHERE tenant_id=:tenant_id AND id=:user_id"),
                    {"tenant_id":service["tenant_id"],"user_id":manifest["requester_user_id"]})
                assert role=="REQUESTER", "requester role did not persist"
            catalog = True
        assert await connection.scalar(text("SELECT version_num FROM alembic_version"))=="f20b8c6d4192", "schema revision mismatch"
        assert await connection.scalar(text("SELECT to_regclass('resolveai_manual_ticket_submissions')")) is not None, "manual request ownership table missing"
    await engine.dispose()
    print(json.dumps({"fixture_verified":True,"ticket_closed":True,"rating":manifest["rating"],"published_vector_rows":True,"attachment_sha256_match":True,"manual_request_ownership":bool(manifest.get("manual_ticket_id")),"service_catalog_snapshot":catalog}))


if __name__=="__main__":
    asyncio.run(verify(json.load(sys.stdin)))

