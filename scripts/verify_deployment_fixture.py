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
        assert await connection.scalar(text("SELECT version_num FROM alembic_version"))=="c7e60b9124d8", "schema revision mismatch"
    await engine.dispose()
    print(json.dumps({"fixture_verified":True,"ticket_closed":True,"rating":manifest["rating"],"published_vector_rows":True,"attachment_sha256_match":True}))


if __name__=="__main__":
    asyncio.run(verify(json.load(sys.stdin)))

