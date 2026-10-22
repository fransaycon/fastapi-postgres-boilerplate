import uuid

from httpx import AsyncClient

from app.core.permissions import ROLE_PERMISSIONS, Permission, Role, has_permission
from app.models.user import User
from app.services.user_service import DELETED_EMAIL_DOMAIN
from tests.conftest import TEST_PASSWORD

USERS = "/api/v1/users"
NEW_PASSWORD = "another-very-long-password"


def test_role_permission_map_is_explicit() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)
    assert has_permission(Role.ADMIN, Permission.USERS_DELETE)
    assert not has_permission(Role.USER, Permission.USERS_READ)
    # Both roles can manage their own profile.
    assert has_permission(Role.USER, Permission.PROFILE_WRITE)


async def test_me_exposes_resolved_permissions(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    body = (await client.get(f"{USERS}/me", headers=auth_headers)).json()
    assert body["role"] == Role.USER
    assert body["permissions"] == sorted([Permission.PROFILE_READ, Permission.PROFILE_WRITE])


async def test_admin_endpoints_are_forbidden_for_regular_users(
    client: AsyncClient, auth_headers: dict[str, str], test_user: User
) -> None:
    assert (await client.get(USERS, headers=auth_headers)).status_code == 403
    assert (await client.get(f"{USERS}/{test_user.id}", headers=auth_headers)).status_code == 403
    assert (
        await client.post(
            USERS, headers=auth_headers, json={"email": "x@example.com", "password": NEW_PASSWORD}
        )
    ).status_code == 403
    assert (await client.delete(f"{USERS}/{test_user.id}", headers=auth_headers)).status_code == 403


async def test_admin_endpoints_require_authentication(client: AsyncClient) -> None:
    assert (await client.get(USERS)).status_code == 401


async def test_list_users_is_paginated(
    client: AsyncClient, admin_headers: dict[str, str], test_user: User
) -> None:
    response = await client.get(USERS, headers=admin_headers, params={"page": 1, "size": 1})
    assert response.status_code == 200

    body = response.json()
    assert body["total"] == 2  # admin + regular user
    assert body["page"] == 1
    assert body["size"] == 1
    assert body["pages"] == 2
    assert len(body["items"]) == 1
    assert "hashed_password" not in body["items"][0]


async def test_list_users_second_page_has_no_overlap(
    client: AsyncClient, admin_headers: dict[str, str], test_user: User
) -> None:
    first = await client.get(USERS, headers=admin_headers, params={"size": 1, "page": 1})
    second = await client.get(USERS, headers=admin_headers, params={"size": 1, "page": 2})
    assert first.json()["items"][0]["id"] != second.json()["items"][0]["id"]


async def test_list_users_rejects_invalid_pagination(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    assert (await client.get(USERS, headers=admin_headers, params={"page": 0})).status_code == 422
    assert (await client.get(USERS, headers=admin_headers, params={"size": 999})).status_code == 422


async def test_admin_can_create_user_with_role(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        USERS,
        headers=admin_headers,
        json={"email": "Created@Example.com", "password": NEW_PASSWORD, "role": Role.ADMIN},
    )
    assert response.status_code == 201

    body = response.json()
    assert body["email"] == "created@example.com"
    assert body["role"] == Role.ADMIN
    assert "password" not in body
    assert "hashed_password" not in body


async def test_admin_cannot_create_duplicate_email(
    client: AsyncClient, admin_headers: dict[str, str], test_user: User
) -> None:
    response = await client.post(
        USERS, headers=admin_headers, json={"email": test_user.email, "password": NEW_PASSWORD}
    )
    assert response.status_code == 409


async def test_admin_can_read_user_by_id(
    client: AsyncClient, admin_headers: dict[str, str], test_user: User
) -> None:
    response = await client.get(f"{USERS}/{test_user.id}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["id"] == str(test_user.id)


async def test_read_unknown_user_returns_404(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.get(f"{USERS}/{uuid.uuid4()}", headers=admin_headers)
    assert response.status_code == 404


async def test_admin_can_update_email_and_role(
    client: AsyncClient, admin_headers: dict[str, str], test_user: User
) -> None:
    response = await client.patch(
        f"{USERS}/{test_user.id}",
        headers=admin_headers,
        json={"email": "moved@example.com", "role": Role.ADMIN},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["email"] == "moved@example.com"
    assert body["role"] == Role.ADMIN


async def test_admin_update_rejects_taken_email(
    client: AsyncClient, admin_headers: dict[str, str], admin_user: User, test_user: User
) -> None:
    response = await client.patch(
        f"{USERS}/{test_user.id}", headers=admin_headers, json={"email": admin_user.email}
    )
    assert response.status_code == 409


async def test_admin_can_change_a_users_password(
    client: AsyncClient, admin_headers: dict[str, str], test_user: User
) -> None:
    response = await client.patch(
        f"{USERS}/{test_user.id}/password",
        headers=admin_headers,
        json={"password": NEW_PASSWORD},
    )
    assert response.status_code == 204

    old = await client.post(
        "/api/v1/auth/login", data={"username": test_user.email, "password": TEST_PASSWORD}
    )
    assert old.status_code == 401

    new = await client.post(
        "/api/v1/auth/login", data={"username": test_user.email, "password": NEW_PASSWORD}
    )
    assert new.status_code == 200


async def test_password_update_enforces_minimum_length(
    client: AsyncClient, admin_headers: dict[str, str], test_user: User
) -> None:
    response = await client.patch(
        f"{USERS}/{test_user.id}/password", headers=admin_headers, json={"password": "short"}
    )
    assert response.status_code == 422


async def test_delete_is_soft_and_anonymizes_email(
    client: AsyncClient, admin_headers: dict[str, str], test_user: User
) -> None:
    original_email = test_user.email
    response = await client.delete(f"{USERS}/{test_user.id}", headers=admin_headers)
    assert response.status_code == 200

    body = response.json()
    assert body["deleted_at"] is not None
    assert body["is_active"] is False
    assert body["email"].endswith(f"@{DELETED_EMAIL_DOMAIN}")
    assert original_email not in body["email"]

    # Hidden from reads and listings, but the row still exists.
    assert (await client.get(f"{USERS}/{test_user.id}", headers=admin_headers)).status_code == 404
    assert (await client.get(USERS, headers=admin_headers)).json()["total"] == 1


async def test_deleted_user_cannot_log_in(
    client: AsyncClient, admin_headers: dict[str, str], test_user: User
) -> None:
    await client.delete(f"{USERS}/{test_user.id}", headers=admin_headers)
    response = await client.post(
        "/api/v1/auth/login", data={"username": test_user.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 401


async def test_email_is_reusable_after_soft_delete(
    client: AsyncClient, admin_headers: dict[str, str], test_user: User
) -> None:
    original_email = test_user.email
    await client.delete(f"{USERS}/{test_user.id}", headers=admin_headers)
    response = await client.post(
        USERS, headers=admin_headers, json={"email": original_email, "password": NEW_PASSWORD}
    )
    assert response.status_code == 201


async def test_admin_cannot_delete_themselves(
    client: AsyncClient, admin_headers: dict[str, str], admin_user: User
) -> None:
    response = await client.delete(f"{USERS}/{admin_user.id}", headers=admin_headers)
    assert response.status_code == 409


async def test_deleting_twice_returns_404(
    client: AsyncClient, admin_headers: dict[str, str], test_user: User
) -> None:
    assert (
        await client.delete(f"{USERS}/{test_user.id}", headers=admin_headers)
    ).status_code == 200
    assert (
        await client.delete(f"{USERS}/{test_user.id}", headers=admin_headers)
    ).status_code == 404
