import uuid
from datetime import UTC, datetime

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.session import UserSession


class SessionRepository:
    """Data access for `UserSession`. Contains no business rules."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _active(self, statement):  # type: ignore[no-untyped-def]
        return statement.where(
            col(UserSession.revoked_at).is_(None),
            col(UserSession.expires_at) > datetime.now(UTC),
        )

    async def get_active(self, session_id: uuid.UUID) -> UserSession | None:
        result = await self.session.exec(
            self._active(select(UserSession).where(UserSession.id == session_id))
        )
        return result.first()

    async def list_active_for_user(self, user_id: uuid.UUID) -> list[UserSession]:
        result = await self.session.exec(
            self._active(select(UserSession).where(UserSession.user_id == user_id)).order_by(
                col(UserSession.last_used_at).desc()
            )
        )
        return list(result.all())

    async def create(self, user_session: UserSession) -> UserSession:
        self.session.add(user_session)
        await self.session.commit()
        await self.session.refresh(user_session)
        return user_session

    async def save(self, user_session: UserSession) -> UserSession:
        self.session.add(user_session)
        await self.session.commit()
        await self.session.refresh(user_session)
        return user_session

    async def revoke(self, user_session: UserSession) -> UserSession:
        user_session.revoked_at = datetime.now(UTC)
        return await self.save(user_session)

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        sessions = await self.list_active_for_user(user_id)
        now = datetime.now(UTC)
        for user_session in sessions:
            user_session.revoked_at = now
            self.session.add(user_session)
        await self.session.commit()
        return len(sessions)
