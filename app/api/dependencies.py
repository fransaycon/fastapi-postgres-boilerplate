import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PaginationParams
from app.core.permissions import Permission, has_permission
from app.core.security import TokenError, decode_token
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.services.user_service import UserService

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_user_service(session: DbSession) -> UserService:
    return UserService(UserRepository(session))


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


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

    # Exposed so the rate limiter can key on the authenticated principal.
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
