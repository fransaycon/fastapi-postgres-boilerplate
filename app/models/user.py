import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, func
from sqlalchemy import Enum as SAEnum
from sqlmodel import Column, Field, SQLModel

from app.core.permissions import DEFAULT_ROLE, Role


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(max_length=320, unique=True, index=True)
    hashed_password: str = Field(max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool = Field(default=True, nullable=False)
    role: Role = Field(
        default=DEFAULT_ROLE,
        sa_column=Column(
            SAEnum(
                Role, native_enum=False, length=32, values_callable=lambda e: [m.value for m in e]
            ),
            nullable=False,
            server_default=DEFAULT_ROLE.value,
            index=True,
        ),
    )
    last_logged_in_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    login_attempts: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    # Anchors the lockout window; without it consecutive failures could never expire.
    last_failed_login_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        ),
    )
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
