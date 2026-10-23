from httpx import AsyncClient

from app.core.rate_limit import limiter
from app.models.user import User
from tests.conftest import TEST_PASSWORD


def test_limiter_is_enabled_during_tests() -> None:
    """Guards the slowapi decorator path, which only misbehaves when enabled."""
    assert limiter.enabled
    assert not limiter._headers_enabled


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_registration_endpoint_does_not_exist(client: AsyncClient) -> None:
    """Accounts are provisioned by admins via POST /users only."""
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "password": "a-very-long-password"},
    )
    assert response.status_code == 404


async def test_login_issues_tokens_and_refresh_cookie(client: AsyncClient, test_user: User) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": test_user.email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"

    cookie = response.cookies.get("refresh_token")
    assert cookie is not None
    assert "httponly" in response.headers["set-cookie"].lower()


async def test_login_with_wrong_password_fails(client: AsyncClient, test_user: User) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": test_user.email, "password": "definitely-wrong-password"},
    )
    assert response.status_code == 401


async def test_refresh_rotates_token(client: AsyncClient, test_user: User) -> None:
    await client.post(
        "/api/v1/auth/login",
        data={"username": test_user.email, "password": TEST_PASSWORD},
    )
    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_refresh_without_cookie_fails(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 401


async def test_me_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 401


async def test_me_returns_current_user(
    client: AsyncClient, test_user: User, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/users/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["email"] == test_user.email


async def test_access_token_is_rejected_as_refresh_token(
    client: AsyncClient, test_user: User, auth_headers: dict[str, str]
) -> None:
    access_token = auth_headers["Authorization"].removeprefix("Bearer ")
    client.cookies.set("refresh_token", access_token)
    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 401


async def test_list_users_requires_superuser(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/users", headers=auth_headers)
    assert response.status_code == 403
