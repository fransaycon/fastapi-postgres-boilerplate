---
name: fastapi-project-structure
description: 'Use when deciding where a new FastAPI file, module, router, model, schema, service, repository, or dependency should live; when adding a new domain/resource to the backend; when asked whether to use a flat layered layout vs feature slices/vertical slices; or when refactoring or reviewing FastAPI project organization. Covers the official FastAPI flat layout (app/api, app/core, app/models, app/schemas) and the layering rules that go with it.'
---

# FastAPI Project Structure

This project uses the **flat, technically-grouped layout** recommended by the FastAPI
docs and the official full-stack template — not feature/vertical slices.

## Canonical layout

```text
app/
├── api/
│   ├── dependencies.py   # DI: get_db, get_current_user, pagination, guards
│   └── v1/
│       ├── endpoints/    # one module per resource: users.py, auth.py
│       └── router.py     # aggregates the v1 routers
├── core/                 # framework-agnostic infrastructure
│   ├── config.py         # pydantic-settings
│   ├── database.py       # engine + sessionmaker + get_db generator
│   ├── security.py       # hashing, JWT encode/decode
│   ├── exceptions.py     # domain error types
│   └── rate_limit.py
├── models/               # SQLModel/SQLAlchemy persistence tables
├── schemas/              # Pydantic request/response contracts
├── services/             # business rules
├── repositories/         # database queries
└── main.py               # app factory, lifespan, middleware, handlers
```

## Where does this file go?

| If it... | It belongs in |
| --- | --- |
| maps to a database table | `models/` |
| shapes a request body or JSON response | `schemas/` |
| builds/filters/persists queries | `repositories/` |
| enforces a business rule or orchestrates repositories | `services/` |
| declares routes, status codes, rate limits | `api/v1/endpoints/` |
| is resolved per-request via `Depends()` | `api/dependencies.py` |
| defines roles or permissions | `core/permissions.py` |
| is a cross-cutting utility (pagination, etc.) | `core/` |
| imports no FastAPI symbols and is reusable infra | `core/` |

## Layering rules

```text
endpoints  →  services  →  repositories  →  models
     ↓            ↓
dependencies   schemas
```

- Dependencies flow **downward only**. A repository must never import a service; a
  service must never import a router.
- Services raise domain errors (`AppError` subclasses), never `HTTPException`.
  `main.py` maps them to HTTP responses so business logic stays transport-agnostic.
- `core/` must not import `fastapi`. `get_db` is a plain async generator in
  `core/database.py`; `api/dependencies.py` is what wraps it in `Depends()`.
- Schemas are not models. Never return a SQLModel table directly — serialize through a
  `*Public` schema so fields like `hashed_password` cannot leak.

## Adding a new domain

Touch these files, in order:

1. `app/models/<domain>.py` — the table
2. `app/schemas/<domain>.py` — `Create` / `Update` / `Public`
3. `app/repositories/<domain>_repo.py` — queries
4. `app/services/<domain>_service.py` — rules
5. `app/api/v1/endpoints/<domain>.py` — routes
6. `app/api/v1/router.py` — `api_router.include_router(...)`
7. `alembic revision --autogenerate` — migration
8. `tests/test_<domain>.py`

If the domain needs its own DI provider, add it to `api/dependencies.py`.

## Why not feature slices?

Vertical slices (`app/features/users/{models,schemas,service}.py`) are a legitimate
pattern and scale well past ~15 domains, but this project deliberately follows the
official layout so it matches the FastAPI docs, the full-stack template, and the bulk
of community examples. Do not migrate to slices piecemeal — a half-migrated tree is
worse than either option.

If `api/dependencies.py` becomes a grab bag, split it into an `api/deps/` package
(`db.py`, `auth.py`, `params.py`) with `__init__.py` re-exporting. That relieves the
pressure without changing the overall architecture.

## Pitfalls

- **Circular imports.** Usually a symptom of a layering violation. Fix the direction of
  the dependency rather than moving the import inside a function.
- **Alembic sees no tables.** Every model module must be imported before
  `SQLModel.metadata` is read. `app/models/__init__.py` re-exports them, and
  `alembic/env.py` imports `app.models`.
- **Version the API at the router, not the files.** Add `v2/` beside `v1/` and reuse
  the same services; do not fork `services/`.

## Reference

- [Bigger Applications – Multiple Files](https://fastapi.tiangolo.com/tutorial/bigger-applications/) — the official file-structure guide
- [Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template/tree/master/backend/app) — reference backend layout
- [Project Generation](https://fastapi.tiangolo.com/project-generation/)
- [APIRouter reference](https://fastapi.tiangolo.com/reference/apirouter/)
- [Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/) · [with yield](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/)
- [Separate OpenAPI Schemas for Input and Output](https://fastapi.tiangolo.com/how-to/separate-openapi-schemas/)
