import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant, require_roles
from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash, validate_password_strength
from app.models.invitation import Invitation
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.auth import Token, UserResponse

router = APIRouter(prefix="/auth/invitations", tags=["Invitations"])
MANAGERS = [UserRole.TENANT_OWNER, UserRole.TENANT_ADMIN]
INVALID_INVITATION = "This invitation is invalid, expired, revoked, or already used."


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class InviteCreate(BaseModel):
    email: EmailStr


class TokenRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class InviteAccept(TokenRequest):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        validate_password_strength(value)
        return value

    @field_validator("full_name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Display name is required.")
        return value


@router.get("")
async def list_invitations(
    tenant: Tenant = Depends(get_current_tenant),
    _manager: User = Depends(require_roles(MANAGERS)),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Invitation).where(Invitation.tenant_id == tenant.id).order_by(Invitation.created_at.desc())
    )
    rows = result.scalars().all()
    invitations = []
    for row in rows:
        if row.consumed_at:
            state = "accepted"
        elif row.revoked_at:
            state = "revoked"
        elif _aware(row.expires_at) <= now:
            state = "expired"
        else:
            state = "pending"
        invitations.append({
            "id": row.id,
            "email": row.email,
            "status": state,
            "created_at": row.created_at,
            "expires_at": row.expires_at,
            "consumed_at": row.consumed_at,
            "revoked_at": row.revoked_at,
        })
    members_result = await db.execute(
        select(User).where(User.tenant_id == tenant.id).order_by(User.created_at.asc())
    )
    members = [
        {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role.value,
         "is_active": user.is_active, "created_at": user.created_at}
        for user in members_result.scalars().all()
    ]
    return {"members": members, "invitations": invitations}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_invitation(
    data: InviteCreate,
    tenant: Tenant = Depends(get_current_tenant),
    manager: User = Depends(require_roles(MANAGERS)),
    db: AsyncSession = Depends(get_db),
):
    email = str(data.email).strip().lower()
    existing = await db.execute(select(User.id).where(func.lower(User.email) == email).limit(1))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    now = datetime.now(timezone.utc)
    pending = await db.execute(
        select(Invitation.id).where(
            Invitation.tenant_id == tenant.id,
            func.lower(Invitation.email) == email,
            Invitation.consumed_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > now,
        ).limit(1)
    )
    if pending.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A pending invitation already exists for this email.")

    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation(
        tenant_id=tenant.id,
        email=email,
        token_hash=_token_hash(raw_token),
        invited_by_user_id=manager.id,
        created_at=now,
        expires_at=now + timedelta(hours=48),
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)
    # The raw token is returned only at creation time and is never persisted.
    return {
        "id": invitation.id,
        "email": invitation.email,
        "token": raw_token,
        "expires_at": invitation.expires_at,
        "delivery": "Copy this link and send it to the invitee. No email is sent.",
    }


@router.delete("/{invitation_id}")
async def revoke_invitation(
    invitation_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    _manager: User = Depends(require_roles(MANAGERS)),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(Invitation)
        .where(
            Invitation.id == invitation_id,
            Invitation.tenant_id == tenant.id,
            Invitation.consumed_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > now,
        )
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    if result.rowcount != 1:
        raise HTTPException(status_code=404, detail="Pending invitation not found.")
    return {"ok": True}


@router.post("/lookup")
async def lookup_invitation(data: TokenRequest, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Invitation.id)
        .join(Tenant, Tenant.id == Invitation.tenant_id)
        .where(
            Invitation.token_hash == _token_hash(data.token),
            Invitation.consumed_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > now,
            Tenant.is_active.is_(True),
        )
        .limit(1)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=INVALID_INVITATION)
    # Do not disclose invitee email, workspace, or account existence here.
    return {"valid": True}


@router.post("/accept", response_model=Token)
async def accept_invitation(data: InviteAccept, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    token_digest = _token_hash(data.token)
    invite_result = await db.execute(
        select(Invitation)
        .join(Tenant, Tenant.id == Invitation.tenant_id)
        .where(
            Invitation.token_hash == token_digest,
            Invitation.consumed_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > now,
            Tenant.is_active.is_(True),
        )
        .limit(1)
    )
    invitation = invite_result.scalar_one_or_none()
    email = str(data.email).strip().lower()
    if invitation is None or invitation.email.lower() != email:
        await db.rollback()
        raise HTTPException(status_code=400, detail=INVALID_INVITATION)

    existing = await db.execute(select(User.id).where(func.lower(User.email) == email).limit(1))
    if existing.scalar_one_or_none():
        await db.rollback()
        raise HTTPException(status_code=400, detail=INVALID_INVITATION)

    # Claim in the same transaction as account creation. The predicate makes
    # simultaneous acceptance attempts for one token mutually exclusive.
    claim = await db.execute(
        update(Invitation)
        .where(
            Invitation.id == invitation.id,
            Invitation.consumed_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > now,
        )
        .values(consumed_at=now)
        .execution_options(synchronize_session=False)
    )
    if claim.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=400, detail=INVALID_INVITATION)

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == invitation.tenant_id, Tenant.is_active.is_(True)))
    tenant = tenant_result.scalar_one_or_none()
    if tenant is None:
        await db.rollback()
        raise HTTPException(status_code=400, detail=INVALID_INVITATION)

    user = User(
        tenant_id=tenant.id,
        email=email,
        full_name=data.full_name,
        hashed_password=get_password_hash(data.password),
        role=UserRole.SUPPORT_AGENT,
        is_active=True,
    )
    db.add(user)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail=INVALID_INVITATION)
    await db.refresh(user)
    access_token = create_access_token(subject=user.id, tenant_id=tenant.id, role=user.role.value)
    return Token(access_token=access_token, user=UserResponse.model_validate(user))
