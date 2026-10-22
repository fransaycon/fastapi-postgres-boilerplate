import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.permissions import Permission, Role, permissions_for

PASSWORD_FIELD = Field(min_length=12, max_length=128, examples=["super-secret-passphrase"])


class UserBase(BaseModel):
    email: EmailStr = Field(max_length=320, examples=["user@example.com"])
    full_name: str | None = Field(default=None, max_length=255)


class UserCreate(UserBase):
    """Public self-registration payload. Role is never caller-supplied."""

    password: str = PASSWORD_FIELD


class UserAdminCreate(BaseModel):
    email: EmailStr = Field(max_length=320, examples=["user@example.com"])
    password: str = PASSWORD_FIELD
    role: Role = Role.USER


class UserAdminUpdate(BaseModel):
    email: EmailStr | None = Field(default=None, max_length=320)
    role: Role | None = None


class PasswordUpdate(BaseModel):
    password: str = PASSWORD_FIELD


class UserSelfUpdate(BaseModel):
    """What a user may change about themselves. Privileged fields are absent by design."""

    email: EmailStr | None = Field(default=None, max_length=320)
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=12, max_length=128)


class UserUpdate(UserSelfUpdate):
    """Administrative update — may also change role and activation."""

    role: Role | None = None
    is_active: bool | None = None


class UserPublic(UserBase):
    """Serialization model — intentionally excludes `hashed_password`."""

    model_config = ConfigDict(from_attributes=True)

    # Plain `str`, not `EmailStr`: soft-deleted rows hold a reserved `.invalid` address
    # that would fail inbound validation, and output never needs re-validating.
    email: str
    id: uuid.UUID
    is_active: bool
    role: Role
    created_at: datetime
    deleted_at: datetime | None = None


class UserMe(UserPublic):
    """`/users/me` additionally exposes the caller's resolved permissions."""

    permissions: list[Permission]

    @classmethod
    def from_user(cls, user: object) -> "UserMe":
        public = UserPublic.model_validate(user)
        return cls(**public.model_dump(), permissions=sorted(permissions_for(public.role)))


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    sub: str
    type: str
    exp: int
    jti: str
