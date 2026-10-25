"""Shared database connection for seed scripts."""

import asyncio
from collections.abc import Awaitable, Callable

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal, dispose_engine

Seed = Callable[[AsyncSession], Awaitable[None]]


def run(seed: Seed, *, environments: tuple[str, ...]) -> None:
    if settings.ENVIRONMENT not in environments:
        raise SystemExit(
            f"Refusing to run: ENVIRONMENT is '{settings.ENVIRONMENT}', "
            f"this seed only runs in {', '.join(environments)}."
        )
    asyncio.run(_run(seed))


async def _run(seed: Seed) -> None:
    try:
        async with AsyncSessionLocal() as session:
            await seed(session)
    finally:
        await dispose_engine()
