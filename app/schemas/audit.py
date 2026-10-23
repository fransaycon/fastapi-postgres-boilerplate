import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core.audit import AuditAction


class AuditLogPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_id: uuid.UUID | None
    resource_id: uuid.UUID | None
    action: AuditAction
    changes: list[dict[str, Any]] | None
    created_at: datetime
