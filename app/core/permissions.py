"""Hardcoded role → permission mapping. Intentionally not database-backed.

Permissions are the unit of authorization; roles are only a shorthand for a set of them.
Guard routes on a `Permission`, never on a `Role`, so the mapping below stays the single
place that has to change when access rules move.
"""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"


class Permission(StrEnum):
    PROFILE_READ = "profile:read"
    PROFILE_WRITE = "profile:write"

    USERS_READ = "users:read"
    USERS_WRITE = "users:write"
    USERS_DELETE = "users:delete"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(
        {
            Permission.PROFILE_READ,
            Permission.PROFILE_WRITE,
            Permission.USERS_READ,
            Permission.USERS_WRITE,
            Permission.USERS_DELETE,
        }
    ),
    Role.USER: frozenset(
        {
            Permission.PROFILE_READ,
            Permission.PROFILE_WRITE,
        }
    ),
}

DEFAULT_ROLE = Role.USER


def permissions_for(role: Role) -> frozenset[Permission]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in permissions_for(role)
