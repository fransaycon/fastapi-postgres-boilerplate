import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.core.devices import describe_device
from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.security import create_refresh_token
from app.models.session import UserSession
from app.repositories.session_repo import SessionRepository


@dataclass(frozen=True, slots=True)
class ClientInfo:
    ip_address: str | None = None
    user_agent: str | None = None


def _expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)


class SessionService:
    """Owns the lifecycle of per-device refresh sessions."""

    def __init__(self, repository: SessionRepository) -> None:
        self.repository = repository

    async def start(self, user_id: uuid.UUID, client: ClientInfo) -> tuple[UserSession, str]:
        """Called on login: register the device and mint its first refresh token."""
        user_session = await self.repository.create(
            UserSession(
                user_id=user_id,
                device_label=describe_device(client.user_agent),
                user_agent=client.user_agent,
                ip_address=client.ip_address,
                expires_at=_expiry(),
            )
        )
        return user_session, self._token(user_id, user_session)

    async def rotate(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        token_version: uuid.UUID,
        client: ClientInfo,
    ) -> tuple[UserSession, str]:
        user_session = await self.repository.get_active(session_id)
        if user_session is None or user_session.user_id != user_id:
            raise AuthenticationError("Invalid refresh token")

        if user_session.token_version != token_version:
            # A superseded token was replayed — assume theft and kill the session.
            await self.repository.revoke(user_session)
            raise AuthenticationError("Refresh token reuse detected; session revoked")

        user_session.token_version = uuid.uuid4()
        user_session.last_used_at = datetime.now(UTC)
        user_session.expires_at = _expiry()
        user_session.ip_address = client.ip_address or user_session.ip_address
        await self.repository.save(user_session)
        return user_session, self._token(user_id, user_session)

    async def end(self, session_id: uuid.UUID) -> None:
        user_session = await self.repository.get_active(session_id)
        if user_session is not None:
            await self.repository.revoke(user_session)

    async def end_for_user(self, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
        user_session = await self.repository.get_active(session_id)
        if user_session is None or user_session.user_id != user_id:
            raise NotFoundError("Session not found")
        await self.repository.revoke(user_session)

    async def list_for_user(self, user_id: uuid.UUID) -> list[UserSession]:
        return await self.repository.list_active_for_user(user_id)

    async def end_all_for_user(self, user_id: uuid.UUID) -> int:
        return await self.repository.revoke_all_for_user(user_id)

    @staticmethod
    def _token(user_id: uuid.UUID, user_session: UserSession) -> str:
        return create_refresh_token(
            str(user_id),
            session_id=str(user_session.id),
            token_version=str(user_session.token_version),
        )
