import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import UserServiceDep
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.rate_limit import limiter
from app.core.security import TokenError, create_access_token, create_refresh_token, decode_token
from app.schemas.user import Token, UserCreate, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])

ACCESS_TOKEN_TTL_SECONDS = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
REFRESH_TOKEN_TTL_SECONDS = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
REFRESH_COOKIE_PATH = f"{settings.API_V1_PREFIX}/auth"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=token,
        max_age=REFRESH_TOKEN_TTL_SECONDS,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN or None,
        path=REFRESH_COOKIE_PATH,
    )


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def register(request: Request, payload: UserCreate, service: UserServiceDep) -> UserPublic:
    user = await service.register(payload)
    return UserPublic.model_validate(user)


@router.post("/login", response_model=Token)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def login(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    service: UserServiceDep,
) -> Token:
    """OAuth2 password flow — the `username` field carries the user's email."""
    user = await service.authenticate(form_data.username, form_data.password)
    _set_refresh_cookie(response, create_refresh_token(str(user.id)))
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
    refresh_token: Annotated[str | None, Cookie(alias=settings.REFRESH_COOKIE_NAME)] = None,
) -> Token:
    if not refresh_token:
        raise AuthenticationError("Missing refresh token")

    try:
        payload = decode_token(refresh_token, expected_type="refresh")
        user_id = uuid.UUID(payload["sub"])
    except (TokenError, ValueError, KeyError) as exc:
        raise AuthenticationError("Invalid refresh token") from exc

    user = await service.repository.get_by_id(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Invalid refresh token")

    # Rotate the refresh token on every use.
    _set_refresh_cookie(response, create_refresh_token(str(user.id)))
    return Token(
        access_token=create_access_token(str(user.id)),
        expires_in=ACCESS_TOKEN_TTL_SECONDS,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN or None,
        path=REFRESH_COOKIE_PATH,
    )
