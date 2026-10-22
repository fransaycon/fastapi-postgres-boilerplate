# FastAPI Boilerplate

A production-ready FastAPI backend starter using a 3-tiered architecture:
**routers → services → repositories**.

Rename the project by updating `name`/`description` in [pyproject.toml](pyproject.toml) and the
`PROJECT_NAME` / `POSTGRES_DB` values in your `.env`.

## Stack

| Concern | Choice |
| --- | --- |
| Framework | FastAPI (Python 3.12+) |
| Packaging | `uv` |
| Lint / format | Ruff |
| Database | PostgreSQL + SQLModel (SQLAlchemy 2.0 async) |
| Migrations | Alembic |
| Auth | Stateless JWT (access token + HttpOnly refresh cookie) |
| Rate limiting | `slowapi` |
| Tests | Pytest + HTTPX `AsyncClient` |

## Getting started

```bash
cp .env.example .env
# generate a real secret and paste it into .env as SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"
```

### With Docker (recommended)

Brings up Postgres and the API with hot reload:

```bash
docker compose up --build

docker compose exec api alembic revision --autogenerate -m "create users table"
docker compose exec api alembic upgrade head
```

### Locally

Requires a Postgres reachable at the `POSTGRES_*` values in `.env`. You can run just the
database from compose and keep the app on your host:

```bash
docker compose up -d db

uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Docs are served at `/docs` when `DEBUG=true`.

## Testing

**Pytest does not need Docker.** The suite defaults to an isolated in-memory SQLite database
created and dropped per test, so `uv run pytest` works in the local venv with no services
running.

```bash
uv run pytest             # default: in-memory SQLite, no infra required
docker compose exec api pytest   # inside the container
```

To validate against real Postgres (catches dialect-specific issues SQLite hides), start the
throwaway test database and point `TEST_DATABASE_URL` at it:

```bash
docker compose --profile test up -d db-test
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/test uv run pytest
```

`db-test` stores its data on tmpfs with `fsync=off`, and each test drops and recreates the
schema, so runs stay fast and isolated. Never point `TEST_DATABASE_URL` at a database you
care about.

## Common commands

```bash
uv run ruff check --fix  # lint
uv run ruff format       # format
uv run alembic upgrade head
docker compose logs -f api
docker compose down -v   # stop and delete the postgres volume
```

## Layering rules

- `api/` — HTTP concerns only: routing, dependency injection, rate limits, status codes.
- `services/` — business rules. Raises `AppError` subclasses, never `HTTPException`.
- `repositories/` — database queries. No business rules.
- `schemas/` — Pydantic request/response contracts. `UserPublic` never exposes `hashed_password`.
- `models/` — SQLModel tables.

## Auth flow

1. `POST /api/v1/auth/register` — create an account.
2. `POST /api/v1/auth/login` — form-encoded `username` (email) + `password`. Returns an access
   token in the body and sets an HttpOnly refresh cookie scoped to `/api/v1/auth`.
3. `POST /api/v1/auth/refresh` — exchanges the cookie for a new access token and rotates the
   refresh cookie.
4. `POST /api/v1/auth/logout` — clears the refresh cookie.
5. `GET /api/v1/users/me` — protected, requires `Authorization: Bearer <access_token>`.

Set `COOKIE_SECURE=true` and `COOKIE_SAMESITE=none` when the API and frontend are on
different origins over HTTPS.

## Roles & permissions

RBAC is hardcoded in [app/core/permissions.py](app/core/permissions.py) — no database
tables. Only the user's `role` column is persisted; permissions are derived from it.

| Role | Permissions |
| --- | --- |
| `admin` | `profile:read`, `profile:write`, `users:read`, `users:write`, `users:delete` |
| `user` | `profile:read`, `profile:write` |

Guard routes on a permission, never a role:

```python
@router.get("", dependencies=[Depends(require_permission(Permission.USERS_READ))])
```

New users get `DEFAULT_ROLE` (`user`). Promote one with:

```bash
docker compose exec db psql -U postgres -d app \
  -c "UPDATE users SET role='admin' WHERE email='you@example.com';"
```

`GET /api/v1/users/me` returns the caller's resolved `permissions` so a frontend can
drive its UI from them. Roles are never embedded in the JWT — `get_current_user` reloads
the user, so a role change takes effect on the next request.

## User management

| Method | Path | Permission |
| --- | --- | --- |
| `GET` | `/api/v1/users?page=1&size=20` | `users:read` |
| `POST` | `/api/v1/users` | `users:write` |
| `GET` | `/api/v1/users/{id}` | `users:read` |
| `PATCH` | `/api/v1/users/{id}` | `users:write` |
| `PATCH` | `/api/v1/users/{id}/password` | `users:write` |
| `DELETE` | `/api/v1/users/{id}` | `users:delete` |

`GET /users/me` and `PATCH /users/me` are self-service and need only authentication.

**Deletion is soft.** It sets `deleted_at`, deactivates the account, and rewrites the
email to `deleted+{uuid}@deleted.invalid`. The row is retained for audit, is excluded
from every read, cannot log in, and the original address becomes reusable immediately.

### Pagination

Any list endpoint gets pagination without boilerplate:

```python
async def list(self, params: PaginationParams) -> Page[User]:
    return await paginate(self.session, select(User), params)  # repository


page = await service.list(pagination)  # endpoint
return page.map(UserPublic.model_validate)
```

`PaginationDep` supplies validated `page`/`size` query params, `paginate()` runs the
count and page queries for any statement, and `Page[T]` serializes as:

```json
{ "items": [...], "total": 42, "page": 1, "size": 20, "pages": 3 }
```
