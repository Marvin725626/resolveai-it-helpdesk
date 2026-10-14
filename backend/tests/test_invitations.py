import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.invitation import Invitation
from app.models.user import User


@pytest_asyncio.fixture(scope="module", autouse=True)
async def initialize_schema():
    from app.core.database import init_db
    await init_db()


@pytest.mark.asyncio
async def test_invitation_acceptance_is_one_time_case_insensitive_and_same_tenant():
    suffix = uuid.uuid4().hex[:12]
    owner_email = f"owner-{suffix}@example.com"
    invited_email = f"agent-{suffix}@example.com"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        registered = await client.post("/api/v1/auth/register", json={
            "email": owner_email.upper(), "password": "Password123!", "full_name": "Workspace Owner",
            "tenant_name": f"Invite Test {suffix}", "tenant_slug": f"invite-test-{suffix}",
        })
        assert registered.status_code == 201
        owner_token = registered.json()["access_token"]
        headers = {"Authorization": f"Bearer {owner_token}"}

        created = await client.post("/api/v1/auth/invitations", headers=headers, json={"email": invited_email.upper()})
        assert created.status_code == 201
        invitation = created.json()
        raw_token = invitation["token"]
        assert len(raw_token) >= 43

        async with AsyncSessionLocal() as db:
            row = (await db.execute(select(Invitation).where(Invitation.id == invitation["id"]))).scalar_one()
            assert row.token_hash != raw_token
            assert len(row.token_hash) == 64

        lookup = await client.post("/api/v1/auth/invitations/lookup", json={"token": raw_token})
        assert lookup.status_code == 200
        assert lookup.json() == {"valid": True}
        invalid_lookup = await client.post("/api/v1/auth/invitations/lookup", json={"token": "x" * 43})
        assert invalid_lookup.status_code == 404
        assert "email" not in invalid_lookup.text.lower()

        accepted = await client.post("/api/v1/auth/invitations/accept", json={
            "token": raw_token, "email": invited_email.upper(), "full_name": "Casey Agent", "password": "AgentPass123!",
        })
        assert accepted.status_code == 200
        invited_user = accepted.json()["user"]
        assert invited_user["email"] == invited_email
        assert invited_user["tenant_id"] == registered.json()["user"]["tenant_id"]
        assert invited_user["role"] == "SUPPORT_AGENT"

        replay = await client.post("/api/v1/auth/invitations/accept", json={
            "token": raw_token, "email": invited_email, "full_name": "Casey Agent", "password": "AgentPass123!",
        })
        assert replay.status_code == 400
        login = await client.post("/api/v1/auth/login", json={"email": invited_email.upper(), "password": "AgentPass123!"})
        assert login.status_code == 200
        assert login.json()["user"]["id"] == invited_user["id"]

        async with AsyncSessionLocal() as db:
            matches = await db.execute(select(func.count(User.id)).where(func.lower(User.email) == invited_email))
            assert matches.scalar_one() == 1


@pytest.mark.asyncio
async def test_invitation_management_role_and_revoke():
    suffix = uuid.uuid4().hex[:12]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        registered = await client.post("/api/v1/auth/register", json={
            "email": f"owner-{suffix}@example.com", "password": "Password123!", "full_name": "Workspace Owner",
            "tenant_name": f"Revoke Test {suffix}", "tenant_slug": f"revoke-test-{suffix}",
        })
        owner_headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
        invite = await client.post("/api/v1/auth/invitations", headers=owner_headers, json={"email": f"agent-{suffix}@example.com"})
        assert invite.status_code == 201

        # A logged-in non-manager cannot list or create invitations.
        accepted = await client.post("/api/v1/auth/invitations/accept", json={
            "token": invite.json()["token"], "email": f"agent-{suffix}@example.com", "full_name": "Support Agent", "password": "AgentPass123!",
        })
        assert accepted.status_code == 200
        agent_headers = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
        assert (await client.get("/api/v1/auth/invitations", headers=agent_headers)).status_code == 403

        duplicate = await client.post("/api/v1/auth/invitations", headers=owner_headers, json={"email": f"AGENT-{suffix}@example.com"})
        assert duplicate.status_code == 409
        pending = await client.post("/api/v1/auth/invitations", headers=owner_headers, json={"email": f"revoke-{suffix}@example.com"})
        assert pending.status_code == 201
        revoked = await client.delete(f"/api/v1/auth/invitations/{pending.json()['id']}", headers=owner_headers)
        assert revoked.status_code == 200
        lookup = await client.post("/api/v1/auth/invitations/lookup", json={"token": pending.json()["token"]})
        assert lookup.status_code == 404
        history = await client.get("/api/v1/auth/invitations", headers=owner_headers)
        assert history.status_code == 200
        assert history.json()["invitations"][0]["status"] == "revoked"


@pytest.mark.asyncio
async def test_invitation_expiry_and_workspace_isolation():
    suffix = uuid.uuid4().hex[:12]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        owner_a = await client.post("/api/v1/auth/register", json={
            "email": f"owner-a-{suffix}@example.com", "password": "Password123!", "full_name": "Owner A",
            "tenant_name": f"Tenant A {suffix}", "tenant_slug": f"tenant-a-{suffix}",
        })
        owner_b = await client.post("/api/v1/auth/register", json={
            "email": f"owner-b-{suffix}@example.com", "password": "Password123!", "full_name": "Owner B",
            "tenant_name": f"Tenant B {suffix}", "tenant_slug": f"tenant-b-{suffix}",
        })
        assert owner_a.status_code == 201, owner_a.text
        assert owner_b.status_code == 201, owner_b.text
        headers_a = {"Authorization": f"Bearer {owner_a.json()['access_token']}"}
        headers_b = {"Authorization": f"Bearer {owner_b.json()['access_token']}"}
        invite_a = await client.post("/api/v1/auth/invitations", headers=headers_a, json={"email": f"agent-a-{suffix}@example.com"})
        invite_b = await client.post("/api/v1/auth/invitations", headers=headers_b, json={"email": f"agent-b-{suffix}@example.com"})
        assert invite_a.status_code == invite_b.status_code == 201

        roster_a = await client.get("/api/v1/auth/invitations", headers=headers_a)
        emails_a = {member["email"] for member in roster_a.json()["members"]}
        emails_a |= {invite["email"] for invite in roster_a.json()["invitations"]}
        assert f"agent-a-{suffix}@example.com" in emails_a
        assert f"agent-b-{suffix}@example.com" not in emails_a
        assert (await client.delete(f"/api/v1/auth/invitations/{invite_b.json()['id']}", headers=headers_a)).status_code == 404
        assert (await client.post("/api/v1/auth/invitations/lookup", json={"token": invite_b.json()["token"]})).status_code == 200

        async with AsyncSessionLocal() as db:
            row = (await db.execute(select(Invitation).where(Invitation.id == invite_a.json()["id"]))).scalar_one()
            await db.execute(update(Invitation).where(Invitation.id == row.id).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
            await db.commit()

        expired_lookup = await client.post("/api/v1/auth/invitations/lookup", json={"token": invite_a.json()["token"]})
        assert expired_lookup.status_code == 404
        expired_accept = await client.post("/api/v1/auth/invitations/accept", json={
            "token": invite_a.json()["token"], "email": f"agent-a-{suffix}@example.com",
            "full_name": "Expired Agent", "password": "AgentPass123!",
        })
        assert expired_accept.status_code == 400
        history = await client.get("/api/v1/auth/invitations", headers=headers_a)
        expired_row = next(item for item in history.json()["invitations"] if item["id"] == invite_a.json()["id"])
        assert expired_row["status"] == "expired"


@pytest.mark.asyncio
async def test_simultaneous_acceptance_consumes_invitation_once():
    suffix = uuid.uuid4().hex[:12]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        registered = await client.post("/api/v1/auth/register", json={
            "email": f"concurrent-owner-{suffix}@example.com", "password": "Password123!", "full_name": "Owner",
            "tenant_name": f"Concurrent {suffix}", "tenant_slug": f"concurrent-{suffix}",
        })
        assert registered.status_code == 201, registered.text
        headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
        created = await client.post("/api/v1/auth/invitations", headers=headers, json={"email": f"concurrent-agent-{suffix}@example.com"})
        assert created.status_code == 201, created.text
        payload = {
            "token": created.json()["token"], "email": f"concurrent-agent-{suffix}@example.com",
            "full_name": "Concurrent Agent", "password": "AgentPass123!",
        }
        responses = await asyncio.gather(
            client.post("/api/v1/auth/invitations/accept", json=payload),
            client.post("/api/v1/auth/invitations/accept", json=payload),
        )
        assert sorted(response.status_code for response in responses) == [200, 400]
        async with AsyncSessionLocal() as db:
            count = await db.scalar(select(func.count(User.id)).where(func.lower(User.email) == payload["email"]))
            assert count == 1
