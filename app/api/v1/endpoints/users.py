import uuid

from fastapi import APIRouter, Depends, Request, status

from app.api.dependencies import (
    CurrentUser,
    PaginationDep,
    UserServiceDep,
    require_permission,
)
from app.core.config import settings
from app.core.pagination import Page
from app.core.permissions import Permission
from app.core.rate_limit import limiter
from app.schemas.user import (
    PasswordUpdate,
    UserAdminCreate,
    UserAdminUpdate,
    UserMe,
    UserPublic,
    UserSelfUpdate,
)

router = APIRouter(prefix="/users", tags=["users"])

RequireUsersRead = Depends(require_permission(Permission.USERS_READ))
RequireUsersWrite = Depends(require_permission(Permission.USERS_WRITE))
RequireUsersDelete = Depends(require_permission(Permission.USERS_DELETE))


@router.get("/me", response_model=UserMe)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def read_current_user(request: Request, current_user: CurrentUser) -> UserMe:
    return UserMe.from_user(current_user)


@router.patch("/me", response_model=UserPublic)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def update_current_user(
    request: Request,
    payload: UserSelfUpdate,
    current_user: CurrentUser,
    service: UserServiceDep,
) -> UserPublic:
    user = await service.update_self(current_user.id, payload)
    return UserPublic.model_validate(user)


@router.get("", response_model=Page[UserPublic], dependencies=[RequireUsersRead])
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def list_users(
    request: Request,
    service: UserServiceDep,
    pagination: PaginationDep,
) -> Page[UserPublic]:
    page = await service.list(pagination)
    return page.map(UserPublic.model_validate)


@router.post(
    "",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[RequireUsersWrite],
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def create_user(
    request: Request,
    payload: UserAdminCreate,
    service: UserServiceDep,
) -> UserPublic:
    user = await service.create_as_admin(payload)
    return UserPublic.model_validate(user)


@router.get("/{user_id}", response_model=UserPublic, dependencies=[RequireUsersRead])
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def read_user(
    request: Request,
    user_id: uuid.UUID,
    service: UserServiceDep,
) -> UserPublic:
    user = await service.get(user_id)
    return UserPublic.model_validate(user)


@router.patch("/{user_id}", response_model=UserPublic, dependencies=[RequireUsersWrite])
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def update_user(
    request: Request,
    user_id: uuid.UUID,
    payload: UserAdminUpdate,
    service: UserServiceDep,
) -> UserPublic:
    user = await service.update_as_admin(user_id, payload)
    return UserPublic.model_validate(user)


@router.patch(
    "/{user_id}/password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[RequireUsersWrite],
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def update_user_password(
    request: Request,
    user_id: uuid.UUID,
    payload: PasswordUpdate,
    service: UserServiceDep,
) -> None:
    await service.set_password(user_id, payload.password)


@router.delete("/{user_id}", response_model=UserPublic, dependencies=[RequireUsersDelete])
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def delete_user(
    request: Request,
    user_id: uuid.UUID,
    current_user: CurrentUser,
    service: UserServiceDep,
) -> UserPublic:
    """Soft delete: anonymizes the email and deactivates the account."""
    user = await service.soft_delete(user_id, acting_user_id=current_user.id)
    return UserPublic.model_validate(user)
