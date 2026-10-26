import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.permissions import Role

PASSWORD_FIELD = Field(min_length=12, max_length=128, examples=["super-secret-passphrase"])


class UserBase(BaseModel):
    """The identity fields a signed-in user sees about themselves."""

    model_config = ConfigDict(from_attributes=True)

    email: EmailStr = Field(max_length=320, examples=["user@example.com"])
    full_name: str | None = Field(default=None, max_length=255)


class UserAdminCreate(BaseModel):
    email: EmailStr = Field(max_length=320, examples=["user@example.com"])
    full_name: str | None = Field(default=None, max_length=255)
    password: str = PASSWORD_FIELD
    role: Role = Role.USER


class UserAdminUpdate(BaseModel):
    email: EmailStr | None = Field(default=None, max_length=320)
    full_name: str | None = Field(default=None, max_length=255)
    role: Role | None = None


class PasswordUpdate(BaseModel):
    password: str = PASSWORD_FIELD


class UserPublic(UserBase):
    model_config = ConfigDict(from_attributes=True)

    email: str
    id: uuid.UUID
    is_active: bool
    full_name: str | None = None
    role: Role
    created_at: datetime
    deleted_at: datetime | None = None


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
