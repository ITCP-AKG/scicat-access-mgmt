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
  scheduler/jobs.py  # expiry sweep, login watcher, reconcile (Mongo lease lock)
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

Requires a reachable MongoDB (app DB + SciCat `dacat` DB), a SciCat backend for JWT
validation, and an admin functional account for resource calls
(`SCICAT_SERVICE_USERNAME`/`SCICAT_SERVICE_PASSWORD`). For a full stack use the
docker-compose integration (below).

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
| `SCICAT_BASE_URL` | `http://localhost:80/api/v3` | SciCat REST base (whoami, resource list/PATCH) |
| `SCICAT_SERVICE_USERNAME` / `SCICAT_SERVICE_PASSWORD` | _(unset)_ | **Required.** SciCat functional account in `ADMIN_GROUPS` (e.g. `admin`) used for every resource read/write; logged in lazily, re-login on expiry |
| `SCICAT_SERVICE_TOKEN` | _(unset)_ | Alternative to username/password (expires with SciCat's `JWT_EXPIRES_IN`) |
| `PERSONAL_GROUP_TEMPLATE` | _(empty)_ | A user's legacy personal ownerGroup, e.g. `{username}` (older catorga records). Only recognised on departure so a group successor takes such resources over; a user successor gets the contact fields and the resource is left `pending_manual`. Empty: transfers only hand over contact fields |
| `INVITE_LINK_BASE` | _(empty)_ | Invitation links are this + the token, e.g. `https://host/#/invite/` (catorga's invite page). Empty: only the token is returned |
| `INVITE_DEFAULT_DAYS` / `INVITE_MAX_DAYS` | `14` / `90` | How long an invitation link stays valid |
| `PROJECT_CASCADE_SECONDS` | `300` | How often project grants are extended to new records and refused project moves retried |
| `ADMIN_GROUPS` | `["admin"]` | JSON array; members are app admins |
| `JWT_SECRET` | _(unset)_ | Optional local signature pre-check; whoami is authoritative |
| `WHOAMI_CACHE_SECONDS` | `60` | Per-token cache of SciCat whoami answers |
| `RESERVED_GROUPS` | SciCat specials | JSON array of names that cannot be created |
| `EXPIRY_SWEEP_SECONDS` | `300` | Scheduler expiry sweep interval |
| `LOGIN_WATCH_SECONDS` | `15` | Re-project identities rewritten by a SciCat login |
| `RECONCILE_SECONDS` | `1800` | Scheduler reconcile interval (also runs at startup) |
| `CORS_ORIGINS` | dev origins | JSON array |

## API

All routes are under `/api/v1`. Highlights:

- `GET /me` — identity, current groups, isAdmin, managerOf (re-projects the caller first)
- `GET/POST /groups`, `GET /groups/-/name-check?name=`, `GET/PATCH/DELETE /groups/{name}`
- `GET/POST /groups/{name}/members`, `PATCH/DELETE /memberships/{id}`
- `GET /users`, `GET /users/{id}`, `GET /users/{id}/groups`, `POST /users/{id}/deactivate`
- `POST /projection/run`, `POST /projection/reconcile`, `GET /projection/status` (admin)
- `POST /proposals`, `PATCH /proposals/{id}` (proposal write proxy)
- `POST /invites`, `GET /invites?groupName=`, `DELETE /invites/{id}` (group managers);
  `GET /invites/by-token/{token}` (no login), `POST /invites/by-token/{token}/accept`
- `GET/POST /grants`, `DELETE /grants/{id}` (204, or 202 while SciCat refuses),
  `GET /grants?parentGrantId=` (a project grant's per-record children),
  `GET /resources/{project|dataset|origdatablock|proposal|sample}`
- `POST /projects/{proposalId}/sync` (extend the project's grants to new records)
- `GET /expiry?withinDays=N`
- `GET/POST/PATCH/DELETE /transfer-rules`, `GET /transfer-records`, `GET /transfer-batches`,
  `POST /transfer-batches/{id}/retry` (admin)
- `GET /audit` (admin)

See `../specs/001-scicat-access-mgmt/contracts/openapi.yaml` for the full contract.

## Auth model

Callers present their **SciCat JWT** (`Authorization: Bearer …`), validated via SciCat
`/auth/whoami` (401 = token rejected, 503 = SciCat unavailable). Admin actions require
membership of a configured `ADMIN_GROUPS`. Group managers manage their own groups: members
and description. Managers also get **member access** to the groups they manage (projection
treats them as members). Sharing is decided by the owner side: a manager may grant any
active group access to resources owned by a group they manage; the receiving group's
managers may withdraw such a grant. Owner grants, transfers and the audit log are
admin-only. Proposals are written through `POST/PATCH /proposals` (SciCat only lets `admin`
write them): admins and managers of the active ownerGroup create, its members and managers
edit. A username is never treated as a group (SciCat does not put it into currentGroups).
Directory and grant views need admin or manager rights; `/me` is open to every
authenticated user. All SciCat resource calls run as the service account, so these checks
are the only guard.

## SciCat integration notes

- SciCat (v4.3.1) re-reads `profile.accessGroups` on every request, so projection takes
  effect immediately — but every login rewrites that array. The login watcher and `/me`
  restore the app-managed groups; the app never touches SciCat's `modified` timestamp.
- Projection removes only names the app manages (registered groups and what it last wrote
  per user); other strings are preserved.
- Only datasets, origdatablocks, proposals and samples carry ownerGroup/accessGroups.
- A catorga **project** is a proposal plus the samples (`SampleBase.proposal`), datasets
  (`proposalId`) and origdatablocks linked to it, as far as the proposal's ownerGroup owns
  them. A project grant (`resourceType: "project"`, access mode) shares all of them,
  including records added later (`project-cascade` job, or `POST /projects/{id}/sync`).
  Changing a proposal's ownerGroup through `PATCH /proposals/{id}` moves the project's
  records and their attachments along (`project_moves`; refusals are retried).
  Attachment reads are not filtered per attachment in SciCat v4.3.1, so sharing does not
  need to touch them.
- Deactivating a user ends their memberships and transfers what they personally own; it
  does not block their SciCat login (do that in the identity provider).

## Deployment

Wired into both `../../dev-environment/docker-compose.yaml` (live reload, ports
3100/5174) and `../../deployment/docker-compose.yaml` (Traefik, served under
`/access-mgmt`). See those files and `../frontend/README.md`.
