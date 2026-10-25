from seeds.core import run
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.permissions import Role
from app.core.security import hash_password
from app.models.user import User
from app.repositories.user_repo import UserRepository

EMAIL = "admin@example.com"
PASSWORD = "development-password"  # noqa: S105
ROLE = Role.ADMIN


async def seed(session: AsyncSession) -> None:
    repository = UserRepository(session)
    if await repository.get_by_email(EMAIL) is not None:
        print(f"{EMAIL} already exists, skipping")
        return

    await repository.create(User(email=EMAIL, hashed_password=hash_password(PASSWORD), role=ROLE))
    print(f"Created {ROLE.value} {EMAIL}")


if __name__ == "__main__":
    run(seed, environments=("local",))
