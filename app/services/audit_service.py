import uuid
from typing import Any

from app.core.audit import AuditAction
from app.core.pagination import Page, PaginationParams
from app.models.audit_log import AuditLog
from app.repositories.audit_repo import AuditRepository


class AuditService:
    """Records domain events. Call `record()` immediately before the write it describes.

    The entry joins the caller's transaction, so a failed operation discards its own
    audit row and a successful one can never lose it.
    """

    def __init__(self, repository: AuditRepository) -> None:
        self.repository = repository

    def record(
        self,
        action: AuditAction,
        *,
        actor_id: uuid.UUID | None = None,
        resource_id: uuid.UUID | None = None,
        changes: list[dict[str, Any]] | None = None,
    ) -> AuditLog:
        return self.repository.stage(
            AuditLog(
                action=action,
                actor_id=actor_id,
                resource_id=resource_id,
                changes=changes or None,
            )
        )

    async def list(
        self,
        params: PaginationParams,
        *,
        actor_id: uuid.UUID | None = None,
        resource_id: uuid.UUID | None = None,
        action: AuditAction | None = None,
    ) -> Page[AuditLog]:
        return await self.repository.list(
            params, actor_id=actor_id, resource_id=resource_id, action=action
        )
