"""Per-device refresh sessions: scoped logout, reuse detection, password invalidation."""

from httpx import AsyncClient

from app.core.devices import UNKNOWN_DEVICE, describe_device
from app.models.user import User
from tests.conftest import TEST_PASSWORD

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
SESSIONS = "/api/v1/auth/sessions"
CHROME_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0"
FIREFOX_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"


def test_describe_device() -> None:
    assert describe_device(CHROME_MAC) == "Chrome on macOS"
    assert describe_device(FIREFOX_WIN) == "Firefox on Windows"
    # Edge and Opera also advertise "Chrome", so ordering matters.
    assert (
        describe_device("Mozilla/5.0 (Windows NT 10.0) Chrome/131.0 Edg/131.0") == "Edge on Windows"
    )
    assert describe_device(None) == UNKNOWN_DEVICE


async def _login(client: AsyncClient, user: User, user_agent: str) -> str:
    response = await client.post(
        LOGIN,
        data={"username": user.email, "password": TEST_PASSWORD},
        headers={"User-Agent": user_agent},
    )
    response.raise_for_status()
    return response.cookies[("refresh_token")]


async def test_login_records_the_device(
    client: AsyncClient, test_user: User, auth_headers: dict[str, str]
) -> None:
    await client.post(
        LOGIN,
        data={"username": test_user.email, "password": TEST_PASSWORD},
        headers={"User-Agent": CHROME_MAC},
    )
    sessions = (await client.get(SESSIONS, headers=auth_headers)).json()
    assert any(item["device_label"] == "Chrome on macOS" for item in sessions)
    assert all("token_version" not in item for item in sessions)


async def test_each_login_creates_its_own_session(
    client: AsyncClient, test_user: User, auth_headers: dict[str, str]
) -> None:
    await _login(client, test_user, CHROME_MAC)
    await _login(client, test_user, FIREFOX_WIN)

    labels = [
        item["device_label"] for item in (await client.get(SESSIONS, headers=auth_headers)).json()
    ]
    assert "Chrome on macOS" in labels
    assert "Firefox on Windows" in labels


async def test_logout_only_ends_the_calling_device(
    client: AsyncClient, test_user: User, auth_headers: dict[str, str]
) -> None:
    await _login(client, test_user, CHROME_MAC)
    before = len((await client.get(SESSIONS, headers=auth_headers)).json())

    # The client still holds the most recent refresh cookie.
    assert (await client.post(LOGOUT)).status_code == 204

    after = (await client.get(SESSIONS, headers=auth_headers)).json()
    assert len(after) == before - 1
    assert all(item["device_label"] != "Chrome on macOS" for item in after)


async def test_logout_without_a_cookie_is_idempotent(client: AsyncClient) -> None:
    assert (await client.post(LOGOUT)).status_code == 204


async def test_refresh_rotates_the_token_version(client: AsyncClient, test_user: User) -> None:
    first = await _login(client, test_user, CHROME_MAC)
    assert (await client.post(REFRESH)).status_code == 200
    second = client.cookies["refresh_token"]
    assert first != second


async def test_replaying_an_old_refresh_token_revokes_the_session(
    client: AsyncClient, test_user: User, auth_headers: dict[str, str]
) -> None:
    stale = await _login(client, test_user, CHROME_MAC)
    assert (await client.post(REFRESH)).status_code == 200

    client.cookies.set("refresh_token", stale)
    replay = await client.post(REFRESH)
    assert replay.status_code == 401
    assert "reuse" in replay.json()["detail"].lower()

    # The whole session is gone, so the rotated token is dead too.
    labels = [
        item["device_label"] for item in (await client.get(SESSIONS, headers=auth_headers)).json()
    ]
    assert "Chrome on macOS" not in labels


async def test_revoking_another_session_by_id(
    client: AsyncClient, test_user: User, auth_headers: dict[str, str]
) -> None:
    await _login(client, test_user, FIREFOX_WIN)
    sessions = (await client.get(SESSIONS, headers=auth_headers)).json()
    target = next(item for item in sessions if item["device_label"] == "Firefox on Windows")

    assert (
        await client.delete(f"{SESSIONS}/{target['id']}", headers=auth_headers)
    ).status_code == 204
    remaining = (await client.get(SESSIONS, headers=auth_headers)).json()
    assert target["id"] not in [item["id"] for item in remaining]


async def test_cannot_revoke_another_users_session(
    client: AsyncClient,
    test_user: User,
    auth_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    victim = (await client.get(SESSIONS, headers=auth_headers)).json()[0]
    response = await client.delete(f"{SESSIONS}/{victim['id']}", headers=admin_headers)
    assert response.status_code == 404


async def test_password_change_ends_every_session(
    client: AsyncClient,
    test_user: User,
    auth_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    await _login(client, test_user, CHROME_MAC)
    await _login(client, test_user, FIREFOX_WIN)
    assert len((await client.get(SESSIONS, headers=auth_headers)).json()) >= 2

    reset = await client.patch(
        f"/api/v1/users/{test_user.id}/password",
        headers=admin_headers,
        json={"password": "a-brand-new-long-password"},
    )
    assert reset.status_code == 204

    # Every refresh cookie is now worthless.
    assert (await client.post(REFRESH)).status_code == 401
    assert (await client.get(SESSIONS, headers=auth_headers)).json() == []


async def test_soft_delete_ends_every_session(
    client: AsyncClient, test_user: User, admin_headers: dict[str, str]
) -> None:
    await _login(client, test_user, CHROME_MAC)
    assert (
        await client.delete(f"/api/v1/users/{test_user.id}", headers=admin_headers)
    ).status_code == 200
    assert (await client.post(REFRESH)).status_code == 401


async def test_sessions_require_authentication(client: AsyncClient) -> None:
    assert (await client.get(SESSIONS)).status_code == 401
