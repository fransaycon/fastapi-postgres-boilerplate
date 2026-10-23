"""Audit trail vocabulary.

Actions are a closed, hardcoded set. Adding one is a code change, never a free-text
string at the call site, so the values stay queryable and typo-proof.
"""

from enum import StrEnum
from typing import Any

# Never record these, even if they change.
REDACTED_ATTRIBUTES = frozenset({"hashed_password", "password"})


class AuditAction(StrEnum):
    USER_LOGIN = "user.login"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"


def _serialize(value: Any) -> Any:
    return str(value) if isinstance(value, StrEnum) else value


def build_changes(before: object, values: dict[str, Any]) -> list[dict[str, Any]]:
    """Diff pending `values` against the current entity, skipping no-op assignments."""
    changes = []
    for attribute, new_value in values.items():
        if attribute in REDACTED_ATTRIBUTES:
            continue
        old_value = getattr(before, attribute, None)
        if old_value == new_value:
            continue
        changes.append(
            {
                "attribute": attribute,
                "from": _serialize(old_value),
                "to": _serialize(new_value),
            }
        )
    return changes
