from httpx import AsyncClient
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit import AuditAction, build_changes
from app.core.pagination import PaginationParams
from app.core.permissions import Role
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.audit_service import AuditService
from tests.conftest import TEST_PASSWORD

USERS = "/api/v1/users"


async def _entries(session: AsyncSession) -> list[AuditLog]:
    result = await session.exec(select(AuditLog).order_by(col(AuditLog.created_at)))
    return list(result.all())


async def _count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(AuditLog)) or 0


def test_build_changes_skips_noops_and_secrets() -> None:
    user = User(email="a@example.com", hashed_password="old-hash", role=Role.USER)
    changes = build_changes(
        user,
        {"role": Role.ADMIN, "email": "a@example.com", "hashed_password": "new-hash"},
    )
    assert changes == [{"attribute": "role", "from": "user", "to": "admin"}]


async def test_login_is_audited(
    client: AsyncClient, db_session: AsyncSession, test_user: User
) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": test_user.email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200

    entries = await _entries(db_session)
    assert len(entries) == 1
    assert entries[0].action == AuditAction.USER_LOGIN
    assert entries[0].actor_id == test_user.id
    assert entries[0].resource_id == test_user.id
    assert entries[0].changes is None


async def test_failed_login_is_not_audited(
    client: AsyncClient, db_session: AsyncSession, test_user: User
) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": test_user.email, "password": "wrong-but-long-password"},
    )
    assert response.status_code == 401
    assert await _count(db_session) == 0


async def test_admin_update_records_changed_attributes(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_headers: dict[str, str],
    admin_user: User,
    test_user: User,
) -> None:
    response = await client.patch(
        f"{USERS}/{test_user.id}", headers=admin_headers, json={"role": Role.ADMIN}
    )
    assert response.status_code == 200

    updates = [e for e in await _entries(db_session) if e.action == AuditAction.USER_UPDATED]
    assert len(updates) == 1
    assert updates[0].actor_id == admin_user.id
    assert updates[0].resource_id == test_user.id
    assert updates[0].changes == [{"attribute": "role", "from": "user", "to": "admin"}]


async def test_update_with_no_actual_change_writes_nothing(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_headers: dict[str, str],
    test_user: User,
) -> None:
    response = await client.patch(
        f"{USERS}/{test_user.id}", headers=admin_headers, json={"role": test_user.role}
    )
    assert response.status_code == 200

    updates = [e for e in await _entries(db_session) if e.action == AuditAction.USER_UPDATED]
    assert updates == []


async def test_self_update_records_the_user_as_its_own_actor(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    test_user: User,
) -> None:
    response = await client.patch(
        f"{USERS}/me", headers=auth_headers, json={"full_name": "Renamed"}
    )
    assert response.status_code == 200

    updates = [e for e in await _entries(db_session) if e.action == AuditAction.USER_UPDATED]
    assert len(updates) == 1
    assert updates[0].actor_id == updates[0].resource_id == test_user.id
    assert updates[0].changes == [{"attribute": "full_name", "from": "Test User", "to": "Renamed"}]


async def test_password_change_never_leaks_into_changes(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    response = await client.patch(
        f"{USERS}/me", headers=auth_headers, json={"password": "a-brand-new-password"}
    )
    assert response.status_code == 200

    serialized = str([e.changes for e in await _entries(db_session)])
    assert "password" not in serialized
    assert "a-brand-new-password" not in serialized


async def test_delete_is_audited(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_headers: dict[str, str],
    admin_user: User,
    test_user: User,
) -> None:
    response = await client.delete(f"{USERS}/{test_user.id}", headers=admin_headers)
    assert response.status_code == 200

    deletes = [e for e in await _entries(db_session) if e.action == AuditAction.USER_DELETED]
    assert len(deletes) == 1
    assert deletes[0].actor_id == admin_user.id
    assert deletes[0].resource_id == test_user.id


async def test_rejected_delete_leaves_no_audit_trail(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_headers: dict[str, str],
    admin_user: User,
) -> None:
    """Self-deletion is refused, so the staged entry must roll back with it."""
    response = await client.delete(f"{USERS}/{admin_user.id}", headers=admin_headers)
    assert response.status_code == 409

    deletes = [e for e in await _entries(db_session) if e.action == AuditAction.USER_DELETED]
    assert deletes == []


async def test_audit_queries_filter_by_participant(
    db_session: AsyncSession,
    audit_service: AuditService,
    admin_user: User,
    test_user: User,
) -> None:
    audit_service.record(AuditAction.USER_DELETED, actor_id=admin_user.id, resource_id=test_user.id)
    audit_service.record(AuditAction.USER_LOGIN, actor_id=test_user.id, resource_id=test_user.id)
    await db_session.commit()

    by_actor = await audit_service.list(PaginationParams(), actor_id=admin_user.id)
    by_resource = await audit_service.list(PaginationParams(), resource_id=test_user.id)
    by_action = await audit_service.list(PaginationParams(), action=AuditAction.USER_LOGIN)

    assert by_actor.total == 1
    assert by_resource.total == 2
    assert by_action.total == 1
