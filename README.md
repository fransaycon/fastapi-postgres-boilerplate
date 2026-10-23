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

| Service | URL | Notes |
| --- | --- | --- |
| API | http://localhost:8000 | `/docs` when `DEBUG=true` |
| pgAdmin | http://localhost:5050 | both databases pre-registered |

### pgAdmin

Sign in with `PGADMIN_EMAIL` / `PGADMIN_PASSWORD` from `.env` (defaults
`admin@example.com` / `admin`). Both servers are already registered and the passwords are
supplied via [docker/pgadmin/pgpass](docker/pgadmin/pgpass) — no connection setup needed.

| Registered server | Compose service | Available when |
| --- | --- | --- |
| `app (dev)` | `db` | always |
| `test (throwaway)` | `db-test` | only under `--profile test` |

Server registration happens **only when the `pgadmin_data` volume is first created**. If
you edit [docker/pgadmin/servers.json](docker/pgadmin/servers.json), re-import with:

```bash
docker compose down pgadmin
docker volume rm fastapi-boilerplate_pgadmin_data
docker compose up -d pgadmin
```

This setup is for local development only — it disables the pgAdmin master password and
ships a plaintext `pgpass`. Do not reuse it anywhere reachable from a network.

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

## Git hooks & commit conventions

[pre-commit](https://pre-commit.com/) replaces husky *and* lint-staged — hooks receive
only the staged files, and unstaged work is stashed while they run.

```bash
uv run pre-commit install      # one-time, after cloning
uv run pre-commit run --all-files
uv run pre-commit autoupdate   # bump pinned hook revisions
```

| Stage | Runs |
| --- | --- |
| `pre-commit` | whitespace/EOF/YAML/TOML checks, private-key & merge-conflict detection, `ruff check --fix`, `ruff format`, `uv lock` |
| `commit-msg` | Commitizen conventional-commit validation |
| `pre-push` | `pytest` |

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) and
are enforced by [Commitizen](https://commitizen-tools.github.io/commitizen/):

```bash
uv run cz commit    # interactive prompt that builds the message for you
uv run cz bump      # bump version + tag + update CHANGELOG from commit history
```

```text
feat(users): add admin management endpoints
fix(auth): reject refresh tokens used as access tokens
```

Skip hooks only when you genuinely must: `git commit --no-verify`.

## Layering rules

- `api/` — HTTP concerns only: routing, dependency injection, rate limits, status codes.
- `services/` — business rules. Raises `AppError` subclasses, never `HTTPException`.
- `repositories/` — database queries. No business rules.
- `schemas/` — Pydantic request/response contracts. `UserPublic` never exposes `hashed_password`.
- `models/` — SQLModel tables.

## Auth flow

**There is no public registration.** Every account is provisioned by an admin through
`POST /api/v1/users`, so the only unauthenticated endpoint is login.

1. `POST /api/v1/auth/login` — form-encoded `username` (email) + `password`. Returns an access
   token in the body and sets an HttpOnly refresh cookie scoped to `/api/v1/auth`.
2. `POST /api/v1/auth/refresh` — exchanges the cookie for a new access token and rotates the
   refresh cookie.
3. `POST /api/v1/auth/logout` — revokes this device's session and clears the cookie.
4. `GET /api/v1/users/me` — protected, requires `Authorization: Bearer <access_token>`.

Bootstrapping the first admin is a database operation, not an API call — see below.

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

New users default to `DEFAULT_ROLE` (`user`) unless the creating admin says otherwise.
Promote one directly when bootstrapping:

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
