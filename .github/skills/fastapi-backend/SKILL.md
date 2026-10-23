---
name: fastapi-backend
description: 'Use when writing, reviewing, debugging, or extending code in this FastAPI backend — adding endpoints, services, repositories, SQLModel models, or Pydantic schemas; working with async SQLAlchemy/SQLModel sessions; roles, permissions and RBAC authorization guards; configuring pydantic-settings; JWT auth with access/refresh tokens; slowapi rate limiting; Alembic async migrations; pytest + httpx AsyncClient tests; uv and Ruff commands; or the docker compose Postgres setup. Contains verified project conventions and the gotchas that have already bitten this repo.'
---

# FastAPI Backend Conventions

Stack: FastAPI · Python 3.12 · uv · Ruff · SQLModel (SQLAlchemy 2.0 async) · asyncpg ·
Alembic · Pydantic v2 / pydantic-settings · PyJWT · pwdlib[argon2] · slowapi · pytest + httpx.

See the `fastapi-project-structure` skill for where files belong. This skill covers *how*
to write them.

## Commands

`uv` installs to `~/.local/bin` — ensure it is on `PATH`.

```bash
uv sync
uv run pytest -q
uv run ruff check . --fix && uv run ruff format .
uv run alembic revision --autogenerate -m "message"
uv run alembic upgrade head

docker compose up -d --build          # Postgres + API with hot reload
docker compose exec api alembic upgrade head
docker compose --profile test up -d db-test   # throwaway Postgres for tests

uv run pre-commit install             # one-time after cloning
uv run pre-commit run --all-files
uv run cz commit                      # guided conventional commit
```

Git hooks run via pre-commit: `pre-commit` (ruff check/format, file hygiene, `uv lock`),
`commit-msg` (Commitizen conventional-commit check), `pre-push` (pytest). Commit messages
must match `type(scope): subject` — `feat`, `fix`, `docs`, `refactor`, `test`, `chore`,
`build`, `ci`, `perf`, `style`, `revert`, `bump`. Hook revisions in
`.pre-commit-config.yaml` are pinned; bump with `uv run pre-commit autoupdate`.

Host ports are overridable: `POSTGRES_PORT`, `API_PORT`, `TEST_POSTGRES_PORT`.

## Database sessions

Use **`sqlmodel.ext.asyncio.session.AsyncSession`**, not SQLAlchemy's. Only the SQLModel
one has `.exec()`, which returns properly typed results for `select(Model)`.

```python
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

result = await session.exec(select(User).where(User.email == email))
user = result.first()
```

- Use `col(Model.field)` when calling SQLAlchemy operators like `.desc()` on a SQLModel
  field, otherwise type checkers reject it.
- Sessions are created by `get_db` and injected via `DbSession`. Repositories own
  `commit()`/`refresh()`; services and endpoints never touch the session directly.
- `expire_on_commit=False` is set, so instances stay usable after commit.

## Configuration

`app/core/config.py` uses `pydantic-settings` with a module-level `settings` singleton.

- **Gotcha:** pydantic-settings JSON-decodes complex env fields *before* validators run.
  A comma-separated list must be annotated with `NoDecode`, otherwise
  `BACKEND_CORS_ORIGINS=a,b` raises `SettingsError`.
- Derived values use `@computed_field` + `@property` (e.g. `SQLALCHEMY_DATABASE_URI`).
- Importing `app.main` without a `SECRET_KEY` raises a validation error by design.
- `FOO=` in a `.env` file yields `""`, not `None`. Optional string settings use the
  `OptionalStr` annotation (a `BeforeValidator` mapping blank to `None`) so
  `COOKIE_DOMAIN=` behaves like unset.
- The `.env` file is deliberately **not** mounted into the `api` container. Compose's
  `env_file:` injects the values into the process environment instead, so
  `Path(".env").exists()` is False in the container while settings still resolve
  correctly. That is intended, not a bug.
- Compose reads `env_file:` at **container creation**. After editing `.env` run
  `docker compose up -d`; `docker compose restart` keeps the old values and
  `uvicorn --reload` only watches Python files. Locally the process must restart too,
  since `settings` is cached with `@lru_cache`.

## pgAdmin

`docker compose up` starts pgAdmin on `${PGADMIN_PORT:-5050}` with both databases
pre-registered from `docker/pgadmin/servers.json` plus a `pgpass` file.

- Registration happens **only on first creation of the `pgadmin_data` volume**. After
  editing `servers.json`, remove that volume and recreate the container or nothing
  changes.
- pgAdmin ignores a `pgpass` that is group- or world-readable, so the entrypoint copies it
  to `/tmp/pgpass` and `chmod 600`s it. A directly mounted file keeps host permissions.
- The `test (throwaway)` server only connects while `--profile test` is running.

## Security

- Hashing is `pwdlib.PasswordHash.recommended()` (Argon2). Do not reintroduce passlib.
- Every JWT carries `type` (`access` | `refresh`), `jti`, `iat`, `nbf`, `exp`.
  `decode_token(token, expected_type=...)` rejects a mismatched type — this is what stops
  a refresh token being replayed as an access token. Keep that check.
- Refresh tokens are HttpOnly cookies scoped to `{API_V1_PREFIX}/auth`, rotated on every
  `/refresh`. Access tokens are returned in the body only.
- `authenticate()` hashes a dummy value when the email is unknown so response timing does
  not reveal account existence.
- `/docs` and the OpenAPI schema are disabled unless `DEBUG` is true.

## Errors

Services raise `AppError` subclasses from `app/core/exceptions.py`
(`NotFoundError`, `ConflictError`, `AuthenticationError`, `PermissionDeniedError`).
Never raise `HTTPException` outside the API layer. `main.py` registers handlers that map
them to status codes, plus handlers for `RequestValidationError`, `RateLimitExceeded`,
`SQLAlchemyError`, and a catch-all that logs and returns a generic 500.

Use the literal `422`, not `status.HTTP_422_UNPROCESSABLE_ENTITY` — the latter is
deprecated in current Starlette.

## Pagination

Never hand-roll `offset`/`limit`/`COUNT(*)` in a repository. Use the helper in
`app/core/pagination.py`:

```python
# repository
async def list(self, params: PaginationParams) -> Page[User]:
    statement = select(User).where(...).order_by(col(User.created_at).desc())
    return await paginate(self.session, statement, params)


# endpoint
@router.get("", response_model=Page[UserPublic])
async def list_users(service: UserServiceDep, pagination: PaginationDep) -> Page[UserPublic]:
    page = await service.list(pagination)
    return page.map(UserPublic.model_validate)
```

- `PaginationDep` supplies validated `page`/`size` query params — do not redeclare them
  per endpoint.
- `paginate()` takes any `select()` statement, runs `COUNT(*)` over it as a subquery
  (stripping `ORDER BY`), then the page query.
- `Page[T]` returns `items`, `total`, `page`, `size`, `pages`. `.map()` converts ORM rows
  to response schemas while preserving the metadata.
- `Page` and `PaginationParams` live in `core/` and import no FastAPI symbols;
  `PaginationDep` lives in `api/dependencies.py`.

## Soft deletes

`User.deleted_at` is the soft-delete marker. `DELETE /users/{id}` sets `deleted_at`,
flips `is_active` to false, and replaces the email with
`deleted+{uuid}@deleted.invalid` (`anonymized_email()`).

- The anonymized address is unique by construction, so the unique index on `email` holds
  and the original address becomes reusable immediately.
- `.invalid` is a reserved TLD (RFC 2606) and can never route.
- `UserRepository._base_query()` filters `deleted_at IS NULL` by default; pass
  `include_deleted=True` to bypass. Every new query must go through it, or deleted rows
  will leak into listings and logins.
- **`UserPublic.email` is `str`, not `EmailStr`** — `EmailStr` rejects `.invalid`, and
  output models should not re-validate inbound constraints.
- Admins cannot delete themselves (409).

## Authorization (RBAC)

Roles and permissions are **hardcoded in `app/core/permissions.py`** — there is no
roles/permissions table and none should be added. Only the user's `role` column is
persisted.

```python
class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"


class Permission(StrEnum):
    USERS_READ = "users:read"
    ...


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {...}
```

Rules:

- **Guard on a `Permission`, never on a `Role`.** `ROLE_PERMISSIONS` stays the single
  place access rules change.
  ```python
  @router.get("", dependencies=[Depends(require_permission(Permission.USERS_READ))])
  ```
- Use the `dependencies=[...]` argument when the user object is not needed in the body;
  use `current_user: CurrentUser` when it is.
- `ADMIN` is **not** automatically a superset of `USER`. Grants are explicit per role.
  `demo:admin-area` and `demo:user-area` exist to prove it, and the test suite asserts it.
- `require_permission` raises `PermissionDeniedError` → 403.
- `GET /users/me` returns `UserMe`, which includes the caller's resolved `permissions`
  list so a frontend can drive its UI from it.
- Changing a role takes effect on the next request — `get_current_user` reloads the user
  from the database rather than trusting a role claim in the JWT. Do not put roles or
  permissions in the token.
- Adding a permission = add the enum member + add it to the relevant roles. No migration.
  Adding a *role* needs a migration only because of the column's CHECK constraint.

Admin user management lives on `/api/v1/users` (list, create, read, update, set password,
soft delete). There is **no public registration and no self-service update** — the only
thing a signed-in non-admin can do is `GET /users/me`, which returns `UserBase`
(email and full name only). The first admin is created directly in the database.

Never sanitize by nulling privileged fields — `model_copy(update={"x": None})` marks the
field as *set*, so `exclude_unset` passes `None` straight into a `NOT NULL` column. Use a
narrower schema instead, the way `UserAdminUpdate` exposes only `email` and `role`.

## Rate limiting

```python
@router.get("/me", response_model=UserPublic)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def read_current_user(request: Request, current_user: CurrentUser) -> UserPublic: ...
```

- slowapi **requires** a parameter literally named `request: Request`, even if unused.
  Ruff's `ARG001` is disabled for `app/api/**` and `app/main.py` for this reason.
- The decorator goes *below* the route decorator.
- **`headers_enabled` must stay `False`.** When enabled, slowapi reads the response from
  a `response` kwarg; endpoints returning a Pydantic model have none, so it raises and
  every rate-limited endpoint returns 500. Turning it on requires adding
  `response: Response` to *every* limited endpoint.
- The limiter stays **enabled during tests** (with huge limits set in `conftest.py`) so
  the decorator path is actually exercised. Do not disable it — a regression test asserts
  `limiter.enabled`.
- `rate_limit_key` prefers `request.state.user_id` (set by `get_current_user`) and falls
  back to client IP.

## Testing

Tests run in the **local venv with no Docker** — the default backend is in-memory SQLite.

- `tests/conftest.py` sets env vars at the top of the file *before* importing `app`.
- `app.dependency_overrides[get_db]` injects the test session; `LifespanManager` runs
  startup/shutdown; `ASGITransport` avoids binding a port.
- Each test creates and drops the schema, so tests are order-independent.
- Set `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/test` to
  run against the compose `db-test` service and catch Postgres-only behavior.
- `asyncio_mode = "auto"` is set, so `async def test_*` needs no marker.

Assert that `hashed_password` and `password` never appear in any response body.

## Migrations

`alembic/env.py` runs async via `connection.run_sync(do_run_migrations)` and imports
`app.models` so `SQLModel.metadata` is populated. `compare_type` and
`compare_server_default` are on. A Ruff post-write hook formats generated revisions.
Always read an autogenerated migration before applying it.

## Dependency gotchas

- `sqlalchemy[asyncio]` (greenlet) is required — plain `sqlalchemy` fails at import.
- `OAuth2PasswordRequestForm` needs `Annotated[OAuth2PasswordRequestForm, Depends()]`
  and `python-multipart` installed.
- `EmailStr` needs `email-validator`.

## Reference

FastAPI
- [Dependencies with yield](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/)
- [OAuth2 with Password, Bearer with JWT](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
- [Handling Errors](https://fastapi.tiangolo.com/tutorial/handling-errors/)
- [Lifespan Events](https://fastapi.tiangolo.com/advanced/events/)
- [Settings and Environment Variables](https://fastapi.tiangolo.com/advanced/settings/)
- [Testing Dependencies with Overrides](https://fastapi.tiangolo.com/advanced/testing-dependencies/) · [Async Tests](https://fastapi.tiangolo.com/advanced/async-tests/)
- [CORS](https://fastapi.tiangolo.com/tutorial/cors/) · [FastAPI in Containers](https://fastapi.tiangolo.com/deployment/docker/)

Data layer
- [SQLModel docs](https://sqlmodel.tiangolo.com/) · [FastAPI + SQLModel tutorial](https://fastapi.tiangolo.com/tutorial/sql-databases/)
- [SQLAlchemy 2.0 asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Alembic async recipe](https://alembic.sqlalchemy.org/en/latest/cookbook.html#programmatic-api-use-connection-sharing-with-asyncio) · [Autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)

Validation & tooling
- [Pydantic v2](https://docs.pydantic.dev/latest/) · [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [PyJWT](https://pyjwt.readthedocs.io/en/stable/) · [pwdlib](https://frankie567.github.io/pwdlib/)
- [slowapi](https://slowapi.readthedocs.io/en/latest/)
- [uv](https://docs.astral.sh/uv/) · [Ruff rules](https://docs.astral.sh/ruff/rules/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/en/latest/) · [HTTPX AsyncClient](https://www.python-httpx.org/async/)
