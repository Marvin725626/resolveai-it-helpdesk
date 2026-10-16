"""Ticket source filters and requester search are isolated from production data."""
import os
import secrets
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, select

_root = Path(tempfile.mkdtemp(prefix="resolveai-ticket-filters-"))
os.environ.update({"DATABASE_URL": "sqlite+aiosqlite:///" + (_root / "test.db").as_posix(),
    "IT_ATTACHMENT_ROOT": (_root / "storage").as_posix(), "IT_DEMO_ENABLED": "false",
    "DEFAULT_LLM_PROVIDER": "mock", "IT_EMBEDDING_PROVIDER": "local", "APP_ENV": "development"})
from app.main import app
from app.core.database import engine

@event.listens_for(engine.sync_engine, "connect")
def enable_foreign_keys(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")


def test_ticket_source_filters_and_private_requester_search():
    suffix = uuid4().hex
    password = "Filter-" + secrets.token_hex(12) + "Aa1!"
    with TestClient(app, raise_server_exceptions=False) as client:
        registered = client.post("/api/v1/auth/register", json={"email": f"owner-{suffix}@example.com",
            "password": password, "full_name": "Filter Owner", "tenant_name": "Filters", "tenant_slug": f"filters-{suffix}"})
        assert registered.status_code == 201, registered.text
        account = registered.json()
        headers = {"Authorization": "Bearer " + account["access_token"]}
        user = client.get("/api/v1/auth/me", headers=headers).json()
        manual = client.post("/api/v1/helpdesk/my-tickets", headers=headers, json={
            "request_id": str(uuid4()), "subject": f"Manual title {suffix[:8]}", "category": "network",
            "description": f"Public description needle%_ {suffix}"})
        assert manual.status_code == 201, manual.text
        manual_id = manual.json()["ticket_id"]

        from app.core.database import AsyncSessionLocal
        from app.helpdesk.models import HelpdeskRun
        from app.models.customer import Customer
        from app.models.ticket import Ticket, TicketPriority, TicketStatus
        from datetime import datetime, timezone
        ai_id, legacy_id = str(uuid4()), str(uuid4())
        async def seed():
            async with AsyncSessionLocal() as db:
                customer = await db.scalar(select(Customer).where(
                    Customer.tenant_id == user["tenant_id"], Customer.email == account["user"]["email"]))
                now = datetime.now(timezone.utc)
                ai_ticket = Ticket(id=ai_id, tenant_id=user["tenant_id"], customer_id=customer.id,
                    subject=f"AI title {suffix[:8]}", description=f"Internal diagnosis secret-internal-{suffix}",
                    status=TicketStatus.OPEN, priority=TicketPriority.MEDIUM, created_at=now)
                legacy_ticket = Ticket(id=legacy_id, tenant_id=user["tenant_id"], customer_id=customer.id,
                    subject=f"Legacy title {suffix[:8]}", description="legacy fixture",
                    status=TicketStatus.OPEN, priority=TicketPriority.MEDIUM, created_at=now)
                db.add_all([ai_ticket, legacy_ticket])
                for index in range(2):
                    db.add(HelpdeskRun(id=str(uuid4()), tenant_id=user["tenant_id"], user_id=user["id"],
                        question=f"AI question needle%_ {suffix}", result={"ticket_id": ai_id, "status": "completed"}, created_at=now))
                await db.commit()
        client.portal.call(seed)

        queue = "/api/v1/helpdesk/ticket-queue"
        all_items = client.get(queue, headers=headers, params={"q": suffix[:8], "page_size": 20})
        assert all_items.status_code == 200, all_items.text
        page = all_items.json()
        assert page["total"] == 3 and len(page["items"]) == 3
        assert all("description" not in item for item in page["items"])
        page_one = client.get(queue, headers=headers, params={"q": suffix[:8], "page_size": 1, "page": 1}).json()
        page_two = client.get(queue, headers=headers, params={"q": suffix[:8], "page_size": 1, "page": 2}).json()
        assert page_one["total"] == page_two["total"] == 3
        assert not ({item["id"] for item in page_one["items"]} & {item["id"] for item in page_two["items"]})
        sources = {item["id"]: item["source"] for item in page["items"]}
        assert sources == {manual_id: "manual", ai_id: "ai", legacy_id: "legacy"}
        for source, expected in (("manual", manual_id), ("ai", ai_id), ("legacy", legacy_id)):
            filtered = client.get(queue, headers=headers, params={"q": suffix[:8], "source": source, "page_size": 20}).json()
            exported = client.get(queue + "/export", headers=headers, params={"q": suffix[:8], "source": source}).json()
            assert filtered["total"] == 1 and [item["id"] for item in filtered["items"]] == [expected]
            assert exported["total"] == 1 and [item["id"] for item in exported["items"]] == [expected]
        assert client.get(queue, headers=headers, params={"source": "other"}).status_code == 422
        assert client.get(queue + "/export", headers=headers, params={"source": "other"}).status_code == 422
        combo = client.get(queue, headers=headers, params={"source": "manual", "status": "OPEN"}).json()
        assert combo["total"] == 1 and combo["items"][0]["id"] == manual_id
        detail = client.get(f"/api/v1/helpdesk/tickets/{legacy_id}", headers=headers).json()["ticket"]
        assert detail["source"] == "legacy"

        mine = "/api/v1/helpdesk/my-tickets"
        assert client.get(mine, headers=headers, params={"q": f"Public description needle%_ {suffix}"}).json()["total"] == 1
        assert client.get(mine, headers=headers, params={"q": f"needle%{suffix}"}).json()["total"] == 0
        assert client.get(mine, headers=headers, params={"q": f"needle__ {suffix}"}).json()["total"] == 0
        assert client.get(mine, headers=headers, params={"q": f"needle%_ {suffix}", "source": "manual"}).json()["total"] == 1
        assert client.get(mine, headers=headers, params={"q": f"AI question needle%_ {suffix}", "source": "ai"}).json()["total"] == 1
        assert client.get(mine, headers=headers, params={"q": f"secret-internal-{suffix}"}).json()["total"] == 0
        assert client.get(mine, headers=headers, params={"q": suffix[:8], "status": "CLOSED"}).json()["total"] == 0
        assert client.get(mine, headers=headers, params={"source": "legacy"}).status_code == 422
        invite = client.post("/api/v1/auth/invitations", headers=headers, json={"email": f"colleague-{suffix}@example.com"})
        assert invite.status_code == 201, invite.text
        colleague = client.post("/api/v1/auth/invitations/accept", json={"email": f"colleague-{suffix}@example.com",
            "password": password, "full_name": "Colleague", "token": invite.json()["token"]}).json()
        colleague_headers = {"Authorization": "Bearer " + colleague["access_token"]}
        assert client.get(mine, headers=colleague_headers, params={"q": suffix[:8]}).json()["total"] == 0

        views = "/api/v1/helpdesk/queue-views"
        legacy_filters = {"q": "", "status": None, "priority": None, "assignment": "all", "sla": None, "page_size": 20}
        legacy_request = {"request_id": str(uuid4()), "name": "legacy empty source", "filters": legacy_filters}
        created_view = client.post(views, headers=headers, json=legacy_request)
        assert created_view.status_code == 201, created_view.text
        replay = client.post(views, headers=headers, json={**legacy_request, "filters": {**legacy_filters, "source": None}})
        assert replay.status_code == 201 and replay.json()["cached"] is True
        source_request = {"request_id": str(uuid4()), "name": "source view",
            "filters": {**legacy_filters, "source": "ai"}}
        source_view = client.post(views, headers=headers, json=source_request)
        assert source_view.status_code == 201, source_view.text
        view_id = source_view.json()["view"]["id"]
        updated = client.put(f"{views}/{view_id}", headers=headers, json={"expected_version": 1,
            "name": "source view", "filters": {**legacy_filters, "source": "manual"}})
        assert updated.status_code == 200
        assert updated.json()["view"]["filters"]["source"] == "manual"
