from typing import Generator, Optional, List
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.config import settings
from app.core.security import decode_access_token
from app.core.token_blacklist import is_token_revoked
from app.models.user import User, UserRole
from app.models.tenant import Tenant

security_scheme = HTTPBearer(auto_error=False)


def _requester_route_allowed(request: Request) -> bool:
    """Exact route/method allowlist for the employee-facing account."""
    route = request.scope.get("route")
    path = getattr(route, "path", "")
    method = request.method.upper()
    # Router prefixes may be applied during inclusion, so compare the registered
    # template with the exact API path suffix, never an open-ended prefix.
    prefix = settings.API_V1_STR.rstrip("/")
    if prefix and path.startswith(prefix + "/"):
        path = path[len(prefix):]
    fixed = {
        ("GET", "/auth/me"), ("POST", "/auth/logout"),
        ("GET", "/helpdesk/my-tickets"), ("POST", "/helpdesk/my-tickets"),
        ("GET", "/helpdesk/notifications"), ("POST", "/helpdesk/notifications/read-all"),
        ("GET", "/helpdesk/portal/overview"),
        ("GET", "/helpdesk/service-catalog"),
    }
    if (method, path) in fixed:
        return True
    if (method, path) == ("POST", "/helpdesk/notifications/{notification_id}/read"):
        return True
    if method == "GET" and path == "/helpdesk/service-catalog/{item_id}":
        return True
    if method == "POST" and path == "/helpdesk/service-catalog/{item_id}/submit":
        return True
    ticket_id = request.path_params.get("ticket_id")
    if not ticket_id:
        return False
    patterns = {
        ("GET", f"/helpdesk/my-tickets/{{ticket_id}}"),
        ("GET", f"/helpdesk/my-tickets/{{ticket_id}}/replies"),
        ("POST", f"/helpdesk/my-tickets/{{ticket_id}}/replies"),
        ("POST", f"/helpdesk/my-tickets/{{ticket_id}}/confirm-resolved"),
        ("POST", f"/helpdesk/my-tickets/{{ticket_id}}/reopen"),
        ("GET", f"/helpdesk/my-tickets/{{ticket_id}}/resolution"),
        ("POST", f"/helpdesk/my-tickets/{{ticket_id}}/satisfaction"),
        ("GET", f"/helpdesk/my-tickets/{{ticket_id}}/attachments"),
        ("POST", f"/helpdesk/my-tickets/{{ticket_id}}/attachments"),
        ("GET", f"/helpdesk/my-tickets/{{ticket_id}}/attachments/{{attachment_id}}/download"),
        ("DELETE", f"/helpdesk/my-tickets/{{ticket_id}}/attachments/{{attachment_id}}"),
    }
    if (method, path) in patterns:
        return True
    # The shared attachment router has a scope parameter in its template.
    return (method in {"GET", "POST", "DELETE"}
        and path in {"/helpdesk/{scope_kind}/{ticket_id}/attachments",
                     "/helpdesk/{scope_kind}/{ticket_id}/attachments/{attachment_id}/download",
                     "/helpdesk/{scope_kind}/{ticket_id}/attachments/{attachment_id}"}
        and request.path_params.get("scope_kind") == "my-tickets")


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Validates JWT access token and returns authenticated User."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = credentials.credentials
    if is_token_revoked(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    user_id = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    if not user_id or not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token claims.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    stmt = select(User).where(User.id == user_id, User.tenant_id == tenant_id, User.is_active == True)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive."
        )

    if user.role == UserRole.REQUESTER and not _requester_route_allowed(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requester access is limited to the employee portal.")
    return user


async def get_current_tenant(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Tenant:
    """Returns the authenticated tenant context for the current user."""
    stmt = select(Tenant).where(Tenant.id == current_user.tenant_id, Tenant.is_active == True)
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant workspace is disabled or does not exist."
        )

    return tenant


def require_roles(allowed_roles: List[UserRole]):
    """Role-Based Access Control (RBAC) dependency factory."""
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted. Required role in {[r.value for r in allowed_roles]}."
            )
        return current_user
    return role_checker
