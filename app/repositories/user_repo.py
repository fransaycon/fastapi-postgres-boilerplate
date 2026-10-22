import uuid
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql.expression import SelectOfScalar

from app.core.pagination import Page, PaginationParams, paginate
from app.models.user import User


class UserRepository:
    """Data access layer for `User`. Contains no business rules."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _base_query(self, *, include_deleted: bool) -> SelectOfScalar[User]:
        statement = select(User)
        if not include_deleted:
            statement = statement.where(col(User.deleted_at).is_(None))
        return statement

    async def get_by_id(self, user_id: uuid.UUID, *, include_deleted: bool = False) -> User | None:
        statement = self._base_query(include_deleted=include_deleted).where(User.id == user_id)
        result = await self.session.exec(statement)
        return result.first()

    async def get_by_email(self, email: str, *, include_deleted: bool = False) -> User | None:
        statement = self._base_query(include_deleted=include_deleted).where(User.email == email)
        result = await self.session.exec(statement)
        return result.first()

    async def list(self, params: PaginationParams, *, include_deleted: bool = False) -> Page[User]:
        statement = self._base_query(include_deleted=include_deleted).order_by(
            col(User.created_at).desc()
        )
        return await paginate(self.session, statement, params)

    async def create(self, user: User) -> User:
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def update(self, user: User, values: dict[str, Any]) -> User:
        for field, value in values.items():
            setattr(user, field, value)
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user
