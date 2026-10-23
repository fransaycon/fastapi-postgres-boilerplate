import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, func
from sqlmodel import Column, Field, SQLModel

from app.core.audit import AuditAction
from app.models.user import utc_now


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    actor_id: uuid.UUID | None = Field(default=None, foreign_key="users.id", index=True)
    resource_id: uuid.UUID | None = Field(default=None, foreign_key="users.id", index=True)
    action: AuditAction = Field(max_length=100, index=True)
    changes: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
        ),
    )
