# SciCat Access Management — Backend

FastAPI service that is the **source of truth** for SciCat access groups, membership,
resource grants, temporal access, and ownership transfer. It projects effective access
into SciCat's `UserIdentity.profile.accessGroups` and stamps `ownerGroup`/`accessGroups`
onto SciCat resources via the REST API. A built-in scheduler enforces expirations and
runs ownership transfers.

## Stack

FastAPI · Pydantic v2 · Motor (async MongoDB) · httpx (SciCat REST) · APScheduler · PyJWT.

## Layout

```
app/
  main.py            # app factory + lifespan (scheduler start/stop)
  config.py          # Settings (env-driven)
  db.py              # Motor clients (app DB + SciCat dacat DB), indexes
  context.py         # AppContext: shared services, injected clock
  auth/              # SciCat JWT validation + FastAPI deps (admin / group manager)
  models/            # Pydantic domain models
  services/          # groups, memberships, projection, reconcile, grants,
                     # transfers, audit, scicat_client, directory/
  scheduler/jobs.py  # expiry sweep + reconcile + expiry-driven transfers (Mongo lease lock)
  api/               # routers mounted under /api/v1
tests/
  unit/              # pure logic (no Mongo/SciCat)
  integration/       # API + in-memory Mongo + fake SciCat
```

## Run locally

```bash
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 3100
# health: http://localhost:3100/health   docs: http://localhost:3100/docs
```

Requires a reachable MongoDB (app DB + SciCat `dacat` DB) and a SciCat backend for JWT
validation. For a full stack use the docker-compose integration (below).

## Test

```bash
pip install -e ".[dev]"
pytest            # unit + integration (in-memory Mongo via mongomock-motor)
ruff check app/ tests/
```

## Configuration (env)

All settings have defaults (see `app/config.py`); override via environment.

| Variable | Default | Notes |
|----------|---------|-------|
| `APP_MONGO_URI` | `mongodb://localhost:27017` | App store |
| `APP_DB_NAME` | `scicat_access_mgmt` | |
| `SCICAT_MONGO_URI` | `mongodb://localhost:27017` | SciCat's Mongo (projection + directory) |
| `SCICAT_DB_NAME` | `dacat` | |
| `SCICAT_BASE_URL` | `http://localhost:80/api/v3` | SciCat REST base (whoami, resource PATCH) |
| `ADMIN_GROUPS` | `["admin"]` | JSON array; members are app admins |
| `JWT_SECRET` | _(unset)_ | Optional local signature pre-check; whoami is authoritative |
| `RESERVED_GROUPS` | SciCat specials | JSON array of names that cannot be created |
| `EXPIRY_SWEEP_SECONDS` | `300` | Scheduler expiry sweep interval |
| `RECONCILE_SECONDS` | `1800` | Scheduler reconcile interval |
| `CORS_ORIGINS` | dev origins | JSON array |

## API

All routes are under `/api/v1`. Highlights:

- `GET /me` — identity, current groups, isAdmin, managerOf
- `GET/POST /groups`, `GET/PATCH/DELETE /groups/{name}`
- `GET/POST /groups/{name}/members`, `PATCH/DELETE /memberships/{id}`
- `GET /users`, `GET /users/{id}/groups`, `POST /users/{id}/deactivate`
- `POST /projection/run`, `POST /projection/reconcile`, `GET /projection/status`
- `GET/POST /grants`, `DELETE /grants/{id}`, `GET /resources/{type}`
- `GET /expiry?withinDays=N`
- `GET/POST/PATCH/DELETE /transfer-rules`, `GET /transfer-records`
- `GET /audit` (admin)

See `../specs/001-scicat-access-mgmt/contracts/openapi.yaml` for the full contract.

## Auth model

Callers present their **SciCat JWT** (`Authorization: Bearer …`), validated via SciCat
`/auth/whoami`. Admin actions require membership of a configured `ADMIN_GROUPS`; group
managers can manage their own groups. With SSO configured in SciCat, users authenticate
through their institutional identity provider and the same token is used here.

## Deployment

Wired into both `../../dev-environment/docker-compose.yaml` (live reload, ports
3100/5174) and `../../deployment/docker-compose.yaml` (Traefik, served under
`/access-mgmt`). See those files and `../frontend/README.md`.
