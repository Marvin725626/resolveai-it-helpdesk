import uuid
import tempfile
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.core.database import Base, get_db
from app.main import app
from app.models.invitation import Invitation
from app.models.user import User

_test_sessions = None


@pytest_asyncio.fixture(scope="module", autouse=True)
async def initialize_schema():
    global _test_sessions
    temp_db = Path(tempfile.gettempdir()) / f"requester_roles_{uuid.uuid4().hex}.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{temp_db.as_posix()}")
    _test_sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async def isolated_db():
        async with _test_sessions() as session:
            yield session
    app.dependency_overrides[get_db] = isolated_db
    yield
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()
    temp_db.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_requester_invitation_scope_and_private_overview():
    suffix = uuid.uuid4().hex[:12]
    requester_email = f"requester-{suffix}@example.com"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        owner = await client.post("/api/v1/auth/register", json={
            "email": f"owner-{suffix}@example.com", "password": "Password123!", "full_name": "Owner",
            "tenant_name": f"Requester {suffix}", "tenant_slug": f"requester-{suffix}",
        })
        assert owner.status_code == 201, owner.text
        owner_headers = {"Authorization": f"Bearer {owner.json()['access_token']}"}

        forbidden_role = await client.post("/api/v1/auth/invitations", headers=owner_headers,
            json={"email": f"admin-{suffix}@example.com", "role": "TENANT_ADMIN"})
        assert forbidden_role.status_code == 422
        invite = await client.post("/api/v1/auth/invitations", headers=owner_headers,
            json={"email": requester_email, "role": "REQUESTER"})
        assert invite.status_code == 201, invite.text
        assert invite.json()["role"] == "REQUESTER"
        async with _test_sessions() as db:
            stored_invite = await db.scalar(select(Invitation).where(Invitation.id == invite.json()["id"]))
            assert stored_invite.role == "REQUESTER"

        accepted = await client.post("/api/v1/auth/invitations/accept", json={
            "token": invite.json()["token"], "email": requester_email, "full_name": "Requester",
            "password": "RequesterPass123!", "role": "TENANT_OWNER",
        })
        assert accepted.status_code == 200, accepted.text
        requester = accepted.json()["user"]
        assert requester["role"] == "REQUESTER"
        headers = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
        me = await client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 200 and me.json()["role"] == "REQUESTER"

        overview = await client.get("/api/v1/helpdesk/portal/overview", headers=headers)
        assert overview.status_code == 200, overview.text
        assert overview.json()["total"] == 0
        assert overview.json()["latest"] == []
        assert "description" not in overview.text

        # Requester credentials cannot enter legacy staff APIs or shared staff scopes.
        for method, path in (
            ("GET", "/api/v1/tickets"), ("POST", "/api/v1/tickets"),
            ("GET", "/api/v1/helpdesk/tickets"), ("POST", "/api/v1/helpdesk/runs"),
            ("GET", "/api/v1/helpdesk/analytics"),
            ("GET", f"/api/v1/helpdesk/tickets/{uuid.uuid4()}/attachments"),
            ("GET", "/api/v1/auth/invitations"),
        ):
            response = await client.request(method, path, headers=headers, json={} if method == "POST" else None)
            assert response.status_code == 403, (method, path, response.status_code, response.text)

        created = await client.post("/api/v1/helpdesk/my-tickets", headers=headers, json={
            "request_id": str(uuid.uuid4()), "subject": "Laptop cannot connect", "description": "The device cannot connect to the office network.",
            "category": "network",
        })
        assert created.status_code == 201, created.text
        ticket_id = created.json()["ticket_id"]
        detail = await client.get(f"/api/v1/helpdesk/my-tickets/{ticket_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert (await client.get(f"/api/v1/helpdesk/my-tickets/{ticket_id}/replies", headers=headers)).status_code == 200
        assert (await client.get(f"/api/v1/helpdesk/my-tickets/{ticket_id}/attachments", headers=headers)).status_code == 200
        assert (await client.get(f"/api/v1/helpdesk/my-tickets/{ticket_id}/resolution", headers=headers)).status_code == 200
        feedback = await client.post(f"/api/v1/helpdesk/my-tickets/{ticket_id}/satisfaction", headers=headers, json={
            "request_id": str(uuid.uuid4()), "resolution_id": str(uuid.uuid4()), "rating": 4, "comment": "Thanks",
        })
        assert feedback.status_code == 404  # Reached ownership-scoped handler; no matching resolution exists.
        assert (await client.get("/api/v1/helpdesk/notifications", headers=headers)).status_code == 200

        # A support agent resolves the request, then the requester confirms and rates it.
        support_invite = await client.post("/api/v1/auth/invitations", headers=owner_headers,
            json={"email": f"support-{suffix}@example.com"})
        support = await client.post("/api/v1/auth/invitations/accept", json={
            "token": support_invite.json()["token"], "email": f"support-{suffix}@example.com",
            "full_name": "Support", "password": "SupportPass123!",
        })
        support_headers = {"Authorization": f"Bearer {support.json()['access_token']}"}
        claimed = await client.post(f"/api/v1/helpdesk/tickets/{ticket_id}/claim", headers=support_headers,
            json={"expected_updated_at": detail.json()["ticket"]["updated_at"]})
        assert claimed.status_code == 200, claimed.text
        after_claim = await client.get(f"/api/v1/helpdesk/my-tickets/{ticket_id}", headers=headers)
        resolution = await client.post(f"/api/v1/helpdesk/tickets/{ticket_id}/resolve", headers=support_headers, json={
            "request_id": str(uuid.uuid4()), "expected_updated_at": after_claim.json()["ticket"]["updated_at"],
            "category": "software", "summary": "Network adapter reset", "steps": "Reset the network adapter.",
        })
        assert resolution.status_code == 201, resolution.text
        resolved_view = await client.get(f"/api/v1/helpdesk/my-tickets/{ticket_id}/resolution", headers=headers)
        assert resolved_view.status_code == 200 and resolved_view.json()["current"] is True
        confirmed = await client.post(f"/api/v1/helpdesk/my-tickets/{ticket_id}/confirm-resolved", headers=headers, json={
            "request_id": str(uuid.uuid4()), "expected_updated_at": resolution.json()["updated_at"],
        })
        assert confirmed.status_code == 200, confirmed.text
        satisfaction = await client.post(f"/api/v1/helpdesk/my-tickets/{ticket_id}/satisfaction", headers=headers, json={
            "request_id": str(uuid.uuid4()), "resolution_id": resolution.json()["resolution"]["id"],
            "rating": 5, "comment": "Resolved",
        })
        assert satisfaction.status_code == 201, satisfaction.text
        updated = await client.get("/api/v1/helpdesk/portal/overview", headers=headers)
        assert updated.status_code == 200 and updated.json()["total"] == 1
        assert "description" not in updated.text

        # Another employee in the same tenant cannot read this ticket.
        invite2 = await client.post("/api/v1/auth/invitations", headers=owner_headers,
            json={"email": f"other-{suffix}@example.com", "role": "REQUESTER"})
        other = await client.post("/api/v1/auth/invitations/accept", json={
            "token": invite2.json()["token"], "email": f"other-{suffix}@example.com", "full_name": "Other",
            "password": "RequesterPass123!",
        })
        other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
        hidden = await client.get(f"/api/v1/helpdesk/my-tickets/{ticket_id}", headers=other_headers)
        assert hidden.status_code == 404
