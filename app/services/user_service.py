import uuid
from datetime import UTC, datetime

from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError
from app.core.pagination import Page, PaginationParams
from app.core.permissions import DEFAULT_ROLE
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories.session_repo import SessionRepository
from app.repositories.user_repo import UserRepository
from app.schemas.user import UserAdminCreate, UserAdminUpdate, UserCreate, UserSelfUpdate

# Reserved TLD (RFC 2606) so an anonymized address can never route anywhere.
DELETED_EMAIL_DOMAIN = "deleted.invalid"


def anonymized_email(user_id: uuid.UUID) -> str:
    """Unique by construction, so freeing the old address cannot break the email index."""
    return f"deleted+{user_id}@{DELETED_EMAIL_DOMAIN}"


class UserService:
    """Business rules for the user domain."""

    def __init__(self, repository: UserRepository, sessions: SessionRepository) -> None:
        self.repository = repository
        self.sessions = sessions

    async def _claim_email(self, email: str, *, exclude: uuid.UUID | None = None) -> str:
        normalized = email.lower()
        existing = await self.repository.get_by_email(normalized)
        if existing is not None and existing.id != exclude:
            raise ConflictError("A user with this email already exists")
        return normalized

    async def register(self, payload: UserCreate) -> User:
        user = User(
            email=await self._claim_email(payload.email),
            full_name=payload.full_name,
            hashed_password=hash_password(payload.password),
            role=DEFAULT_ROLE,
        )
        return await self.repository.create(user)

    async def create_as_admin(self, payload: UserAdminCreate) -> User:
        user = User(
            email=await self._claim_email(payload.email),
            hashed_password=hash_password(payload.password),
            role=payload.role,
        )
        return await self.repository.create(user)

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.repository.get_by_email(email.lower())
        # Hash a dummy value when the user is missing to keep timing constant.
        hashed = user.hashed_password if user else hash_password("invalid-placeholder")
        if not verify_password(password, hashed) or user is None:
            raise AuthenticationError("Incorrect email or password")
        if not user.is_active:
            raise AuthenticationError("Inactive user")
        return user

    async def get(self, user_id: uuid.UUID) -> User:
        user = await self.repository.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user

    async def list(self, params: PaginationParams) -> Page[User]:
        return await self.repository.list(params)

    async def update_self(self, user_id: uuid.UUID, payload: UserSelfUpdate) -> User:
        user = await self.get(user_id)
        values = payload.model_dump(exclude_unset=True)

        if (new_email := values.pop("email", None)) is not None:
            values["email"] = await self._claim_email(new_email, exclude=user.id)

        if (new_password := values.pop("password", None)) is not None:
            values["hashed_password"] = hash_password(new_password)

        updated = await self.repository.update(user, values)
        if new_password is not None:
            # A password change invalidates every device, including this one.
            await self.sessions.revoke_all_for_user(user.id)
        return updated

    async def update_as_admin(self, user_id: uuid.UUID, payload: UserAdminUpdate) -> User:
        user = await self.get(user_id)
        values = payload.model_dump(exclude_unset=True)

        if (new_email := values.pop("email", None)) is not None:
            values["email"] = await self._claim_email(new_email, exclude=user.id)

        return await self.repository.update(user, values)

    async def set_password(self, user_id: uuid.UUID, password: str) -> User:
        user = await self.get(user_id)
        updated = await self.repository.update(user, {"hashed_password": hash_password(password)})
        await self.sessions.revoke_all_for_user(user.id)
        return updated

    async def soft_delete(self, user_id: uuid.UUID, *, acting_user_id: uuid.UUID) -> User:
        if user_id == acting_user_id:
            raise ConflictError("You cannot delete your own account")

        user = await self.get(user_id)
        deleted = await self.repository.update(
            user,
            {
                "deleted_at": datetime.now(UTC),
                "is_active": False,
                "email": anonymized_email(user.id),
            },
        )
        await self.sessions.revoke_all_for_user(user.id)
        return deleted
