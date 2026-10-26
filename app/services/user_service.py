import uuid
from datetime import UTC, datetime, timedelta

from app.core.audit import AuditAction, build_changes
from app.core.config import settings
from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError
from app.core.pagination import Page, PaginationParams
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories.session_repo import SessionRepository
from app.repositories.user_repo import UserRepository
from app.schemas.user import UserAdminCreate, UserAdminUpdate
from app.services.audit_service import AuditService

# Reserved TLD (RFC 2606) so an anonymized address can never route anywhere.
DELETED_EMAIL_DOMAIN = "deleted.invalid"

# Reused for a locked account too: a distinct message would confirm the address exists.
INVALID_CREDENTIALS = "Incorrect email or password"


def anonymized_email(user_id: uuid.UUID) -> str:
    """Unique by construction, so freeing the old address cannot break the email index."""
    return f"deleted+{user_id}@{DELETED_EMAIL_DOMAIN}"


def _as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo on round-trip, so normalize before any arithmetic."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _lockout_window() -> timedelta:
    return timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)


class UserService:
    """Business rules for the user domain."""

    def __init__(
        self,
        repository: UserRepository,
        sessions: SessionRepository,
        audit: AuditService,
    ) -> None:
        self.repository = repository
        self.sessions = sessions
        self.audit = audit

    async def _claim_email(self, email: str, *, exclude: uuid.UUID | None = None) -> str:
        normalized = email.lower()
        existing = await self.repository.get_by_email(normalized)
        if existing is not None and existing.id != exclude:
            raise ConflictError("A user with this email already exists")
        return normalized

    async def create_as_admin(self, payload: UserAdminCreate) -> User:
        user = User(
            email=await self._claim_email(payload.email),
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name,
            role=payload.role,
        )
        return await self.repository.create(user)

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.repository.get_by_email(email.lower())
        hashed = user.hashed_password if user else hash_password("invalid-placeholder")
        password_matches = verify_password(password, hashed)
        now = datetime.now(UTC)

        if user is not None and self._is_locked_out(user, now):
            raise AuthenticationError(INVALID_CREDENTIALS)
        if user is None or not password_matches:
            if user is not None:
                await self._record_failed_login(user, now)
            raise AuthenticationError(INVALID_CREDENTIALS)
        if not user.is_active:
            raise AuthenticationError("Inactive user")

        return await self.repository.update(
            user,
            {"login_attempts": 0, "last_failed_login_at": None, "last_logged_in_at": now},
        )

    @staticmethod
    def _is_locked_out(user: User, now: datetime) -> bool:
        if user.login_attempts < settings.LOGIN_MAX_ATTEMPTS or user.last_failed_login_at is None:
            return False
        return now - _as_utc(user.last_failed_login_at) < _lockout_window()

    async def _record_failed_login(self, user: User, now: datetime) -> None:
        """Attempts expire with the window, so isolated typos never accumulate into a lock."""
        previous = user.last_failed_login_at
        within_window = previous is not None and now - _as_utc(previous) < _lockout_window()
        await self.repository.update(
            user,
            {
                "login_attempts": user.login_attempts + 1 if within_window else 1,
                "last_failed_login_at": now,
            },
        )

    async def get(self, user_id: uuid.UUID) -> User:
        user = await self.repository.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user

    async def list(self, params: PaginationParams) -> Page[User]:
        return await self.repository.list(params)

    async def update_as_admin(
        self, user_id: uuid.UUID, payload: UserAdminUpdate, *, acting_user_id: uuid.UUID
    ) -> User:
        user = await self.get(user_id)
        values = payload.model_dump(exclude_unset=True)

        if (new_email := values.pop("email", None)) is not None:
            values["email"] = await self._claim_email(new_email, exclude=user.id)

        self._record_update(actor_id=acting_user_id, user=user, values=values)
        return await self.repository.update(user, values)

    def _record_update(self, *, actor_id: uuid.UUID, user: User, values: dict[str, object]) -> None:
        """No-op updates are not events, so nothing is written when nothing changed."""
        changes = build_changes(user, values)
        if changes:
            self.audit.record(
                AuditAction.USER_UPDATED,
                actor_id=actor_id,
                resource_id=user.id,
                changes=changes,
            )

    async def set_password(self, user_id: uuid.UUID, password: str) -> User:
        user = await self.get(user_id)
        updated = await self.repository.update(user, {"hashed_password": hash_password(password)})
        await self.sessions.revoke_all_for_user(user.id)
        return updated

    async def soft_delete(self, user_id: uuid.UUID, *, acting_user_id: uuid.UUID) -> User:
        if user_id == acting_user_id:
            raise ConflictError("You cannot delete your own account")

        user = await self.get(user_id)
        self.audit.record(AuditAction.USER_DELETED, actor_id=acting_user_id, resource_id=user.id)
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
