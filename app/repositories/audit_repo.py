import uuid

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit import AuditAction
from app.core.pagination import Page, PaginationParams, paginate
from app.models.audit_log import AuditLog


class AuditRepository:
    """Append-only. Audit rows are never updated or deleted by the application."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def stage(self, entry: AuditLog) -> AuditLog:
        """Enlist the row in the caller's transaction; the business commit persists it."""
        self.session.add(entry)
        return entry

    async def list(
        self,
        params: PaginationParams,
        *,
        actor_id: uuid.UUID | None = None,
        resource_id: uuid.UUID | None = None,
        action: AuditAction | None = None,
    ) -> Page[AuditLog]:
        statement = select(AuditLog)
        if actor_id is not None:
            statement = statement.where(AuditLog.actor_id == actor_id)
        if resource_id is not None:
            statement = statement.where(AuditLog.resource_id == resource_id)
        if action is not None:
            statement = statement.where(AuditLog.action == action)

        statement = statement.order_by(col(AuditLog.created_at).desc())
        return await paginate(self.session, statement, params)
