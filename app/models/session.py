import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlmodel import Column, Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class UserSession(SQLModel, table=True):
    """One row per logged-in device. `id` is the `sid` claim, `token_version` the `ver`."""

    __tablename__ = "user_sessions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True, nullable=False)
    # Rotated on every refresh; a stale value means the token was replayed.
    token_version: uuid.UUID = Field(default_factory=uuid.uuid4, nullable=False)

    device_label: str = Field(default="Unknown device", max_length=128)
    user_agent: str | None = Field(default=None, max_length=512)
    ip_address: str | None = Field(default=None, max_length=45)

    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )
    last_used_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    revoked_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True, index=True)
    )

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > utc_now()
