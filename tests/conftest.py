import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-characters-long")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("BACKEND_CORS_ORIGINS", "http://testserver")
# Keep the limiter ON so tests exercise the slowapi decorator path, but raise the
# ceilings so unrelated tests never trip a 429.
os.environ.setdefault("RATE_LIMIT_DEFAULT", "100000/minute")
os.environ.setdefault("RATE_LIMIT_AUTH", "100000/minute")

from collections.abc import AsyncGenerator

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.database import get_db
from app.core.permissions import Role
from app.main import app as fastapi_app
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.user import UserCreate
from app.services.user_service import UserService

SQLITE_URL = "sqlite+aiosqlite:///:memory:"
# Point at the compose `db-test` service to run the suite against real Postgres:
#   TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/test
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", SQLITE_URL)
TEST_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    """An isolated database schema, created and dropped per test."""
    if TEST_DATABASE_URL.startswith("sqlite"):
        engine = create_async_engine(
            TEST_DATABASE_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    fastapi_app.dependency_overrides[get_db] = override_get_db

    async with (
        LifespanManager(fastapi_app),
        AsyncClient(
            transport=ASGITransport(app=fastapi_app),
            base_url="http://testserver",
        ) as async_client,
    ):
        yield async_client

    fastapi_app.dependency_overrides.clear()


@pytest.fixture
def user_service(db_session: AsyncSession) -> UserService:
    return UserService(UserRepository(db_session))


@pytest.fixture
async def test_user(user_service: UserService) -> User:
    return await user_service.register(
        UserCreate(email="user@example.com", full_name="Test User", password=TEST_PASSWORD)
    )


@pytest.fixture
async def admin_user(user_service: UserService) -> User:
    user = await user_service.register(
        UserCreate(email="admin@example.com", full_name="Admin User", password=TEST_PASSWORD)
    )
    return await user_service.repository.update(user, {"role": Role.ADMIN})


async def _login(client: AsyncClient, user: User) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": user.email, "password": TEST_PASSWORD},
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def auth_headers(client: AsyncClient, test_user: User) -> dict[str, str]:
    return await _login(client, test_user)


@pytest.fixture
async def admin_headers(client: AsyncClient, admin_user: User) -> dict[str, str]:
    return await _login(client, admin_user)
