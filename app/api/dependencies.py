import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PaginationParams
from app.core.permissions import Permission, has_permission
from app.core.security import TokenError, decode_token
from app.models.user import User
from app.repositories.audit_repo import AuditRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_service import AuditService
from app.services.session_service import ClientInfo, SessionService
from app.services.user_service import UserService

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_audit_service(session: DbSession) -> AuditService:
    return AuditService(AuditRepository(session))


AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]


def get_user_service(session: DbSession, audit: AuditServiceDep) -> UserService:
    return UserService(UserRepository(session), SessionRepository(session), audit)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


def get_session_service(session: DbSession) -> SessionService:
    return SessionService(SessionRepository(session))


SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]


def get_client_info(request: Request) -> ClientInfo:
    forwarded = request.headers.get("x-forwarded-for") if settings.TRUST_PROXY_HEADERS else None
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else None
    return ClientInfo(ip_address=ip, user_agent=request.headers.get("user-agent"))


ClientInfoDep = Annotated[ClientInfo, Depends(get_client_info)]


def get_pagination(
    page: Annotated[int, Query(ge=1, description="1-based page number")] = 1,
    size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PaginationParams:
    return PaginationParams(page=page, size=size)


PaginationDep = Annotated[PaginationParams, Depends(get_pagination)]


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    service: UserServiceDep,
) -> User:
    if credentials is None:
        raise AuthenticationError("Not authenticated")

    try:
        payload = decode_token(credentials.credentials, expected_type="access")
        user_id = uuid.UUID(payload["sub"])
    except (TokenError, ValueError, KeyError) as exc:
        raise AuthenticationError("Could not validate credentials") from exc

    user = await service.repository.get_by_id(user_id)
    if user is None:
        raise AuthenticationError("Could not validate credentials")
    if not user.is_active:
        raise AuthenticationError("Inactive user")

    request.state.user_id = str(user.id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(permission: Permission) -> Callable[[User], Awaitable[User]]:
    """Build a dependency asserting the caller's role grants `permission`."""

    async def dependency(current_user: CurrentUser) -> User:
        if not has_permission(current_user.role, permission):
            raise PermissionDeniedError(f"Requires the '{permission}' permission")
        return current_user

    return dependency
