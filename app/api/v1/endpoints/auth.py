import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import (
    AuditServiceDep,
    ClientInfoDep,
    CurrentUser,
    SessionServiceDep,
    UserServiceDep,
)
from app.core.audit import AuditAction
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.rate_limit import limiter
from app.core.security import TokenError, create_access_token, decode_token
from app.schemas.session import SessionPublic
from app.schemas.user import Token

router = APIRouter(prefix="/auth", tags=["auth"])

ACCESS_TOKEN_TTL_SECONDS = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
REFRESH_TOKEN_TTL_SECONDS = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
REFRESH_COOKIE_PATH = f"{settings.API_V1_PREFIX}/auth"

RefreshCookie = Annotated[str | None, Cookie(alias=settings.REFRESH_COOKIE_NAME)]


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=token,
        max_age=REFRESH_TOKEN_TTL_SECONDS,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path=REFRESH_COOKIE_PATH,
    )


def _read_refresh_token(token: str | None) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Return (user_id, session_id, token_version) or raise."""
    if not token:
        raise AuthenticationError("Missing refresh token")
    try:
        payload = decode_token(token, expected_type="refresh")
        return (
            uuid.UUID(payload["sub"]),
            uuid.UUID(payload["sid"]),
            uuid.UUID(payload["ver"]),
        )
    except (TokenError, ValueError, KeyError) as exc:
        raise AuthenticationError("Invalid refresh token") from exc


@router.post("/login", response_model=Token)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def login(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    service: UserServiceDep,
    sessions: SessionServiceDep,
    audit: AuditServiceDep,
    client: ClientInfoDep,
) -> Token:
    """OAuth2 password flow — the `username` field carries the user's email."""
    user = await service.authenticate(form_data.username, form_data.password)
    audit.record(AuditAction.USER_LOGIN, actor_id=user.id, resource_id=user.id)
    _, refresh_token = await sessions.start(user.id, client)
    _set_refresh_cookie(response, refresh_token)
    return Token(
        access_token=create_access_token(str(user.id)),
        expires_in=ACCESS_TOKEN_TTL_SECONDS,
    )


@router.post("/refresh", response_model=Token)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def refresh(
    request: Request,
    response: Response,
    service: UserServiceDep,
    sessions: SessionServiceDep,
    client: ClientInfoDep,
    refresh_token: RefreshCookie = None,
) -> Token:
    user_id, session_id, token_version = _read_refresh_token(refresh_token)

    user = await service.repository.get_by_id(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Invalid refresh token")

    # Rotates `ver`; replaying a superseded token revokes the session instead.
    _, new_token = await sessions.rotate(user_id, session_id, token_version, client)
    _set_refresh_cookie(response, new_token)
    return Token(
        access_token=create_access_token(str(user.id)),
        expires_in=ACCESS_TOKEN_TTL_SECONDS,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    sessions: SessionServiceDep,
    refresh_token: RefreshCookie = None,
) -> None:
    """Revokes only the session this device holds. Idempotent."""
    if refresh_token:
        try:
            _, session_id, _ = _read_refresh_token(refresh_token)
        except AuthenticationError:
            session_id = None
        if session_id is not None:
            await sessions.end(session_id)
    _clear_refresh_cookie(response)


@router.get("/sessions", response_model=list[SessionPublic])
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def list_sessions(
    request: Request,
    current_user: CurrentUser,
    sessions: SessionServiceDep,
) -> list[SessionPublic]:
    active = await sessions.list_for_user(current_user.id)
    return [SessionPublic.model_validate(item) for item in active]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def revoke_session(
    request: Request,
    session_id: uuid.UUID,
    current_user: CurrentUser,
    sessions: SessionServiceDep,
) -> None:
    await sessions.end_for_user(current_user.id, session_id)
