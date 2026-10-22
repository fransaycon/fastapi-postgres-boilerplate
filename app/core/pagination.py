"""Reusable pagination primitives.

`paginate()` runs the count and page queries for any `select()` statement, so
repositories never hand-roll `offset`/`limit`/`COUNT(*)` logic per resource.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import ceil
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql.expression import SelectOfScalar

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class PaginationParams:
    page: int = 1
    size: int = DEFAULT_PAGE_SIZE

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class Page[ItemT](BaseModel):
    """Envelope returned by every paginated endpoint."""

    items: list[ItemT]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    size: int = Field(ge=1)
    pages: int = Field(ge=0)

    @classmethod
    def build(cls, items: Sequence[ItemT], total: int, params: PaginationParams) -> "Page[ItemT]":
        return cls(
            items=list(items),
            total=total,
            page=params.page,
            size=params.size,
            pages=ceil(total / params.size) if params.size else 0,
        )

    def map[OtherT](self, transform: Callable[[ItemT], OtherT]) -> "Page[OtherT]":
        """Convert the items while preserving the pagination metadata."""
        return Page[Any](
            items=[transform(item) for item in self.items],
            total=self.total,
            page=self.page,
            size=self.size,
            pages=self.pages,
        )


async def paginate[ModelT](
    session: AsyncSession,
    statement: SelectOfScalar[ModelT],
    params: PaginationParams,
) -> Page[ModelT]:
    total = await session.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    )
    result = await session.exec(statement.offset(params.offset).limit(params.size))
    return Page[Any].build(result.all(), total or 0, params)
