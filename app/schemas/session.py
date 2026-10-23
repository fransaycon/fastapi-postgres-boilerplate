import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_label: str
    ip_address: str | None
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
