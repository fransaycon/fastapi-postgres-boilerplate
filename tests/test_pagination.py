"""Pagination semantics that are easy to get subtly wrong."""

import pytest
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.pagination import PaginationParams, paginate
from app.core.permissions import Role
from app.core.security import hash_password
from app.models.user import User


@pytest.fixture
async def population(db_session: AsyncSession) -> None:
    for index in range(7):
        db_session.add(
            User(
                email=f"user{index}@example.com",
                hashed_password=hash_password("a-very-long-password"),
                role=Role.ADMIN if index < 3 else Role.USER,
                is_active=index % 2 == 0,
            )
        )
    await db_session.commit()


async def test_total_reflects_filters_not_page_size(
    db_session: AsyncSession, population: None
) -> None:
    statement = select(User).where(User.role == Role.ADMIN)
    page = await paginate(db_session, statement, PaginationParams(page=1, size=2))

    assert page.total == 3  # filtered count, not the 7 rows in the table
    assert len(page.items) == 2  # limited by page size
    assert page.pages == 2


async def test_total_is_stable_across_pages(db_session: AsyncSession, population: None) -> None:
    statement = select(User).where(col(User.is_active).is_(True))
    totals = [
        (await paginate(db_session, statement, PaginationParams(page=page, size=2))).total
        for page in (1, 2, 3)
    ]
    assert totals == [4, 4, 4]


async def test_pages_cover_every_row_exactly_once(
    db_session: AsyncSession, population: None
) -> None:
    statement = select(User).order_by(col(User.email))
    seen: list[str] = []
    for number in (1, 2, 3, 4):
        page = await paginate(db_session, statement, PaginationParams(page=number, size=2))
        seen.extend(user.email for user in page.items)

    assert len(seen) == len(set(seen)) == 7


async def test_page_beyond_the_end_is_empty_but_keeps_total(
    db_session: AsyncSession, population: None
) -> None:
    page = await paginate(db_session, select(User), PaginationParams(page=99, size=10))
    assert page.items == []
    assert page.total == 7


async def test_empty_result_set_reports_zero_pages(db_session: AsyncSession) -> None:
    statement = select(User).where(User.email == "nobody@example.com")
    page = await paginate(db_session, statement, PaginationParams())
    assert (page.total, page.pages, page.items) == (0, 0, [])
