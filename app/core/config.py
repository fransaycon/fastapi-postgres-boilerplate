import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, BeforeValidator, Field, PostgresDsn, computed_field
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_origins(value: str | list[str]) -> list[str]:
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("["):
            return json.loads(value)
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _blank_to_none(value: str | None) -> str | None:
    """`FOO=` in a .env file arrives as "", which is not the same as unset."""
    return value.strip() or None if isinstance(value, str) else value


CorsOrigins = Annotated[list[AnyHttpUrl], NoDecode, BeforeValidator(_split_origins)]
OptionalStr = Annotated[str | None, BeforeValidator(_blank_to_none)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # Application
    PROJECT_NAME: str = "FastAPI Boilerplate"
    ENVIRONMENT: Literal["local", "staging", "production", "test"] = "local"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # Security
    SECRET_KEY: str = Field(min_length=32)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Refresh token cookie
    REFRESH_COOKIE_NAME: str = "refresh_token"
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
    COOKIE_DOMAIN: OptionalStr = None
    # Only enable behind a proxy you control, otherwise clients can spoof their IP.
    TRUST_PROXY_HEADERS: bool = False

    # Database
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "app"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # CORS
    BACKEND_CORS_ORIGINS: CorsOrigins = []

    # Rate limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "100/minute"
    RATE_LIMIT_AUTH: str = "5/minute"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ALEMBIC_DATABASE_URI(self) -> str:
        """Sync DSN used by Alembic's offline mode and tooling."""
        return self.SQLALCHEMY_DATABASE_URI.replace("postgresql+asyncpg", "postgresql+psycopg")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
